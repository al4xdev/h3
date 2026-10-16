"""Firebase Cloud Messaging (FCM) v1 push notification manager for H3.

Delivers background push notifications to registered Android devices when video chunks
reach terminal states (ready_for_review, interrupted, failed).
Uses Google Cloud Application Default Credentials (ADC) or service account credentials
via httpx, without requiring heavy external SDKs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import time
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

DEFAULT_PROJECT_ID = "casa-de-tequila-push"
DEFAULT_CHANNEL_ID = "h3_video_renders"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

logger = logging.getLogger(__name__)


class DeviceRegistration(BaseModel):
    token: str = Field(min_length=10, max_length=4096)
    device_name: str = Field(default="Android Device", max_length=128)
    device_id: str | None = Field(default=None, max_length=128)


class NotificationConfig(BaseModel):
    project_id: str = Field(default=DEFAULT_PROJECT_ID, max_length=128)
    enabled: bool = True
    topic: str | None = Field(default=None, max_length=128)
    channel_id: str = Field(default=DEFAULT_CHANNEL_ID, max_length=128)


class NotificationTestRequest(BaseModel):
    validate_only: bool = True
    title: str = "H3 Studio · Teste"
    body: str = "Notificação de teste do backend H3"


class NotificationManager:
    def __init__(self, data_root: pathlib.Path | str) -> None:
        self.root = pathlib.Path(data_root) / "notifications"
        self.devices_file = self.root / "devices.json"
        self.config_file = self.root / "config.json"
        self._token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}
        self._lock = asyncio.Lock()
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> NotificationConfig:
        if self.config_file.is_file():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                return NotificationConfig.model_validate(data)
            except (OSError, ValueError, TypeError):
                logger.warning("Failed to parse notifications config.json; using defaults")
        return NotificationConfig()

    def save_config(self, config: NotificationConfig) -> None:
        self._ensure_dir()
        temp_file = self.config_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(config.model_dump(), indent=2), encoding="utf-8")
        temp_file.replace(self.config_file)

    def load_devices(self) -> dict[str, dict[str, Any]]:
        if self.devices_file.is_file():
            try:
                data = json.loads(self.devices_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "devices" in data and isinstance(data["devices"], dict):
                    return data["devices"]
            except (OSError, ValueError, TypeError):
                logger.warning("Failed to parse notifications devices.json; resetting")
        return {}

    def save_devices(self, devices: dict[str, dict[str, Any]]) -> None:
        self._ensure_dir()
        temp_file = self.devices_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps({"devices": devices}, indent=2), encoding="utf-8")
        temp_file.replace(self.devices_file)

    def register_device(self, payload: DeviceRegistration) -> dict[str, Any]:
        devices = self.load_devices()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        device_id = payload.device_id or str(uuid4())
        record = {
            "token": payload.token,
            "device_name": payload.device_name,
            "device_id": device_id,
            "registered_at": devices.get(payload.token, {}).get("registered_at", now),
            "updated_at": now,
        }
        devices[payload.token] = record
        self.save_devices(devices)
        return {"status": "registered", "device_id": device_id, "device_name": payload.device_name}

    def unregister_device(self, token: str) -> bool:
        devices = self.load_devices()
        if token in devices:
            del devices[token]
            self.save_devices(devices)
            return True
        return False

    def list_devices(self) -> list[dict[str, Any]]:
        devices = self.load_devices()
        result = []
        for d in devices.values():
            token = d.get("token", "")
            masked = f"{token[:8]}...{token[-6:]}" if len(token) > 16 else "***"
            result.append({
                "device_id": d.get("device_id"),
                "device_name": d.get("device_name"),
                "masked_token": masked,
                "registered_at": d.get("registered_at"),
                "updated_at": d.get("updated_at"),
            })
        return result

    async def get_oauth_token(self) -> str | None:
        """Acquire an active OAuth2 Bearer token with caching."""
        async with self._lock:
            now = time.time()
            if self._token_cache["access_token"] and now < self._token_cache["expires_at"] - 60:
                return self._token_cache["access_token"]

            # Strategy 1: Check Application Default Credentials in ~/.config/gcloud
            adc_path = pathlib.Path.home() / ".config/gcloud/application_default_credentials.json"
            if adc_path.is_file():
                try:
                    data = json.loads(adc_path.read_text(encoding="utf-8"))
                    if "refresh_token" in data and "client_id" in data and "client_secret" in data:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            resp = await client.post(
                                OAUTH_TOKEN_URL,
                                data={
                                    "client_id": data["client_id"],
                                    "client_secret": data["client_secret"],
                                    "refresh_token": data["refresh_token"],
                                    "grant_type": "refresh_token",
                                },
                            )
                            if resp.status_code == 200:
                                payload = resp.json()
                                token = payload.get("access_token")
                                expires_in = payload.get("expires_in", 3600)
                                if token:
                                    self._token_cache = {
                                        "access_token": token,
                                        "expires_at": now + expires_in,
                                    }
                                    return token
                except (OSError, httpx.HTTPError, ValueError) as exc:
                    logger.debug("ADC refresh via OAuth failed: %s", exc)

            # Strategy 2: Call gcloud CLI fallback
            try:
                proc = await asyncio.create_subprocess_exec(
                    "gcloud", "auth", "application-default", "print-access-token",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                if proc.returncode == 0:
                    token = stdout.decode().strip()
                    if token:
                        self._token_cache = {"access_token": token, "expires_at": now + 1800}
                        return token
            except (TimeoutError, OSError) as exc:
                logger.debug("gcloud access token command failed: %s", exc)

            return None

    async def send_fcm_message(
        self,
        *,
        token: str | None = None,
        topic: str | None = None,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        """Send a single FCM message via HTTP v1 API."""
        config = self.load_config()
        if not config.enabled:
            return {"status": "disabled"}

        auth_token = await self.get_oauth_token()
        if not auth_token:
            logger.warning("Cannot send FCM message: Google OAuth token unavailable")
            return {"status": "auth_unavailable"}

        target_field = {"token": token} if token else ({"topic": topic} if topic else None)
        if not target_field:
            return {"status": "no_target"}

        message_payload: dict[str, Any] = {
            **target_field,
            "notification": {"title": title, "body": body},
            "data": data or {},
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": config.channel_id,
                    "notification_priority": "PRIORITY_HIGH",
                    "default_sound": True,
                },
            },
        }

        request_body: dict[str, Any] = {"message": message_payload}
        if validate_only:
            request_body["validate_only"] = True

        url = FCM_SEND_URL.format(project_id=config.project_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json=request_body,
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code == 200:
                result = resp.json()
                return {"status": "sent", "name": result.get("name")}

            # Token expired or unregistered on Android
            if resp.status_code == 404 and token:
                logger.info("FCM token expired or unregistered; removing device: %s...", token[:8])
                self.unregister_device(token)
                return {"status": "unregistered"}

            logger.warning("FCM send failed (HTTP %s): %s", resp.status_code, resp.text)
            return {"status": "error", "code": resp.status_code, "detail": resp.text}

    async def broadcast_event(
        self,
        *,
        title: str,
        body: str,
        data: dict[str, str],
        validate_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Broadcast a notification to all registered devices and topic."""
        config = self.load_config()
        if not config.enabled:
            return []

        devices = self.load_devices()
        tokens = list(devices.keys())
        tasks = [
            self.send_fcm_message(
                token=token,
                title=title,
                body=body,
                data=data,
                validate_only=validate_only,
            )
            for token in tokens
        ]
        if config.topic:
            tasks.append(
                self.send_fcm_message(
                    topic=config.topic,
                    title=title,
                    body=body,
                    data=data,
                    validate_only=validate_only,
                )
            )

        if not tasks:
            return []
        return await asyncio.gather(*tasks, return_exceptions=False)

    def notify_run_terminal_sync(self, run: Any, *, duration_seconds: float | None = None) -> None:
        """Schedule a background task to notify device clients of run completion/failure."""
        config = self.load_config()
        if not config.enabled:
            return

        state = getattr(run, "state", None) or "unknown"
        run_id = getattr(run, "id", None) or "unknown"

        if state == "ready_for_review":
            dur_str = f" em {duration_seconds:.1f}s" if duration_seconds is not None else ""
            title = "H3 Studio · Vídeo Pronto"
            body = f"Chunk {run_id[:8]} renderizado com sucesso{dur_str}. Toque para revisar."
        elif state == "failed":
            title = "H3 Studio · Erro na Renderização"
            err = getattr(run, "error", None) or "Falha no processo"
            body = f"Chunk {run_id[:8]} falhou: {err}"
        elif state == "interrupted":
            title = "H3 Studio · Geração Interrompida"
            body = f"Chunk {run_id[:8]} foi interrompido."
        else:
            return

        data = {
            "event": "run_terminal",
            "run_id": str(run_id),
            "state": str(state),
            "video_url": f"/runs/{run_id}/chunk.mp4" if state == "ready_for_review" else "",
        }

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.broadcast_event(title=title, body=body, data=data),
                name=f"fcm-notify-{run_id}",
            )
        except RuntimeError:
            pass


