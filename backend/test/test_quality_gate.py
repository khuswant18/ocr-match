"""Engine-level tests for the quality gate: pass / caution / hold / resume.

The engine imports PaddleOCR and LayoutLMv3 at module scope, so these tests
stub the two expensive stages (_ocr_stage, _parse_stage) and the assessment
itself. What is under test is the GATE LOGIC between them, not OCR.

If the heavy dependencies are unavailable the module skips rather than fails.
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# engine.py instantiates PaddleOCR at module scope. Loading the real detector
# costs ~30s of model loading, needs the model files, and on CPUs without the
# instruction set the wheel was built for it aborts the interpreter outright.
# None of that is under test here -- the gate logic between the OCR stage and
# the parse stage is -- so stub the module before importing the engine.
if "paddleocr" not in sys.modules:
    _stub = types.ModuleType("paddleocr")

    class _StubPaddleOCR:                       # pragma: no cover
        def __init__(self, *args, **kwargs):
            pass

        def ocr(self, *args, **kwargs):
            raise AssertionError(
                "the real OCR must never run in the gate tests"
            )

    _stub.PaddleOCR = _StubPaddleOCR
    sys.modules["paddleocr"] = _stub

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

engine = pytest.importorskip(
    "app.ocr.engine",
    reason="engine requires torch/transformers/flask to import",
)

from app.ocr import quality_cache  # noqa: E402
from app.ocr.quality import QualityReport  # noqa: E402


SENTINEL = (None, {"invoice_number": "INV-1"}, "raw text", {})


def _report(score, tier):
    return QualityReport(
        score=score, tier=tier, metrics={}, issues=[],
        pages=[{"index": 0, "score": score, "metrics": {}}],
        thresholds={"high": 85.0, "low": 70.0}, elapsed_ms=12.3,
    )


# One page of PaddleOCR output in its real nested shape:
# [ page ][ line ] -> [bbox_quad, (text, confidence)]
_PAGE = [
    [[[0, 0], [100, 0], [100, 20], [0, 20]], ("INVOICE", 0.97)],
    [[[0, 30], [140, 30], [140, 50], [0, 50]], ("TOTAL 1,200.00", 0.93)],
]


def _stage():
    return engine._OcrStage(
        images=["img"], all_results=[_PAGE], text="INVOICE",
        average_confidence=0.94, recognition_time=6.1,
        raw_probes=["probe"], orig_shapes=[(1651, 1275)],
    )


@pytest.fixture
def gate(monkeypatch):
    """Stub the expensive stages; record how _parse_stage was called."""
    calls = {"parse": [], "assess": 0}

    monkeypatch.setattr(engine, "_ocr_stage", lambda *a, **k: _stage())

    def fake_parse(stage, filename, **kw):
        calls["parse"].append(kw)
        return (None, {"invoice_number": "INV-1"}, "raw text",
                {"quality": kw.get("quality"),
                 "quality_flag": kw.get("quality_flag")})

    monkeypatch.setattr(engine, "_parse_stage", fake_parse)
    monkeypatch.setattr(engine, "QUALITY_GATE_ENABLED", True)
    monkeypatch.setattr(engine, "QUALITY_LOG_ONLY", False)
    quality_cache.clear()
    quality_cache.configure(ttl_seconds=1800, max_entries=20,
                            max_bytes=256 * 1024 * 1024)
    yield calls
    quality_cache.clear()


def _set_score(monkeypatch, gate, score, tier):
    def fake_assess(*a, **k):
        gate["assess"] += 1
        return _report(score, tier)
    monkeypatch.setattr(engine, "assess_quality", fake_assess)


# --------------------------------------------------------------------------
# The three tiers
# --------------------------------------------------------------------------

def test_high_score_passes_clean(gate, monkeypatch):
    _set_score(monkeypatch, gate, 92.0, "high")
    _, _, _, meta = engine.extract_and_parse(b"bytes", "a.png")
    assert meta["quality_flag"] == "ok"
    assert "warning" not in meta
    assert quality_cache.stats()["entries"] == 0


def test_medium_score_proceeds_with_caution(gate, monkeypatch):
    _set_score(monkeypatch, gate, 77.2, "medium")
    _, _, _, meta = engine.extract_and_parse(b"bytes", "a.png")
    assert meta["quality_flag"] == "caution"
    assert quality_cache.stats()["entries"] == 0


def test_low_score_holds(gate, monkeypatch):
    _set_score(monkeypatch, gate, 63.4, "low")
    with pytest.raises(engine.QualityHold) as excinfo:
        engine.extract_and_parse(b"bytes", "a.png")

    exc = excinfo.value
    assert exc.assessment_id.startswith("qa_")
    assert exc.report["score"] == 63.4
    assert exc.warning["title"]
    assert "blurry" in exc.warning["message"].lower()
    assert quality_cache.peek(exc.assessment_id) is not None


def test_hold_skips_the_expensive_parse(gate, monkeypatch):
    """The whole point of gating before LayoutLMv3: a rejected invoice must
    never pay for inference."""
    _set_score(monkeypatch, gate, 60.0, "low")
    with pytest.raises(engine.QualityHold):
        engine.extract_and_parse(b"bytes", "a.png")
    assert gate["parse"] == []


def test_pass_and_caution_do_reach_the_parse(gate, monkeypatch):
    _set_score(monkeypatch, gate, 90.0, "high")
    engine.extract_and_parse(b"bytes", "a.png")
    assert len(gate["parse"]) == 1


# --------------------------------------------------------------------------
# Resume
# --------------------------------------------------------------------------

def test_resume_returns_the_result_and_flags_it(gate, monkeypatch):
    _set_score(monkeypatch, gate, 60.0, "low")
    monkeypatch.setattr(engine, "load_images_from_bytes", lambda *a, **k: ["img"])
    with pytest.raises(engine.QualityHold) as excinfo:
        engine.extract_and_parse(b"bytes", "a.png")
    token = excinfo.value.assessment_id

    _, parsed, _, meta = engine.resume_extraction(token)
    assert parsed["invoice_number"] == "INV-1"
    assert meta["quality_flag"] == "proceeded_low_quality"
    assert len(gate["parse"]) == 1


def test_resume_does_not_re_run_ocr(gate, monkeypatch):
    _set_score(monkeypatch, gate, 60.0, "low")
    monkeypatch.setattr(engine, "load_images_from_bytes", lambda *a, **k: ["img"])

    def boom(*a, **k):                              # pragma: no cover
        raise AssertionError("resume must not re-run OCR")

    with pytest.raises(engine.QualityHold) as excinfo:
        engine.extract_and_parse(b"bytes", "a.png")
    token = excinfo.value.assessment_id

    monkeypatch.setattr(engine, "_ocr_stage", boom)
    engine.resume_extraction(token)


def test_resume_token_is_single_use(gate, monkeypatch):
    _set_score(monkeypatch, gate, 60.0, "low")
    monkeypatch.setattr(engine, "load_images_from_bytes", lambda *a, **k: ["img"])
    with pytest.raises(engine.QualityHold) as excinfo:
        engine.extract_and_parse(b"bytes", "a.png")
    token = excinfo.value.assessment_id

    engine.resume_extraction(token)
    with pytest.raises(engine.ExtractionError) as second:
        engine.resume_extraction(token)
    assert second.value.status_code == 410


def test_resume_with_unknown_token_is_410(gate):
    with pytest.raises(engine.ExtractionError) as excinfo:
        engine.resume_extraction("qa_does_not_exist")
    assert excinfo.value.status_code == 410
    assert excinfo.value.payload.get("code") == "ASSESSMENT_EXPIRED"


def test_discard_hold_drops_the_entry(gate, monkeypatch):
    _set_score(monkeypatch, gate, 60.0, "low")
    with pytest.raises(engine.QualityHold) as excinfo:
        engine.extract_and_parse(b"bytes", "a.png")
    token = excinfo.value.assessment_id

    assert engine.discard_hold(token) is True
    assert quality_cache.peek(token) is None
    assert engine.discard_hold(token) is False


# --------------------------------------------------------------------------
# Bypass paths
# --------------------------------------------------------------------------

def test_proceed_decision_skips_assessment_entirely(gate, monkeypatch):
    _set_score(monkeypatch, gate, 10.0, "low")
    _, _, _, meta = engine.extract_and_parse(b"bytes", "a.png",
                                             quality_decision="proceed")
    assert gate["assess"] == 0
    assert meta["quality_flag"] == "proceeded_low_quality"


def test_gate_disabled_behaves_exactly_as_before(gate, monkeypatch):
    _set_score(monkeypatch, gate, 10.0, "low")
    monkeypatch.setattr(engine, "QUALITY_GATE_ENABLED", False)
    _, _, _, meta = engine.extract_and_parse(b"bytes", "a.png")
    assert gate["assess"] == 0
    assert meta["quality_flag"] == "ok"
    assert meta["quality"] is None


def test_log_only_mode_scores_but_never_holds(gate, monkeypatch):
    _set_score(monkeypatch, gate, 30.0, "low")
    monkeypatch.setattr(engine, "QUALITY_LOG_ONLY", True)
    _, _, _, meta = engine.extract_and_parse(b"bytes", "a.png")
    assert gate["assess"] == 1
    assert meta["quality_flag"] == "ok"
    assert meta["quality"]["score"] == 30.0
    assert quality_cache.stats()["entries"] == 0


def test_oversize_document_falls_through_to_caution(gate, monkeypatch):
    """Failing to cache must never turn into a failed upload."""
    _set_score(monkeypatch, gate, 60.0, "low")
    quality_cache.configure(max_bytes=10)
    _, _, _, meta = engine.extract_and_parse(b"x" * 5000, "big.png")
    assert meta["quality_flag"] == "caution"
    assert quality_cache.stats()["entries"] == 0


def test_assessment_crash_does_not_fail_extraction(gate, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("cv2 exploded")

    monkeypatch.setattr(engine, "assess_quality", broken)
    _, _, _, meta = engine.extract_and_parse(b"bytes", "a.png")
    assert meta["quality_flag"] == "ok"
    assert len(gate["parse"]) == 1


# --------------------------------------------------------------------------
# The retry-safety contract with the match worker
# --------------------------------------------------------------------------

def test_quality_hold_is_not_an_extraction_error():
    """match_worker._is_transient retries ExtractionError with status_code 502.
    A hold must never be retried -- that would re-run the very OCR pass it
    exists to preserve."""
    hold = engine.QualityHold("qa_t", {}, "held")
    assert not isinstance(hold, engine.ExtractionError)
    assert not hasattr(hold, "status_code")


def test_quality_hold_carries_the_vendor_payload():
    hold = engine.QualityHold("qa_t", {"score": 1}, "held",
                              warning={"title": "t"}, expires_at=123.0)
    assert hold.assessment_id == "qa_t"
    assert hold.report == {"score": 1}
    assert hold.warning["title"] == "t"
    assert hold.expires_at == 123.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
