"""Tests for the invoice quality assessment layer.

Strategy: take one clean invoice from all_invoices/ as the positive sample and
generate negatives by degrading it (blur, downscale, rotate, crop, darken,
wash out, add noise). That yields labelled negatives with no hand-labelling.

Assertions are deliberately RELATIVE (degraded scores worse than clean) wherever
possible, so the suite survives threshold retuning. The few absolute assertions
are the ones that encode the actual product requirement.
"""

import json
import math
import os
import subprocess
import sys

import numpy as np
import pytest

# Allow importing from the backend app without installing it
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import cv2  # noqa: E402

from ocr.quality import (  # noqa: E402
    DEFAULT_WEIGHTS,
    CRITICAL_METRICS,
    aggregate,
    assess_page,
    assess_quality,
    score_to_tier,
)

_CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "all_invoices")
_SAMPLE = os.path.join(_CORPUS, "3857523.png")


def _load_clean():
    img = cv2.imread(_SAMPLE)
    if img is None:
        pytest.skip(f"sample invoice not available at {_SAMPLE}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


@pytest.fixture(scope="module")
def clean():
    return _load_clean()


# --------------------------------------------------------------------------
# Degradation helpers
# --------------------------------------------------------------------------

def blur(img, k):
    return cv2.GaussianBlur(img, (k, k), 0)


def downscale(img, f):
    return cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)


def rotate(img, deg):
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


def crop_right(img, frac):
    return img[:, : int(img.shape[1] * (1 - frac))]


def darken(img, gamma):
    return np.clip(img.astype(np.float32) * gamma, 0, 255).astype(np.uint8)


def washout(img, alpha):
    return cv2.convertScaleAbs(img, alpha=alpha, beta=255 * (1 - alpha))


