"""Unit tests for FCM push notifications module."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from h3_backend.api import create_app
from h3_backend.notifications import (
    DeviceRegistration,
    NotificationConfig,
    NotificationManager,
)


@pytest.fixture
def manager(tmp_path):
    return NotificationManager(tmp_path)


def test_config_defaults_and_persistence(manager):
    cfg = manager.load_config()
    assert isinstance(cfg, NotificationConfig)
    assert cfg.project_id == "casa-de-tequila-push"
    assert cfg.enabled is True
    assert cfg.channel_id == "h3_video_renders"

    cfg.enabled = False
    cfg.topic = "custom_topic"
    manager.save_config(cfg)

    loaded = manager.load_config()
    assert loaded.enabled is False
    assert loaded.topic == "custom_topic"


def test_device_registration_and_masking(manager):
    reg = DeviceRegistration(token="fcm_token_sample_1234567890", device_name="Pixel 8")
    result = manager.register_device(reg)
    assert result["status"] == "registered"
    assert result["device_name"] == "Pixel 8"
    assert "device_id" in result

    devices = manager.list_devices()
    assert len(devices) == 1
    assert devices[0]["device_name"] == "Pixel 8"
    assert devices[0]["masked_token"] == "fcm_toke...567890"

    # Unregister
    removed = manager.unregister_device("fcm_token_sample_1234567890")
    assert removed is True
    assert len(manager.list_devices()) == 0
    assert manager.unregister_device("non_existent") is False


@pytest.mark.asyncio
async def test_oauth_token_caching(manager):
    manager._token_cache = {"access_token": "cached_fake_token", "expires_at": 9999999999.0}
    token = await manager.get_oauth_token()
    assert token == "cached_fake_token"


@pytest.mark.asyncio
async def test_send_fcm_message_success(manager, monkeypatch):
    monkeypatch.setattr(manager, "get_oauth_token", AsyncMock(return_value="mock_token"))

    class MockResponse:
        status_code = 200

        def json(self):
            return {"name": "projects/test/messages/msg_123"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = MockResponse()

        result = await manager.send_fcm_message(
            token="test_device_token",
            title="Vídeo Pronto",
            body="Bloco 1 renderizado",
            data={"run_id": "run-abc", "event": "ready"},
            validate_only=True,
        )

        assert result["status"] == "sent"
        assert result["name"] == "projects/test/messages/msg_123"
        assert mock_post.called
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["validate_only"] is True
        assert call_kwargs["json"]["message"]["token"] == "test_device_token"
        assert call_kwargs["json"]["message"]["notification"]["title"] == "Vídeo Pronto"
        assert call_kwargs["json"]["message"]["data"]["run_id"] == "run-abc"


@pytest.mark.asyncio
async def test_send_fcm_message_unregistered_prunes_device(manager, monkeypatch):
    monkeypatch.setattr(manager, "get_oauth_token", AsyncMock(return_value="mock_token"))
    manager.register_device(DeviceRegistration(token="expired_token_12345", device_name="Old Phone"))

    class Mock404Response:
        status_code = 404
        text = json.dumps({"error": {"status": "NOT_FOUND"}})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Mock404Response()

        result = await manager.send_fcm_message(
            token="expired_token_12345",
            title="Test",
            body="Test",
        )

        assert result["status"] == "unregistered"
        assert len(manager.load_devices()) == 0


@pytest.mark.asyncio
async def test_broadcast_event(manager, monkeypatch):
    monkeypatch.setattr(manager, "send_fcm_message", AsyncMock(return_value={"status": "sent"}))
    manager.register_device(DeviceRegistration(token="token_device_1", device_name="Device 1"))
    manager.register_device(DeviceRegistration(token="token_device_2", device_name="Device 2"))

    results = await manager.broadcast_event(
        title="Title",
        body="Body",
        data={"event": "done"},
    )
    assert len(results) == 2
    assert all(r["status"] == "sent" for r in results)


def test_notification_routes_api(tmp_path):
    app = create_app()
    app.state.notifications = NotificationManager(tmp_path)
    client = TestClient(app)

    # 1. Config endpoint
    resp = client.get("/notifications/config")
    assert resp.status_code == 200
    assert resp.json()["project_id"] == "casa-de-tequila-push"

    resp = client.put("/notifications/config", json={"project_id": "my-project", "enabled": True})
    assert resp.status_code == 200
    assert resp.json()["project_id"] == "my-project"

    # 2. Register device
    resp = client.post("/notifications/register", json={
        "token": "android_fcm_token_abcdef123456",
        "device_name": "Galaxy S24",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "registered"

    # 3. List devices
    resp = client.get("/notifications/devices")
    assert resp.status_code == 200
    devices = resp.json()
    assert len(devices) == 1
    assert devices[0]["device_name"] == "Galaxy S24"

    # 4. Unregister device
    resp = client.delete("/notifications/devices/android_fcm_token_abcdef123456")
    assert resp.status_code == 200
    assert resp.json()["status"] == "unregistered"

    resp = client.delete("/notifications/devices/not_found_token")
    assert resp.status_code == 404


def test_notification_test_endpoint_mocked(tmp_path, monkeypatch):
    app = create_app()
    app.state.notifications = NotificationManager(tmp_path)
    monkeypatch.setattr(app.state.notifications, "get_oauth_token", AsyncMock(return_value="mock_token"))

    class MockResp:
        status_code = 200

        def json(self):
            return {"name": "projects/test/messages/msg_999"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = MockResp()
        client = TestClient(app)
        resp = client.post("/notifications/test", json={"validate_only": True})
        assert resp.status_code == 200
        assert resp.json()["result"]["status"] == "sent"
