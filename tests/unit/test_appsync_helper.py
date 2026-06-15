import json
from unittest.mock import patch, MagicMock
from agents.shared.utils.appsync import publish_machine_state


def test_publish_machine_state_posts_mutation(monkeypatch):
    monkeypatch.setenv("APPSYNC_URL", "https://example.appsync-api.us-east-1.amazonaws.com/graphql")
    monkeypatch.setenv("APPSYNC_API_KEY", "da2-test")
    captured = {}

    class FakeResp:
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    with patch("urllib.request.urlopen", fake_urlopen):
        ok = publish_machine_state(
            machine_id="CNC-AERO-01", plant_id="PLANT-001",
            status="FAULT", health_score=0.12,
            telemetry={"vibration_mms": 9.1, "current_amps": 20.0,
                       "coolant_lmin": 12.0, "acoustic_db": 80.0},
            updated_at="2026-05-31T10:00:00Z",
        )
    assert ok is True
    assert captured["body"]["variables"]["input"]["status"] == "FAULT"
    assert captured["body"]["variables"]["input"]["health_score"] == 0.12
    assert captured["headers"]["X-api-key"] == "da2-test"


def test_publish_machine_state_noop_without_env(monkeypatch):
    monkeypatch.delenv("APPSYNC_URL", raising=False)
    monkeypatch.delenv("APPSYNC_API_KEY", raising=False)
    assert publish_machine_state(
        machine_id="CNC-AERO-01", plant_id="PLANT-001",
        status="RUNNING", health_score=1.0, telemetry={}, updated_at="x"
    ) is False