router = APIRouter(prefix="/notifications", tags=["notifications"])


def get_manager(request: Request) -> NotificationManager:
    notifications = getattr(request.app.state, "notifications", None)
    if notifications is not None:
        return notifications
    service = getattr(request.app.state, "service", None)
    if service is not None and getattr(service, "notifications", None) is not None:
        return service.notifications
    data_root = getattr(service.store, "root", None) if service and hasattr(service, "store") else pathlib.Path(".data")
    return NotificationManager(data_root)


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    manager = get_manager(request)
    return manager.load_config().model_dump()


@router.put("/config")
async def update_config(payload: NotificationConfig, request: Request) -> dict[str, Any]:
    manager = get_manager(request)
    manager.save_config(payload)
    return manager.load_config().model_dump()


@router.get("/devices")
async def get_devices(request: Request) -> list[dict[str, Any]]:
    manager = get_manager(request)
    return manager.list_devices()


@router.post("/register")
async def register_device(payload: DeviceRegistration, request: Request) -> dict[str, Any]:
    manager = get_manager(request)
    return manager.register_device(payload)


@router.delete("/devices/{token}")
async def unregister_device(token: str, request: Request) -> dict[str, Any]:
    manager = get_manager(request)
    removed = manager.unregister_device(token)
    if not removed:
        raise HTTPException(status_code=404, detail="Device token not found")
    return {"status": "unregistered"}


@router.post("/test")
async def test_notification(payload: NotificationTestRequest, request: Request) -> dict[str, Any]:
    manager = get_manager(request)
    devices = manager.load_devices()
    first_token = next(iter(devices.keys()), None)
    target_topic = manager.load_config().topic or "h3_updates"

    result = await manager.send_fcm_message(
        token=first_token,
        topic=None if first_token else target_topic,
        title=payload.title,
        body=payload.body,
        data={"event": "test", "timestamp": str(int(time.time()))},
        validate_only=payload.validate_only,
    )
    return {
        "result": result,
        "target": "device" if first_token else f"topic:{target_topic}",
        "validate_only": payload.validate_only,
    }
