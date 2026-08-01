"""HTTP-level tests for the quality gate: hold -> decision -> resume.

Exercises the real Flask blueprint with PaddleOCR and the two expensive
engine stages stubbed, so the route contract (status discriminator, payload
shape, status codes) is verified without running OCR.
"""

import io
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# See test_quality_gate.py: engine.py builds a PaddleOCR instance at import.
if "paddleocr" not in sys.modules:
    _stub = types.ModuleType("paddleocr")

    class _StubPaddleOCR:                       # pragma: no cover
        def __init__(self, *args, **kwargs):
            pass

        def ocr(self, *args, **kwargs):
            raise AssertionError("the real OCR must never run in route tests")

    _stub.PaddleOCR = _StubPaddleOCR
    sys.modules["paddleocr"] = _stub

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import werkzeug  # noqa: E402

if not hasattr(werkzeug, "__version__"):
    # Some pinned werkzeug builds drop __version__ while flask.testing still
    # reads it. Pre-existing environment quirk, unrelated to the gate.
    werkzeug.__version__ = "3.0.0"

flask = pytest.importorskip("flask", reason="flask is required for route tests")

engine = pytest.importorskip(
    "app.ocr.engine",
    reason="engine requires torch/transformers/flask to import",
)

from app.ocr import quality_cache                      # noqa: E402
from app.ocr.quality import QualityReport              # noqa: E402
import app.routes.ocr_routes as ocr_routes             # noqa: E402


_PAGE = [[[[0, 0], [100, 0], [100, 20], [0, 20]], ("INVOICE", 0.97)]]


