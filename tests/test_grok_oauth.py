"""Offline OAuth tests adapted from grok_supergrok/tests/test_oauth.py.

No account, real data directory, or billable inference; Tavern adapter tests are
excluded and catalog assertions exercise the H3 OAuth manager directly.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest

from h3_backend.infrastructure import grok_oauth as oauth


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


DISCOVERY_DATA = {
    "issuer": oauth.ISSUER,
    "token_endpoint": oauth.TOKEN_ENDPOINT,
    "device_authorization_endpoint": oauth.DEVICE_ENDPOINT,
    "grant_types_supported": [oauth.DEVICE_GRANT],
}
TOKEN_DATA = {
    "access_token": "ACCESS-SENTINEL",
    "refresh_token": "REFRESH-SENTINEL",
    "expires_in": 120,
    "token_type": "Bearer",
}
DEVICE_DATA = {
    "device_code": "DEVICE-SENTINEL",
    "user_code": "USER-CODE",
    "verification_uri": "https://auth.x.ai/device",
    "expires_in": 60,
    "interval": 1,
}


def manager(tmp_path, handler, clock=None):
    clock = clock or Clock()
    transport = httpx.MockTransport(handler)
    return oauth.OAuthManager(
        tmp_path / "private" / "oauth.json",
        client_factory=lambda: httpx.AsyncClient(transport=transport),
        clock=clock,
        monotonic=clock,
    )


def run(coroutine):
    return asyncio.run(coroutine)


def fast_poll(monkeypatch, clock):
    original = asyncio.sleep

    async def sleep(seconds):
        clock.value += seconds
        await original(0)

    monkeypatch.setattr(oauth.asyncio, "sleep", sleep)


def test_login_pending_slow_down_success_restart_and_disconnect(tmp_path, monkeypatch):
    clock = Clock()
    fast_poll(monkeypatch, clock)
    seen = []
    outcomes = [
        (400, {"error": "authorization_pending"}),
        (400, {"error": "slow_down"}),
        (200, TOKEN_DATA),
    ]

    def handler(request):
        seen.append(request)
        assert request.headers["user-agent"] == "H3-SuperGrok/0.1"
        if str(request.url) == oauth.DISCOVERY:
            return httpx.Response(200, json=DISCOVERY_DATA)
        if str(request.url) == oauth.DEVICE_ENDPOINT:
            assert "client_id=" in request.content.decode()
            return httpx.Response(200, json=DEVICE_DATA)
        status, value = outcomes.pop(0)
        return httpx.Response(status, json=value)

    async def check():
        auth = manager(tmp_path, handler, clock)
        started = await auth.start()
        assert started["user_code"] == "USER-CODE"
        assert "DEVICE-SENTINEL" not in json.dumps(started)
        assert "DEVICE-SENTINEL" not in repr(auth._flow)
        await auth._task
        done = await auth.flow_status(started["flow_id"])
        assert done["phase"] == "connected"
        assert done["user_code"] == done["verification_uri"] == ""
        assert auth._flow.interval == 6
        assert auth.path.stat().st_mode & 0o777 == 0o600
        assert auth.path.parent.stat().st_mode & 0o777 == 0o700
        reopened = manager(tmp_path, handler, clock)
        assert (await reopened.connection_status())["connected"]
        assert "ACCESS-SENTINEL" not in repr(reopened._tokens)
        await reopened.disconnect()
        assert not (await manager(tmp_path, handler, clock).connection_status())["connected"]
        await auth.close()
        await reopened.close()

    run(check())
    assert len(seen) == 5


@pytest.mark.parametrize(
    "error,phase",
    [("access_denied", "denied"), ("expired_token", "expired"), ("bad_grant", "error")],
)
def test_device_terminal_errors_do_not_echo_provider_body(tmp_path, monkeypatch, error, phase):
    clock = Clock()
    fast_poll(monkeypatch, clock)

    def handler(request):
        if str(request.url) == oauth.DISCOVERY:
            return httpx.Response(200, json=DISCOVERY_DATA)
        if str(request.url) == oauth.DEVICE_ENDPOINT:
            return httpx.Response(200, json=DEVICE_DATA)
        return httpx.Response(400, json={"error": error, "error_description": "REFRESH-SENTINEL"})

    async def check():
        auth = manager(tmp_path, handler, clock)
        started = await auth.start()
        await auth._task
        result = await auth.flow_status(started["flow_id"])
        assert result["phase"] == phase
        assert "SENTINEL" not in json.dumps(result)
        assert not auth.path.exists()
        await auth.close()

    run(check())


def test_device_deadline_never_polls_after_expiry(tmp_path, monkeypatch):
    clock = Clock()
    fast_poll(monkeypatch, clock)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json=DISCOVERY_DATA
            if str(request.url) == oauth.DISCOVERY
            else {**DEVICE_DATA, "expires_in": 1},
        )

    async def check():
        auth = manager(tmp_path, handler, clock)
        started = await auth.start()
        await auth._task
        assert (await auth.flow_status(started["flow_id"]))["phase"] == "expired"
        assert oauth.TOKEN_ENDPOINT not in calls
        await auth.close()

    run(check())


def test_nonce_cancel_rate_limit_and_shutdown(tmp_path):
    def handler(request):
        return httpx.Response(
            200, json=DISCOVERY_DATA if str(request.url) == oauth.DISCOVERY else DEVICE_DATA
        )

    async def check():
        auth = manager(tmp_path, handler)
        started = await auth.start()
        with pytest.raises(oauth.OAuthError, match="already"):
            await auth.start()
        with pytest.raises(oauth.OAuthError, match="unavailable"):
            await auth.cancel("not-the-owner")
        with pytest.raises(oauth.OAuthError, match="unavailable"):
            await auth.flow_status("not-the-owner")
        await auth.cancel(started["flow_id"])
        assert auth._task.done()
        assert (await auth.flow_status(started["flow_id"]))["phase"] == "cancelled"
        with pytest.raises(oauth.OAuthError, match="Wait"):
            await auth.start()
        await auth.close()
        with pytest.raises(oauth.OAuthError, match="shutting down"):
            await auth.start()

    run(check())


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.example/token",
        "http://auth.x.ai/oauth2/token",
        "https://user:pass@auth.x.ai/oauth2/token",
        "https://auth.x.ai:443/oauth2/token",
    ],
)
def test_discovery_rejects_untrusted_endpoint(tmp_path, endpoint):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={**DISCOVERY_DATA, "token_endpoint": endpoint})

    async def check():
        auth = manager(tmp_path, handler)
        with pytest.raises(oauth.OAuthError, match="trusted"):
            await auth.start()
        assert calls == [oauth.DISCOVERY]
        await auth.close()

    run(check())


def test_redirect_and_html_are_safe(tmp_path):
    for response in (
        httpx.Response(302, headers={"Location": "https://evil.example"}),
        httpx.Response(200, text="<html>ACCESS-SENTINEL</html>"),
    ):

        async def check(response=response):
            auth = manager(tmp_path, lambda request: response)
            with pytest.raises(oauth.OAuthError) as caught:
                await auth.start()
            assert "SENTINEL" not in str(caught.value)
            await auth.close()

        run(check())


def test_single_flight_rotating_refresh_and_stale_rejection(tmp_path):
    clock = Clock()
    refreshes = []

    def handler(request):
        if str(request.url) == oauth.DISCOVERY:
            return httpx.Response(200, json=DISCOVERY_DATA)
        refreshes.append(request.content)
        return httpx.Response(
            200, json={**TOKEN_DATA, "access_token": "NEW-ACCESS", "refresh_token": "NEW-REFRESH"}
        )

    async def check():
        auth = manager(tmp_path, handler, clock)
        auth._persist(auth._parse_tokens(TOKEN_DATA))
        clock.value += 121
        async with auth.client_factory() as client:
            values = await asyncio.gather(
                *(auth.access(client, "ACCESS-SENTINEL") for _ in range(12))
            )
            assert all(value.access == "NEW-ACCESS" for value in values)
            assert len(refreshes) == 1
            await auth.access(client, "ACCESS-SENTINEL")
            assert len(refreshes) == 1
        persisted = json.loads(auth.path.read_text())
        assert persisted["refresh_token"] == "NEW-REFRESH"
        await auth.close()

    run(check())


def test_ambiguous_refresh_clears_credentials_without_retry(tmp_path):
    refreshes = []

    def handler(request):
        if str(request.url) == oauth.DISCOVERY:
            return httpx.Response(200, json=DISCOVERY_DATA)
        refreshes.append(request)
        raise httpx.ReadTimeout("REFRESH-SENTINEL", request=request)

    async def check():
        auth = manager(tmp_path, handler)
        auth._persist(auth._parse_tokens(TOKEN_DATA))
        async with auth.client_factory() as client:
            with pytest.raises(oauth.OAuthError, match="Reconnect safely") as caught:
                await auth.access(client, "ACCESS-SENTINEL")
            assert "SENTINEL" not in str(caught.value)
            with pytest.raises(oauth.OAuthError, match="Connect"):
                await auth.access(client)
        assert len(refreshes) == 1
        assert json.loads(auth.path.read_text()) is None
        await auth.close()

    run(check())


def test_logout_waits_for_refresh_and_cannot_resurrect_tokens(tmp_path):
    async def check():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            if str(request.url) == oauth.DISCOVERY:
                return httpx.Response(200, json=DISCOVERY_DATA)
            entered.set()
            await release.wait()
            return httpx.Response(200, json=TOKEN_DATA)

        auth = manager(tmp_path, handler)
        auth._persist(auth._parse_tokens(TOKEN_DATA))
        async with auth.client_factory() as client:
            refreshing = asyncio.create_task(auth.access(client, "ACCESS-SENTINEL"))
            await entered.wait()
            logout = asyncio.create_task(auth.disconnect())
            release.set()
            await asyncio.gather(refreshing, logout)
        assert not (await auth.connection_status())["connected"]
        assert json.loads(auth.path.read_text()) is None
        await auth.close()

    run(check())


def test_catalog_model_policy_cache_and_credentials_repr(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.headers["authorization"] == "Bearer ACCESS-SENTINEL"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "grok-test", "api_backend": "responses", "context_window": 32768},
                    {"id": "image-only", "api_backend": "image"},
                ]
            },
        )

    async def check():
        auth = manager(tmp_path, handler)
        auth._persist(auth._parse_tokens(TOKEN_DATA))
        async with auth.client_factory() as client:
            tokens, models = await auth.authorized_models(client)
            assert "SENTINEL" not in repr(tokens)
            assert models == [{"id": "grok-test", "name": "grok-test", "context_window": 32768}]
            assert await auth.authorized_models(client) == (tokens, models)
            assert calls == [f"{oauth.BASE_URL}/models"]
        await auth.close()

    run(check())


def test_invalid_stored_credentials_still_allow_reconnect_ui(tmp_path):
    path = tmp_path / "private" / "oauth.json"
    path.parent.mkdir()
    path.write_text('{"access_token":"ACCESS-SENTINEL"}')
    os.chmod(path, 0o600)
    auth = manager(tmp_path, lambda request: httpx.Response(500))
    status = run(auth.connection_status())
    assert not status["connected"]
    assert "Reconnect" in status["error"] or "reconnect" in status["error"]
    assert "SENTINEL" not in json.dumps(status)


def test_billing_endpoint_is_outside_allowlist(tmp_path):
    def handler(request):
        pytest.fail("Untrusted endpoint must not reach the transport")

    async def check():
        auth = manager(tmp_path, handler)
        async with auth.client_factory() as client:
            with pytest.raises(oauth.OAuthError, match="Untrusted"):
                await auth._request(
                    client, "GET", "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
                )
        assert not hasattr(auth, "billing")
        await auth.close()

    run(check())
