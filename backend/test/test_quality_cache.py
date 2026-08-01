"""Tests for the quality hold/resume cache."""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from ocr import quality_cache as qc  # noqa: E402


def _put(payload=b"x" * 100, **kw):
    kw.setdefault("filename", "invoice.png")
    return qc.put(
        file_bytes=payload, all_results=[["line"]], text="INVOICE",
        average_confidence=0.94, recognition_time=6.1,
        report={"score": 60.0, "tier": "low"}, **kw
    )


@pytest.fixture(autouse=True)
def reset():
    qc.clear()
    qc.configure(ttl_seconds=1800, max_entries=20, max_bytes=256 * 1024 * 1024)
    yield
    qc.clear()


def test_put_returns_an_unguessable_token():
    token = _put()
    assert token.startswith("qa_")
    assert len(token) > 12
    assert token != _put()


def test_peek_does_not_consume():
    token = _put()
    assert qc.peek(token) is not None
    assert qc.peek(token) is not None
    assert qc.stats()["entries"] == 1


def test_pop_is_single_use():
    token = _put()
    entry = qc.pop(token)
    assert entry is not None
    assert entry.text == "INVOICE"
    assert entry.report["tier"] == "low"
    assert qc.pop(token) is None
    assert qc.peek(token) is None


def test_round_trip_preserves_the_expensive_artefact():
    token = _put(po_number="4387858", job_id=7, source="pipeline")
    entry = qc.pop(token)
    assert entry.all_results == [["line"]]
    assert entry.average_confidence == 0.94
    assert entry.recognition_time == 6.1
    assert entry.po_number == "4387858"
    assert entry.job_id == 7
    assert entry.source == "pipeline"


def test_discard_removes_the_entry():
    token = _put()
    assert qc.discard(token) is True
    assert qc.discard(token) is False
    assert qc.peek(token) is None


def test_unknown_and_empty_tokens_are_safe():
    for token in ("qa_nope", "", None):
        assert qc.peek(token) is None
        assert qc.pop(token) is None
        assert qc.discard(token) is False


def test_entries_expire_after_the_ttl():
    qc.configure(ttl_seconds=0.05)
    token = _put()
    assert qc.peek(token) is not None
    time.sleep(0.12)
    assert qc.peek(token) is None
    assert qc.pop(token) is None
    assert qc.stats()["entries"] == 0


def test_sweep_reports_what_it_dropped():
    qc.configure(ttl_seconds=0.05)
    _put()
    _put()
    time.sleep(0.12)
    assert qc.sweep() == 2
    assert qc.stats()["entries"] == 0


def test_max_entries_evicts_oldest_first():
    qc.configure(max_entries=3)
    tokens = [_put() for _ in range(5)]
    assert qc.stats()["entries"] == 3
    assert qc.peek(tokens[0]) is None
    assert qc.peek(tokens[1]) is None
    for token in tokens[2:]:
        assert qc.peek(token) is not None


def test_byte_cap_evicts_until_under_the_limit():
    qc.configure(max_entries=100, max_bytes=1000)
    first = _put(payload=b"a" * 400)
    second = _put(payload=b"b" * 400)
    third = _put(payload=b"c" * 400)
    assert qc.stats()["bytes"] <= 1000
    assert qc.peek(first) is None
    assert qc.peek(third) is not None
    assert qc.peek(second) is not None or qc.stats()["entries"] == 1


def test_oversize_entry_is_refused_not_cached():
    """Refusing to hold must never fail the upload - the caller falls through
    to a caution flag instead."""
    qc.configure(max_bytes=500)
    assert _put(payload=b"z" * 5000) is None
    assert qc.stats()["entries"] == 0


def test_oversize_refusal_does_not_evict_existing_entries():
    qc.configure(max_entries=10, max_bytes=500)
    keep = _put(payload=b"a" * 100)
    assert _put(payload=b"z" * 5000) is None
    assert qc.peek(keep) is not None


def test_stats_shape():
    _put()
    s = qc.stats()
    assert s["entries"] == 1
    assert s["bytes"] == 100
    assert s["oldest_age_s"] >= 0
    assert s["ttl_seconds"] > 0


def test_concurrent_access_is_safe():
    qc.configure(max_entries=50, max_bytes=10 * 1024 * 1024)
    errors = []

    def worker(n):
        try:
            for i in range(200):
                token = _put(payload=b"q" * 50)
                if i % 3 == 0:
                    qc.peek(token)
                elif i % 3 == 1:
                    qc.pop(token)
                else:
                    qc.discard(token)
        except Exception as exc:                     # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert qc.stats()["entries"] <= 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