def noisify(img, sigma, seed=0):
    rng = np.random.default_rng(seed)
    out = img.astype(np.float32) + rng.normal(0, sigma, img.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def _metric(img, name, blocks=None):
    return assess_page(img, blocks)["metrics"][name].score


def _codes(img, blocks=None):
    return {i.code for i in assess_page(img, blocks)["issues"]}


# --------------------------------------------------------------------------
# The headline guarantee
# --------------------------------------------------------------------------

def test_clean_invoice_passes(clean):
    """A known-good invoice must land in the 'high' tier.

    This is the guard against a gate that rejects good documents. If it fails,
    the normalisation anchors are wrong -- not this test.
    """
    report = assess_quality([clean])
    assert report.tier == "high", (
        f"clean invoice scored {report.score} ({report.tier}), "
        f"issues={report.issue_codes}"
    )
    assert report.score >= 85.0


def test_clean_invoice_raises_no_issues(clean):
    assert _codes(clean) == set()


def test_degraded_always_scores_below_clean(clean):
    base = assess_quality([clean]).score
    for label, img in [
        ("blurred", blur(clean, 17)),
        ("downscaled", downscale(clean, 0.35)),
        ("rotated", rotate(clean, 6)),
        ("dark", darken(clean, 0.35)),
        ("washed out", washout(clean, 0.3)),
    ]:
        got = assess_quality([img]).score
        assert got < base, f"{label} scored {got}, clean scored {base}"


# --------------------------------------------------------------------------
# Per-metric monotonicity
# --------------------------------------------------------------------------

def test_blur_measurement_is_monotonic(clean):
    """The underlying measurement must fall with every increase in blur.

    Asserted on the raw Laplacian variance rather than the score, because the
    score deliberately saturates at 0 once a page is unambiguously blurred
    (k>=9 here) and saturated values are equal, not ordered.
    """
    raws = [
        assess_page(blur(clean, k) if k > 1 else clean)["metrics"]["blur"]
        .raw["laplacian_var"]
        for k in (1, 3, 5, 9, 17)
    ]
    assert raws == sorted(raws, reverse=True), raws


def test_blur_score_is_monotonic_before_saturation(clean):
    assert _metric(clean, "blur") > _metric(blur(clean, 3), "blur") \
        > _metric(blur(clean, 5), "blur")


def test_heavy_blur_is_flagged(clean):
    assert "BLURRY" in _codes(blur(clean, 9))
    assert "BLURRY" in _codes(blur(clean, 17))


def test_blur_not_flagged_on_clean(clean):
    assert "BLURRY" not in _codes(clean)


def test_resolution_drops_with_downscale(clean):
    assert _metric(downscale(clean, 0.5), "resolution") < _metric(clean, "resolution")
    assert "LOW_RESOLUTION" in _codes(downscale(clean, 0.3))


def test_skew_detects_tilt(clean):
    assert _metric(rotate(clean, 0.3), "skew") > _metric(rotate(clean, 6), "skew")
    assert "SKEWED" in _codes(rotate(clean, 6))


def test_skew_tolerates_upright(clean):
    assert "SKEWED" not in _codes(clean)
    assert _metric(clean, "skew") >= 90


def test_rotation_is_not_claimed_without_blocks(clean):
    """A whole-page ink minAreaRect reports ~90 degrees on upright invoices and
    produced a 40% false-positive rate on the known-good corpus, so the
    block-free path must never assert ROTATED."""
    assert "ROTATED" not in _codes(rotate(clean, 90))


def test_rotation_detected_from_blocks(clean):
    h, w = clean.shape[:2]
    # Sideways text: every quadrilateral runs top-to-bottom, not left-to-right.
    blocks = [
        {"text": "x", "confidence": 0.95,
         "box": [[500, 100 + i * 40], [500, 260 + i * 40],
                 [530, 260 + i * 40], [530, 100 + i * 40]]}
        for i in range(20)
    ]
    assert "ROTATED" in _codes(clean, blocks)


def test_contrast_drops_when_washed_out(clean):
    assert _metric(washout(clean, 0.3), "contrast") < _metric(clean, "contrast")
    assert "LOW_CONTRAST" in _codes(washout(clean, 0.22))


def test_lighting_flags_underexposure(clean):
    assert "POOR_LIGHTING" in _codes(darken(clean, 0.3))


def test_lighting_flags_uneven_illumination(clean):
    h, w = clean.shape[:2]
    gradient = np.linspace(0.25, 1.0, w, dtype=np.float32)[None, :, None]
    shaded = np.clip(clean.astype(np.float32) * gradient, 0, 255).astype(np.uint8)
    assert _metric(shaded, "lighting") < _metric(clean, "lighting")


def test_noise_drops_with_added_grain(clean):
    assert _metric(noisify(clean, 22), "noise") < _metric(clean, "noise")
    # Additive grain on near-white paper clips at 255, so the recoverable
    # sigma is roughly half what was injected: sigma_in=60 measures ~9.9.
    # The NOISY cut-point sits at an estimated sigma of ~9.
    assert "NOISY" in _codes(noisify(clean, 60))


def test_noise_estimate_is_monotonic(clean):
    est = [
        assess_page(noisify(clean, s) if s else clean)["metrics"]["noise"]
        .raw["sigma_paper"]
        for s in (0, 10, 22, 45, 60)
    ]
    assert est == sorted(est), est


def test_noise_clean_on_clean_scan(clean):
    """Regression: speckle_ratio was computed with uint8 subtraction, and
    OpenCV's even-kernel anchor offset made it underflow to values in the
    tens, pinning every document's noise score at exactly 50."""
    page = assess_page(clean)
    speckle = page["metrics"]["noise"].raw["speckle_ratio"]
    assert 0.0 <= speckle <= 1.0, f"speckle_ratio out of range: {speckle}"
    assert "NOISY" not in _codes(clean)


def test_cropping_detects_a_transected_edge(clean):
    """A single guillotined edge is detected and deducts score."""
    page = assess_page(crop_right(clean, 0.14))
    assert "right" in page["metrics"]["cropping"].raw["cropped_edges"]
    assert page["metrics"]["cropping"].score < 100


def test_cropped_issue_needs_two_edges(clean):
    """CROPPED requires 2+ transected edges. A single edge is legitimate on
    28% of the known-good corpus (letterheads, margin rules, scanner borders),
    so raising the issue on one would make the gate unusable."""
    h, w = clean.shape[:2]
    assert "CROPPED" not in _codes(crop_right(clean, 0.14))
    both = clean[:, int(w * 0.10): int(w * 0.86)]
    assert "CROPPED" in _codes(both)


def test_cropping_is_not_a_critical_metric():
    """Its detector is too noisy to be allowed to cap the document score."""
    assert "cropping" not in CRITICAL_METRICS


def test_cropping_no_false_positive_on_header_bar(clean):
    """Many invoices have a full-bleed coloured header bar or a printed frame
    rule. That is flat fill, not cut-off content, and must not trigger CROPPED."""
    img = clean.copy()
    img[:40, :] = (30, 60, 140)
    assert "CROPPED" not in _codes(img)


# --------------------------------------------------------------------------
# Occlusion and visible text
# --------------------------------------------------------------------------

def redact(img, boxes):
    """Paint solid black rectangles, given as (y0, y1, x0, x1) page fractions."""
    out = img.copy()
    h, w = img.shape[:2]
    for y0, y1, x0, x1 in boxes:
        out[int(h * y0):int(h * y1), int(w * x0):int(w * x1)] = 0
    return out


def test_clean_invoice_reads_as_unoccluded(clean):
    page = assess_page(clean)
    assert page["metrics"]["occlusion"].score == 100
    assert page["metrics"]["occlusion"].raw["occluded_ratio"] < 0.01
    assert "OCCLUDED" not in _codes(clean)


def test_printed_text_is_not_mistaken_for_occlusion(clean):
    """Marker pen and printed ink are equally dark; only shape separates them.
    Across the 100-invoice corpus this metric scores exactly 100 on every
    file, barcodes and solid logos included."""
    assert assess_page(clean)["metrics"]["occlusion"].raw["occluded_ratio"] < 0.01


def test_occlusion_is_monotonic(clean):
    one = _metric(redact(clean, [(.30, .36, .10, .70)]), "occlusion")
    three = _metric(redact(clean, [(.30, .36, .10, .70), (.45, .51, .10, .70),
                                   (.60, .66, .10, .70)]), "occlusion")
    half = _metric(redact(clean, [(.45, 1.0, 0.0, 1.0)]), "occlusion")
    assert 100 >= one > three > half
    assert half == 0


def test_heavy_redaction_is_flagged(clean):
    codes = _codes(redact(clean, [(.30, .36, .10, .70), (.45, .51, .10, .70),
                                  (.60, .66, .10, .70)]))
    assert "OCCLUDED" in codes
    assert "LOW_VISIBLE_TEXT" in codes


def test_redaction_forces_a_hold(clean):
    """Occlusion and visible_text_ratio are both critical metrics, so a
    redacted invoice must land in the low tier rather than being averaged
    back up by nine healthy dimensions."""
    report = assess_quality([redact(clean, [(.45, 1.0, 0.0, 1.0)])])
    assert report.tier == "low"
    assert "OCCLUDED" in report.issue_codes


def test_visible_text_ratio_falls_as_coverage_grows(clean):
    base = _metric(clean, "visible_text_ratio")
    part = _metric(redact(clean, [(.30, .45, .05, .95)]), "visible_text_ratio")
    most = _metric(redact(clean, [(.30, .65, .05, .95)]), "visible_text_ratio")
    assert base > part > most


def test_ocr_confidence_is_capped_by_occlusion(clean):
    """The blind spot this closes: OCR returns nothing at all for text hidden
    under a redaction bar -- not a low-confidence reading -- so the mean over
    surviving detections would otherwise vouch for a document whose covered
    quarter was never read.

    Both pages are given the SAME set of high-confidence blocks, so mean_conf
    is identical and only the occlusion cap can move the score.
    """
    confident = _grid_blocks(conf=0.98)
    open_page = assess_page(clean, confident)
    covered = assess_page(redact(clean, [(.30, .55, .05, .95)]), confident)

    assert open_page["metrics"]["ocr_confidence"].score >= 90
    assert covered["metrics"]["ocr_confidence"].score < 30
    assert covered["metrics"]["ocr_confidence"].raw["mean_conf"] == pytest.approx(
        open_page["metrics"]["ocr_confidence"].raw["mean_conf"])


def test_almost_entirely_covered_page_is_degenerate(clean):
    """Past ~60% ink coverage the page short-circuits to zero rather than
    being scored metric by metric."""
    report = assess_quality([redact(clean, [(.35, 1.0, 0.0, 1.0)])])
    assert report.score == 0.0
    assert report.tier == "low"


def test_occlusion_and_visible_text_are_critical():
    assert "occlusion" in CRITICAL_METRICS
    assert "visible_text_ratio" in CRITICAL_METRICS


def test_blank_page_is_degenerate(clean):
    blank = np.full_like(clean, 255)
    report = assess_quality([blank])
    assert report.tier == "low"
    assert "INCOMPLETE_DOCUMENT" in report.issue_codes
    assert report.score == 0.0


# --------------------------------------------------------------------------
# Block-derived metrics (no OCR needed -- blocks are synthesised directly)
# --------------------------------------------------------------------------

def _grid_blocks(n_rows=30, n_cols=5, conf=0.97, h=22, page_h=1651, page_w=1275):
    blocks = []
    for r in range(n_rows):
        y = int(page_h * (r + 0.5) / n_rows)
        for c in range(n_cols):
            x = int(page_w * (c + 0.5) / n_cols)
            blocks.append({
                "text": "sample", "confidence": conf,
                "box": [[x, y], [x + 90, y], [x + 90, y + h], [x, y + h]],
            })
    return blocks


def test_dense_confident_blocks_read_well(clean):
    page = assess_page(clean, _grid_blocks())
    assert page["metrics"]["readability"].score >= 85
    assert page["metrics"]["completeness"].score >= 85
    assert page["metrics"]["ocr_confidence"].score >= 90
    codes = {i.code for i in page["issues"]}
    assert "SPARSE_TEXT" not in codes and "LOW_OCR_CONFIDENCE" not in codes


def test_sparse_blocks_flag_incomplete(clean):
    blocks = [
        {"text": "x", "confidence": 0.4,
         "box": [[100, 100 + i * 12], [160, 100 + i * 12],
                 [160, 112 + i * 12], [100, 112 + i * 12]]}
        for i in range(4)
    ]
    codes = _codes(clean, blocks)
    assert "SPARSE_TEXT" in codes
    assert "LOW_OCR_CONFIDENCE" in codes


def test_low_confidence_tail_lowers_readability(clean):
    good = assess_page(clean, _grid_blocks(conf=0.97))
    bad = assess_page(clean, _grid_blocks(conf=0.55))
    assert bad["metrics"]["readability"].score < good["metrics"]["readability"].score


def test_small_text_flagged(clean):
    assert "SMALL_TEXT" in _codes(clean, _grid_blocks(h=8))


def test_block_metrics_marked_estimated_without_blocks(clean):
    page = assess_page(clean)
    assert page["metrics"]["ocr_confidence"].estimated is True
    assert page["metrics"]["readability"].estimated is True
    with_blocks = assess_page(clean, _grid_blocks())
    assert with_blocks["metrics"]["ocr_confidence"].estimated is False


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("metric", CRITICAL_METRICS)
def test_critical_floor_caps_a_single_catastrophic_metric(metric):
    """An unreadable page must not be averaged back up to 'high' by nine
    healthy dimensions."""
    scores = {k: 95.0 for k in DEFAULT_WEIGHTS}
    scores[metric] = 20.0
    assert aggregate(scores) == 45.0


@pytest.mark.parametrize("metric", CRITICAL_METRICS)
def test_healthy_critical_metric_imposes_no_cap(metric):
    scores = {k: 95.0 for k in DEFAULT_WEIGHTS}
    scores[metric] = 75.0
    weighted = sum(DEFAULT_WEIGHTS[k] * scores[k] for k in DEFAULT_WEIGHTS)
    assert aggregate(scores) == pytest.approx(weighted, abs=0.1)


def test_non_critical_metric_cannot_cap_the_score():
    """cropping is weighted but must never single-handedly force a hold."""
    scores = {k: 95.0 for k in DEFAULT_WEIGHTS}
    scores["cropping"] = 20.0
    assert aggregate(scores) > 80.0


def test_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_critical_metric_is_a_known_metric():
    for m in CRITICAL_METRICS:
        assert m in DEFAULT_WEIGHTS


def test_tier_boundaries():
    assert score_to_tier(85.0) == "high"
    assert score_to_tier(84.9) == "medium"
    assert score_to_tier(70.0) == "medium"
    assert score_to_tier(69.9) == "low"


def test_document_score_is_worst_page(clean):
    report = assess_quality([clean, blur(clean, 21)])
    assert report.score == min(p["score"] for p in report.pages)
    assert len(report.pages) == 2


def test_max_pages_is_respected(clean):
    report = assess_quality([clean] * 9, max_pages=3)
    assert len(report.pages) == 3


def test_empty_input_is_low_tier():
    report = assess_quality([])
    assert report.tier == "low"
    assert report.score == 0.0


# --------------------------------------------------------------------------
# Robustness / serialisation
# --------------------------------------------------------------------------

def test_desynced_block_list_does_not_crash(clean):
    """_run_document_ocr drops pages with no detections, so the block list and
    the image list can legitimately differ in length."""
    report = assess_quality([clean, clean, clean], [_grid_blocks()])
    assert len(report.pages) == 3


def test_grayscale_input_accepted(clean):
    gray = cv2.cvtColor(clean, cv2.COLOR_RGB2GRAY)
    assert assess_quality([gray]).score > 0


def test_orig_shape_overrides_probe_for_resolution(clean):
    small = downscale(clean, 0.4)
    without = assess_page(small)["metrics"]["resolution"].score
    with_shape = assess_page(small, orig_shape=(1651, 1275))["metrics"]["resolution"].score
    assert with_shape > without


def test_report_serialises_to_json(clean):
    payload = assess_quality([clean], _grid_blocks() and [_grid_blocks()]).to_dict()
    text = json.dumps(payload)          # raises on numpy scalars
    restored = json.loads(text)
    assert restored["tier"] in ("high", "medium", "low")
    assert set(restored["metrics"]) == set(DEFAULT_WEIGHTS)
    for metric in restored["metrics"].values():
        assert isinstance(metric["score"], (int, float))


def test_no_numpy_scalars_leak_into_to_dict(clean):
    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        else:
            assert not isinstance(node, np.generic), f"numpy scalar leaked: {node!r}"

    walk(assess_quality([clean], [_grid_blocks()]).to_dict())


def test_issues_sorted_critical_first(clean):
    img = blur(crop_right(clean, 0.15), 17)
    issues = assess_page(img)["issues"]
    if len(issues) > 1:
        ranks = ["critical", "major", "minor"]
        idx = [ranks.index(i.severity) for i in issues]
        assert idx == sorted(idx)


def test_vendor_warning_shape(clean):
    warning = assess_quality([blur(clean, 21)]).vendor_warning()
    assert warning["title"] and warning["message"]
    assert "blurry" in warning["message"].lower()
    for issue in warning["issues"]:
        assert issue["code"] and issue["message"] and issue["hint"]


def test_module_is_flask_free():
    """The purity contract: quality.py must be importable with no Flask, no DB
    and no PaddleOCR, so it can be unit-tested and calibrated offline."""
    app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
    code = (
        "import sys; sys.path.insert(0, %r);"
        "import ocr.quality;"
        "bad=[m for m in ('flask','sqlalchemy','paddleocr','torch','transformers')"
        "     if m in sys.modules];"
        "print(','.join(bad))" % app_dir
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"quality.py pulled in: {out.stdout.strip()}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
