"""Server-only device authorization and rotating credentials.

Adapted from alex-tavern-plugins/plugins/grok_supergrok/oauth.py for H3:
Python 3.12 exception syntax, H3 User-Agent, and no out-of-scope billing API.
Protocol reference: OpenClaw 7cfdcc6e7590f606656f782cc48eb2b1f30ac42b,
extensions/xai/xai-oauth.ts. This does not establish third-party client rights.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

ISSUER = "https://auth.x.ai"
DISCOVERY = f"{ISSUER}/.well-known/openid-configuration"
DEVICE_ENDPOINT = f"{ISSUER}/oauth2/device/code"
TOKEN_ENDPOINT = f"{ISSUER}/oauth2/token"
# The account pilot accepted OAuth here; the CLI proxy rejected requests with 426.
# A fixed route prevents silent changes of endpoint or billing bucket.
BASE_URL = "https://api.x.ai/v1"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class OAuthError(RuntimeError):
    """Only stable, local messages may reach the UI, journal or LLM log."""

    def __init__(self, code: str, detail: str, status: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status


@dataclass(frozen=True, slots=True)
class Tokens:
    access: str = field(repr=False)
    refresh: str = field(repr=False)
    expires_at: float
    refresh_at: float


class CatalogRejected(OAuthError):
    def __init__(self, tokens: Tokens) -> None:
        super().__init__(
            "catalog_unauthorized", "SuperGrok catalog rejected the access token.", 401
        )
        self.tokens = tokens


@dataclass(slots=True)
class Flow:
    nonce: str = field(repr=False)
    device_code: str = field(repr=False)
    user_code: str = field(repr=False)
    verification_uri: str = field(repr=False)
    expires_at: float
    deadline: float
    interval: float
    phase: str = "pending"
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "flow_id": self.nonce,
            "phase": self.phase,
            "user_code": self.user_code if self.phase == "pending" else "",
            "verification_uri": self.verification_uri if self.phase == "pending" else "",
            "expires_at": self.expires_at,
            "error": self.error,
        }


def _number(value: object, label: str, *, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
        or value <= 0
        or value > maximum
    ):
        raise OAuthError("invalid_response", f"xAI returned invalid {label}.", 502)
    return float(value)


def _text(value: object, label: str, *, maximum: int = 8192) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise OAuthError("invalid_response", f"xAI returned invalid {label}.", 502)
    return value.strip()


def validate_base(value: str) -> None:
    if value.rstrip("/") != BASE_URL:
        raise ValueError("SuperGrok uses only the fixed HTTPS OAuth inference endpoint.")


def _verification_uri(value: object) -> str:
    uri = _text(value, "verification URL", maximum=2048)
    parts = urlsplit(uri)
    if (
        parts.scheme != "https"
        or parts.hostname not in ("auth.x.ai", "accounts.x.ai", "grok.com")
        or parts.username is not None
        or parts.password is not None
        or parts.netloc != parts.hostname
        or parts.fragment
    ):
        raise OAuthError("untrusted_endpoint", "xAI returned an untrusted verification URL.", 502)
    return uri


class OAuthManager:
    def __init__(
        self,
        credential_path: Path,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = credential_path
        self.client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=30, follow_redirects=False)
        )
        self.clock = clock
        self.monotonic = monotonic
        self._lock = asyncio.Lock()
        self._flow: Flow | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._last_start = float("-inf")
        self._load_error: str | None = None
        try:
            self._tokens = self._load()
        except OAuthError as error:
            self._tokens = None
            self._load_error = str(error)
        self._models: list[dict[str, Any]] = []
        self._catalog_access: str | None = None
        self._catalog_at = 0.0

    def _load(self) -> Tokens | None:
        if not self.path.exists():
            return None
        try:
            if self.path.stat().st_mode & 0o077:
                raise ValueError("insecure credential mode")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data is None:
                return None
            if data["schema_version"] != 1:
                raise ValueError("wrong credential version")
            return Tokens(
                _text(data["access_token"], "access token"),
                _text(data["refresh_token"], "refresh token"),
                _number(data["expires_at"], "expiry", maximum=10**12),
                _number(data["refresh_at"], "refresh time", maximum=10**12),
            )
        except (OSError, ValueError, TypeError, KeyError, OAuthError):
            raise OAuthError(
                "invalid_credentials", "Stored SuperGrok credentials are invalid; reconnect.", 409
            ) from None

    def _persist(self, tokens: Tokens | None) -> None:
        # Atomic publication keeps a crash from pairing a new access token with
        # an already-consumed refresh token. H3 must never serve this private path.
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        data = (
            {
                "schema_version": 1,
                "access_token": tokens.access,
                "refresh_token": tokens.refresh,
                "expires_at": tokens.expires_at,
                "refresh_at": tokens.refresh_at,
            }
            if tokens is not None
            else None
        )
        descriptor, temporary = tempfile.mkstemp(prefix=".oauth-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._tokens = tokens
        self._load_error = None
        self._models = []
        self._catalog_access = None

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        form: dict[str, str] | None = None,
        access: str | None = None,
        timeout: float = 30,
    ) -> tuple[int, dict[str, Any]]:
        if url not in (
            DISCOVERY,
            DEVICE_ENDPOINT,
            TOKEN_ENDPOINT,
            f"{BASE_URL}/models",
        ):
            raise OAuthError("untrusted_endpoint", "Untrusted SuperGrok endpoint.", 502)
        headers = {"Accept": "application/json", "User-Agent": "H3-SuperGrok/0.1"}
        if access:
            headers["Authorization"] = f"Bearer {access}"
        try:
            async with (
                asyncio.timeout(max(0.1, timeout)),
                client.stream(
                    method,
                    url,
                    data=form,
                    headers=headers,
                    timeout=max(0.1, timeout),
                    follow_redirects=False,
                ) as response,
            ):
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise OAuthError(
                            "invalid_response", "xAI response exceeds size limit.", 502
                        )
                status = response.status_code
                if 300 <= status < 400:
                    raise OAuthError("untrusted_endpoint", "xAI redirects are not permitted.", 502)
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise OAuthError("invalid_response", "xAI returned a non-object response.", 502)
                return status, value
        except (httpx.HTTPError, TimeoutError):
            raise OAuthError(
                "network_error", "Could not contact xAI. Try again or reconnect.", 502
            ) from None
        except (ValueError, UnicodeError):
            raise OAuthError(
                "invalid_response", "xAI returned an invalid JSON response.", 502
            ) from None

    async def _discover(self, client: httpx.AsyncClient) -> None:
        status, data = await self._request(client, "GET", DISCOVERY)
        if (
            status != 200
            or data.get("issuer") != ISSUER
            or data.get("token_endpoint") != TOKEN_ENDPOINT
            or data.get("device_authorization_endpoint") != DEVICE_ENDPOINT
            or DEVICE_GRANT not in data.get("grant_types_supported", [])
        ):
            raise OAuthError(
                "untrusted_endpoint",
                "xAI OAuth discovery does not match the trusted protocol.",
                502,
            )

    def _parse_tokens(self, data: dict[str, Any], old: Tokens | None = None) -> Tokens:
        if "scope" in data:
            scope = _text(data["scope"], "scope").split()
            if not {"api:access", "grok-cli:access"}.issubset(scope):
                raise OAuthError(
                    "missing_scope", "xAI did not grant the required API access. Reconnect.", 403
                )
        if _text(data.get("token_type", "Bearer"), "token type").lower() != "bearer":
            raise OAuthError("invalid_response", "xAI returned an unsupported token type.", 502)
        lifetime = _number(data.get("expires_in"), "token lifetime", maximum=31_536_000)
        now = self.clock()
        return Tokens(
            _text(data.get("access_token"), "access token"),
            _text(data.get("refresh_token", old.refresh if old else None), "refresh token"),
            now + lifetime,
            now + lifetime - min(60, lifetime / 10),
        )

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self._closed:
                raise OAuthError("closed", "SuperGrok provider is shutting down.", 503)
            if self._flow is not None and self._flow.phase == "pending":
                raise OAuthError("flow_active", "A SuperGrok login is already in progress.", 409)
            if self.monotonic() - self._last_start < 10:
                raise OAuthError(
                    "rate_limited", "Wait a few seconds before starting another login.", 429
                )
            self._last_start = self.monotonic()
            async with self.client_factory() as client:
                await self._discover(client)
                status, data = await self._request(
                    client, "POST", DEVICE_ENDPOINT, form={"client_id": CLIENT_ID, "scope": SCOPE}
                )
            if self._closed:
                raise OAuthError("closed", "SuperGrok provider is shutting down.", 503)
            if status != 200:
                raise OAuthError("device_denied", "xAI could not start device authorization.", 403)
            lifetime = _number(data.get("expires_in"), "device lifetime", maximum=3600)
            flow = Flow(
                secrets.token_urlsafe(32),
                _text(data.get("device_code"), "device code"),
                _text(data.get("user_code"), "user code", maximum=128),
                _verification_uri(data.get("verification_uri")),
                self.clock() + lifetime,
                self.monotonic() + lifetime,
                max(1.0, _number(data.get("interval", 5), "polling interval", maximum=3600)),
            )
            self._flow = flow
            self._task = asyncio.create_task(self._poll(flow), name="supergrok-device-flow")
            return flow.public()

    async def _poll(self, flow: Flow) -> None:
        try:
            async with self.client_factory() as client:
                while True:
                    remaining = flow.deadline - self.monotonic()
                    if remaining <= 0:
                        flow.phase = "expired"
                        return
                    await asyncio.sleep(min(flow.interval, remaining))
                    async with self._lock:
                        if self._closed or self._flow is not flow or flow.phase != "pending":
                            return
                        remaining = flow.deadline - self.monotonic()
                        if remaining <= 0:
                            flow.phase = "expired"
                            return
                        status, data = await self._request(
                            client,
                            "POST",
                            TOKEN_ENDPOINT,
                            form={
                                "grant_type": DEVICE_GRANT,
                                "client_id": CLIENT_ID,
                                "device_code": flow.device_code,
                            },
                            timeout=min(30, remaining),
                        )
                        if self._closed or self._flow is not flow or flow.phase != "pending":
                            return
                        if status == 200:
                            if self.monotonic() >= flow.deadline:
                                flow.phase = "expired"
                                return
                            self._persist(self._parse_tokens(data))
                            flow.phase = "connected"
                            return
                        error = data.get("error")
                        if status == 400 and error == "authorization_pending":
                            continue
                        if status == 400 and error == "slow_down":
                            flow.interval += 5
                            continue
                        flow.phase = (
                            "denied"
                            if error == "access_denied"
                            else "expired"
                            if error == "expired_token"
                            else "error"
                        )
                        flow.error = "xAI did not authorize this login. Check account eligibility and try again."
                        return
        except asyncio.CancelledError:
            raise
        except OAuthError as error:
            flow.phase = "error"
            flow.error = str(error)
        except Exception:  # noqa: BLE001 -- Contain task failures without logging OAuth bodies.
            flow.phase = "error"
            flow.error = "SuperGrok login could not be saved. Try again."
        finally:
            # Retain only the public result until another attempt starts.
            flow.device_code = ""
            flow.user_code = ""
            flow.verification_uri = ""

    async def flow_status(self, nonce: str) -> dict[str, Any]:
        async with self._lock:
            flow = self._flow
            if flow is None or not secrets.compare_digest(nonce, flow.nonce):
                raise OAuthError("flow_not_found", "This login flow is unavailable.", 404)
            return flow.public()

    def _interrupt_flow(self) -> asyncio.Task[None] | None:
        # All manager operations run on one event loop. Retire the flow and cancel
        # its I/O BEFORE awaiting its lock: a pending token response must not win
        # the race against the user's cancellation intent.
        if self._flow is not None:
            self._flow.phase = "cancelled"
            self._flow.device_code = ""
            self._flow.user_code = ""
            self._flow.verification_uri = ""
        task = self._task
        if task and not task.done():
            task.cancel()
        return task

    async def cancel(self, nonce: str) -> None:
        flow = self._flow
        if flow is None or not secrets.compare_digest(nonce, flow.nonce):
            raise OAuthError("flow_not_found", "This login flow is unavailable.", 404)
        just_connected = flow.phase == "connected"
        task = self._interrupt_flow()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            # The browser may cancel after the grant arrived but before it saw
            # the completion. Cancel that flow's grant, not a later login's.
            if just_connected and self._flow is flow:
                self._persist(None)

    async def disconnect(self) -> None:
        task = self._interrupt_flow()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            self._persist(None)

    async def close(self) -> None:
        # Shutdown cancels the ephemeral authorization, not a persisted grant.
        self._closed = True
        if self._flow is not None and self._flow.phase == "pending":
            task = self._interrupt_flow()
        else:
            task = self._task
        if task:
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            pass

    async def connection_status(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "connected": self._tokens is not None,
                "expires_at": self._tokens.expires_at if self._tokens else None,
                "subscription_verified": False,
                "error": self._load_error,
            }

    async def _access_locked(
        self, client: httpx.AsyncClient, rejected_access: str | None = None
    ) -> Tokens:
        if self._closed:
            raise OAuthError("closed", "SuperGrok provider is shutting down.", 503)
        tokens = self._tokens
        if tokens is None:
            raise OAuthError(
                "login_required", "Connect your SuperGrok account before using this provider.", 401
            )
        if self.clock() < tokens.refresh_at and (
            rejected_access is None or rejected_access != tokens.access
        ):
            return tokens
        try:
            await self._discover(client)
            # Retire the rotating grant durably BEFORE sending it. A process
            # interruption after server-side consumption must require reconnect,
            # not resurrect the last refresh token from disk on the next boot.
            self._persist(None)
            status, data = await self._request(
                client,
                "POST",
                TOKEN_ENDPOINT,
                form={
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "refresh_token": tokens.refresh,
                },
            )
            if status != 200:
                raise OAuthError(
                    "refresh_failed",
                    "SuperGrok authorization expired or was refused. Reconnect.",
                    401,
                )
            new_tokens = self._parse_tokens(data, tokens)
            self._persist(new_tokens)
            return new_tokens
        except asyncio.CancelledError:
            # A cancellation can occur after the server consumed a rotating grant.
            self._persist(None)
            raise
        except Exception:  # noqa: BLE001 -- Any ambiguous rotating refresh invalidates the grant.
            self._persist(None)
            raise OAuthError(
                "reconnect_required",
                "SuperGrok refresh could not be confirmed. Reconnect safely.",
                401,
            ) from None

    async def access(self, client: httpx.AsyncClient, rejected_access: str | None = None) -> Tokens:
        async with self._lock:
            return await self._access_locked(client, rejected_access)

    async def refresh(self, client: httpx.AsyncClient) -> dict[str, Any]:
        # Snapshot the immutable generation before waiting: concurrent callers
        # consume one rotation, not a new rotation each time the lock is released.
        observed = self._tokens
        async with self._lock:
            rejected = (
                observed.access if observed is not None and observed is self._tokens else None
            )
            tokens = await self._access_locked(client, rejected)
            return {"connected": True, "expires_at": tokens.expires_at}

    def _current_tokens_locked(self) -> Tokens:
        tokens = self._tokens
        if self._closed or tokens is None or self.clock() >= tokens.expires_at:
            raise OAuthError(
                "authorization_required",
                "A current SuperGrok authorization is required for this read-only check.",
                401,
            )
        return tokens

    async def authorized_models(
        self, client: httpx.AsyncClient, *, recover: bool = True, refresh: bool = True
    ) -> tuple[Tokens, list[dict[str, Any]]]:
        async with self._lock:
            tokens = await self._access_locked(client) if refresh else self._current_tokens_locked()
            if self._catalog_access == tokens.access and self.monotonic() - self._catalog_at < 60:
                return tokens, list(self._models)
            status, data = await self._request(
                client, "GET", f"{BASE_URL}/models", access=tokens.access
            )
            if status == 401:
                if not recover or not refresh:
                    # Inference lets the shared client count this against the
                    # SAME recovery budget as a subsequent generation 401.
                    raise CatalogRejected(tokens)
                tokens = await self._access_locked(client, tokens.access)
                status, data = await self._request(
                    client, "GET", f"{BASE_URL}/models", access=tokens.access
                )
            if status != 200:
                raise OAuthError(
                    "catalog_unavailable",
                    "Could not read your SuperGrok model catalog. Reconnect or check eligibility.",
                    403 if status in (401, 403) else 502,
                )
            rows = data.get("data")
            if not isinstance(rows, list):
                raise OAuthError("invalid_response", "xAI model catalog is invalid.", 502)
            models: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise OAuthError("invalid_response", "xAI model catalog row is invalid.", 502)
                identifier = _text(row.get("id"), "model ID", maximum=256)
                backend = row.get("api_backend")
                if backend is not None and backend not in ("responses", "chat", "language"):
                    continue
                if identifier in seen:
                    continue
                seen.add(identifier)
                model: dict[str, Any] = {"id": identifier, "name": identifier}
                for key in ("context_window", "max_completion_tokens"):
                    if key in row:
                        model[key] = int(_number(row[key], key, maximum=10**9))
                models.append(model)
            if not models:
                raise OAuthError(
                    "no_models", "Your xAI account returned no eligible text models.", 403
                )
            self._models = models
            self._catalog_access = tokens.access
            self._catalog_at = self.monotonic()
            return tokens, list(models)