def _report(score, tier):
    return QualityReport(
        score=score, tier=tier, metrics={}, issues=[],
        pages=[{"index": 0, "score": score, "metrics": {}}],
        thresholds={"high": 85.0, "low": 70.0}, elapsed_ms=5.0,
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(engine, "_ocr_stage", lambda *a, **k: engine._OcrStage(
        images=["img"], all_results=[_PAGE], text="INVOICE",
        average_confidence=0.94, recognition_time=6.1,
        raw_probes=["probe"], orig_shapes=[(1651, 1275)],
    ))

    def fake_parse(stage, filename, **kw):
        meta = {
            "recognition_time": 6.1, "parsing_time": 2.0,
            "average_confidence": 94.0,
            "quality": kw.get("quality"),
            "quality_flag": kw.get("quality_flag"),
        }
        if kw.get("quality_flag") != "ok":
            meta["warning"] = "quality warning"
        return None, {"invoice_number": "INV-1"}, "raw text", meta

    monkeypatch.setattr(engine, "_parse_stage", fake_parse)
    monkeypatch.setattr(engine, "load_images_from_bytes", lambda *a, **k: ["img"])
    monkeypatch.setattr(engine, "QUALITY_GATE_ENABLED", True)
    monkeypatch.setattr(engine, "QUALITY_LOG_ONLY", False)

    quality_cache.clear()
    quality_cache.configure(ttl_seconds=1800, max_entries=20,
                            max_bytes=256 * 1024 * 1024)

    app = flask.Flask(__name__)
    app.register_blueprint(ocr_routes.paddleocr_bp)
    with app.test_client() as c:
        yield c
    quality_cache.clear()


def _upload(client, headers=None):
    return client.post(
        "/paddleOCR",
        data={"file": (io.BytesIO(b"png-bytes"), "invoice.png")},
        content_type="multipart/form-data",
        headers=headers or {},
    )


def _set_tier(monkeypatch, score, tier):
    monkeypatch.setattr(engine, "assess_quality", lambda *a, **k: _report(score, tier))


# --------------------------------------------------------------------------
# Tier outcomes
# --------------------------------------------------------------------------

def test_high_quality_returns_ok(client, monkeypatch):
    _set_tier(monkeypatch, 92.0, "high")
    resp = _upload(client)
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["status"] == "ok"
    assert body["parsed_data"]["invoice_number"] == "INV-1"
    assert body["quality"]["score"] == 92.0
    assert "warning" not in body


def test_medium_quality_returns_caution(client, monkeypatch):
    _set_tier(monkeypatch, 77.0, "medium")
    body = _upload(client).get_json()
    assert body["status"] == "caution"
    assert body["warning"]
    assert body["parsed_data"]["invoice_number"] == "INV-1"


def test_low_quality_holds_with_http_200(client, monkeypatch):
    """A hold must stay 2xx: the frontend's axios instance has no interceptors,
    so a non-2xx would be swallowed by a catch block that discards the payload,
    and the batch harness counts any non-200 as a failure."""
    _set_tier(monkeypatch, 63.4, "low")
    resp = _upload(client)
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "quality_hold"
    assert body["assessment_id"].startswith("qa_")
    assert body["expires_at"]
    assert "parsed_data" not in body
    assert "blurry" in body["warning"]["message"].lower()
    assert [a["id"] for a in body["actions"]] == ["retry", "proceed"]


# --------------------------------------------------------------------------
# The decision endpoint
# --------------------------------------------------------------------------

def test_proceed_resumes_and_flags_the_result(client, monkeypatch):
    _set_tier(monkeypatch, 63.4, "low")
    token = _upload(client).get_json()["assessment_id"]

    resp = client.post("/paddleOCR/quality-decision",
                       json={"assessment_id": token, "decision": "proceed"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["status"] == "proceeded_low_quality"
    assert body["parsed_data"]["invoice_number"] == "INV-1"
    assert body["warning"]


def test_proceed_token_is_single_use(client, monkeypatch):
    _set_tier(monkeypatch, 63.4, "low")
    token = _upload(client).get_json()["assessment_id"]

    client.post("/paddleOCR/quality-decision",
                json={"assessment_id": token, "decision": "proceed"})
    resp = client.post("/paddleOCR/quality-decision",
                       json={"assessment_id": token, "decision": "proceed"})
    assert resp.status_code == 410
    assert resp.get_json()["code"] == "ASSESSMENT_EXPIRED"


def test_retry_releases_the_cached_result(client, monkeypatch):
    _set_tier(monkeypatch, 63.4, "low")
    token = _upload(client).get_json()["assessment_id"]

    resp = client.post("/paddleOCR/quality-decision",
                       json={"assessment_id": token, "decision": "retry"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "retry_acknowledged"
    assert quality_cache.peek(token) is None


def test_retry_on_unknown_token_is_410(client, monkeypatch):
    resp = client.post("/paddleOCR/quality-decision",
                       json={"assessment_id": "qa_nope", "decision": "retry"})
    assert resp.status_code == 410


def test_missing_assessment_id_is_400(client):
    resp = client.post("/paddleOCR/quality-decision", json={"decision": "proceed"})
    assert resp.status_code == 400


def test_invalid_decision_is_400(client):
    resp = client.post("/paddleOCR/quality-decision",
                       json={"assessment_id": "qa_x", "decision": "maybe"})
    assert resp.status_code == 400


def test_missing_file_is_400(client, monkeypatch):
    _set_tier(monkeypatch, 92.0, "high")
    resp = client.post("/paddleOCR", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# Bypass
# --------------------------------------------------------------------------

def test_bypass_header_skips_the_hold(client, monkeypatch):
    _set_tier(monkeypatch, 20.0, "low")
    monkeypatch.setattr(ocr_routes, "QUALITY_BYPASS_TOKEN", "s3cret")

    body = _upload(client, headers={"X-Quality-Bypass": "s3cret"}).get_json()
    assert body["status"] == "proceeded_low_quality"
    assert body["parsed_data"]["invoice_number"] == "INV-1"


def test_wrong_bypass_token_still_holds(client, monkeypatch):
    _set_tier(monkeypatch, 20.0, "low")
    monkeypatch.setattr(ocr_routes, "QUALITY_BYPASS_TOKEN", "s3cret")

    body = _upload(client, headers={"X-Quality-Bypass": "wrong"}).get_json()
    assert body["status"] == "quality_hold"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
