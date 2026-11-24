from fastapi.testclient import TestClient

from jarvis.api import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "online"


def test_security_scanner_is_registered_and_status_is_available():
    with TestClient(app) as client:
        skills = client.get("/api/v1/skills").json()["skills"]
        status = client.get("/api/v1/security/status")
    assert any(item["skill_id"] == "security.scan_project" for item in skills)
    assert status.status_code == 200
    assert status.json()["available"] is True


def test_voice_options_endpoint_reports_installed_languages():
    with TestClient(app) as client:
        response = client.get("/api/v1/voice/options")
    assert response.status_code == 200
    payload = response.json()
    assert payload["voices"]
    assert payload["recognition_languages"]
    assert all(item["culture"] for item in payload["recognition_languages"])
    assert isinstance(payload["audio_devices"], list)
    assert payload["device_selection"] == "fixed_preferred_devices"
    assert any(item["kind"] == "input" for item in payload["audio_devices"])
    assert any(item["kind"] == "output" for item in payload["audio_devices"])


def test_voice_language_preference_is_saved_and_reported():
    with TestClient(app) as client:
        options = client.get("/api/v1/voice/options").json()
        supported = options["recognition_languages"][0]["culture"]
        saved = client.put("/api/v1/voice/language", json={"language": supported})
        assert saved.status_code == 200
        assert saved.json()["saved"] is True
        assert client.get("/api/v1/voice/language").json()["language"] == supported
        assert client.get("/api/v1/voice/options").json()["default_language"] == supported


def test_voice_language_rejects_uninstalled_culture():
    with TestClient(app) as client:
        response = client.put("/api/v1/voice/language", json={"language": "zz-ZZ"})
    assert response.status_code == 422


def test_voice_listen_rejects_malformed_language():
    with TestClient(app) as client:
        response = client.post("/api/v1/voice/listen", json={"seconds": 4, "language": "bad!"})
    assert response.status_code == 422


def test_memory_api_create_and_delete():
    with TestClient(app) as client:
        created = client.post("/api/v1/memory", json={"content": "temporary API test"})
        assert created.status_code == 200
        memory_id = created.json()["memory"]["id"]
        assert any(item["id"] == memory_id
                   for item in client.get("/api/v1/memory").json()["memories"])
        deleted = client.delete(f"/api/v1/memory/{memory_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
