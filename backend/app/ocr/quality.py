"""
Invoice Quality Assessment Layer.

Scores an uploaded document 0-100 on how likely it is that field extraction
will be accurate, from image-appearance signals (resolution, blur, skew,
cropping, lighting, contrast, noise) and OCR-structure signals (text
readability, document completeness, recognition confidence).

The score drives a three-tier decision made by the caller:

    >= high threshold   proceed automatically
    low..high           proceed, but flag the result as caution
    <  low threshold    pause and ask the vendor to re-upload or proceed anyway

DESIGN NOTE - why `ocr_confidence` carries the SMALLEST weight (0.05).

    PaddleOCR's per-line score is its confidence in its own transcription of
    a crop it already decided contained text. It is high on a confidently
    misread blurry glyph, and it never sees text it failed to detect at all.
    Measured over the 99 successfully-processed invoices in test_report.json,
    mean confidence spans 89.88 -> 98.70 (median 94.95, p5 91.5) - an 8.8
    point spread across the *entire* corpus, including files from which only
    45% of invoice numbers were extracted. It is close to a constant.

    The OCR signal that actually moves under degradation lives elsewhere and
    is weighted 3x higher in aggregate: `low_conf_ratio` (inside readability,
    0.10) and `block_count` / `vertical_coverage` (inside completeness, 0.08).
    A blurry page's *mean* confidence barely moves; its detection count
    collapses and its low-confidence tail fattens.

    Please do not "improve" this back into a mean-confidence gate.

PURITY CONTRACT.

    This module imports only cv2, numpy and the stdlib. Nothing from Flask,
    SQLAlchemy, app.*, or engine.py. Every tunable arrives as an argument.
    That is what lets it be unit-tested offline without loading PaddleOCR.

CALIBRATION.

    All normalisation cut-points below are FIRST-PASS DEFAULTS, anchored to a
    1600px probe and to the observed corpus norm of 1275x1651 (US Letter at
    150 DPI). They are meant to be replaced with corpus percentiles - run the
    batch harness in shadow mode (QUALITY_LOG_ONLY=true) and set each cut-point
    near its p5. See the plan's "threshold tuning" section.
"""

import math
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

VERSION = "1.0"

# --------------------------------------------------------------------------
# Weights. Must sum to 1.0.
# --------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "blur":           0.20,   # the single biggest killer of field extraction
    "resolution":     0.12,
    "cropping":       0.12,
    "readability":    0.10,
    "skew":           0.10,
    "lighting":       0.08,
    "contrast":       0.08,
    "completeness":   0.08,
    "noise":          0.07,
    "ocr_confidence": 0.05,   # deliberately smallest - see module docstring
}

# Dimensions whose collapse destroys extraction rather than merely degrading
# it. A weighted mean alone would average a catastrophic one away, so these
# additionally impose a hard ceiling on the document score.
#
# `cropping` is deliberately EXCLUDED despite being a genuine failure mode:
# on the 100-invoice known-good corpus its detector trips a single edge on 28
# documents (letterheads, margin rules, scanner borders). A metric that noisy
# must not be able to cap a document's score by itself. See _m_cropping.
CRITICAL_METRICS = ("blur", "readability", "completeness")

# A metric at 75 imposes no cap (75+25 = 100); a metric at 20 caps the
# document at 45, which forces a hold under the default low threshold of 70.
CRITICAL_FLOOR_MARGIN = 25.0

METRIC_ORDER = tuple(DEFAULT_WEIGHTS.keys())

# --------------------------------------------------------------------------
# Issue vocabulary: stable machine code -> (vendor message, remediation hint)
# --------------------------------------------------------------------------

SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2}

ISSUE_SEVERITY: dict[str, str] = {
    "BLURRY":              "critical",
    "CROPPED":             "critical",
    "INCOMPLETE_DOCUMENT": "critical",
    "ROTATED":             "critical",
    "LOW_RESOLUTION":      "major",
    "SKEWED":              "major",
    "SMALL_TEXT":          "major",
    "LOW_CONTRAST":        "major",
    "POOR_LIGHTING":       "major",
    "SPARSE_TEXT":         "major",
    "NOISY":               "minor",
    "LOW_OCR_CONFIDENCE":  "minor",
}

ISSUE_MESSAGES: dict[str, tuple[str, str]] = {
    "BLURRY": (
        "The invoice looks blurry or out of focus, so characters may be misread.",
        "Rescan at 300 DPI with the page flat and the scanner or camera held steady.",
    ),
    "CROPPED": (
        "Part of the invoice appears cut off at the edge of the page.",
        "Rescan with the whole page inside the frame, leaving a small white "
        "margin on all four sides.",
    ),
    "INCOMPLETE_DOCUMENT": (
        "Large parts of the page contain no readable content - the document "
        "may be incomplete.",
        "Check that the full invoice was scanned and that no pages are missing.",
    ),
    "ROTATED": (
        "The invoice appears to be rotated sideways or upside down.",
        "Rotate the invoice upright before uploading it again.",
    ),
    "LOW_RESOLUTION": (
        "The invoice image is too low-resolution for reliable reading.",
        "Rescan at 300 DPI, or upload the original PDF instead of a screenshot.",
    ),
    "SKEWED": (
        "The invoice appears tilted on the page.",
        "Straighten the page against the scanner edge and rescan.",
    ),
    "SMALL_TEXT": (
        "The text on this invoice is too small to read reliably.",
        "Rescan at a higher resolution so the printed text is larger and sharper.",
    ),
    "LOW_CONTRAST": (
        "The text does not stand out enough from the background.",
        "Rescan in colour or greyscale rather than a faxed or thresholded copy.",
    ),
    "POOR_LIGHTING": (
        "Lighting across the page is uneven, or the scan is too dark.",
        "Use a flatbed scanner, or photograph the page in even light with no "
        "shadow across it.",
    ),
    "SPARSE_TEXT": (
        "Very little text was detected on this document.",
        "Check that you uploaded the invoice itself and that the page is not blank.",
    ),
    "NOISY": (
        "The scan contains speckles or grain that interfere with reading.",
        "Clean the scanner glass and rescan, or upload the original PDF.",
    ),
    "LOW_OCR_CONFIDENCE": (
        "Several parts of the invoice could not be read with confidence.",
        "Upload a clearer or higher-resolution copy of the same invoice.",
    ),
}

VENDOR_HOLD_TITLE = "This invoice may be too low quality to read reliably"
VENDOR_HOLD_MESSAGE = (
    "The invoice you uploaded may be blurry, incomplete, poorly scanned, "
    "cropped, or otherwise difficult to read. We recommend uploading a "
    "higher-quality version."
)

# The two vendor actions are part of the API contract rather than a frontend
# convention, so the server is the source of truth for their ids and labels.
QUALITY_ACTIONS = [
    {"id": "retry", "label": "Upload a Better Invoice", "recommended": True},
    {"id": "proceed", "label": "Proceed Anyway", "recommended": False},
]


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SubMetric:
    name: str
    score: float
    weight: float
    raw: dict
    estimated: bool = False

    def to_dict(self) -> dict:
        out = {
            "score": _jsonable(self.score),
            "weight": _jsonable(self.weight),
            "raw": {k: _jsonable(v) for k, v in self.raw.items()},
        }
        if self.estimated:
            out["estimated"] = True
        return out


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    metric: str
    value: float
    message: str
    hint: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "metric": self.metric,
            "value": _jsonable(self.value),
            "message": self.message,
            "hint": self.hint,
        }


@dataclass(frozen=True)
class QualityReport:
    score: float
    tier: str
    metrics: dict[str, SubMetric]
    issues: list[QualityIssue]
    pages: list[dict] = field(default_factory=list)
    thresholds: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0
    version: str = VERSION

    @property
    def issue_codes(self) -> list[str]:
        return [i.code for i in self.issues]

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "score": _jsonable(self.score),
            "tier": self.tier,
            "thresholds": {k: _jsonable(v) for k, v in self.thresholds.items()},
            "elapsed_ms": _jsonable(self.elapsed_ms),
            "page_count": len(self.pages),
            "metrics": {k: m.to_dict() for k, m in self.metrics.items()},
            "issues": [i.to_dict() for i in self.issues],
            "pages": [
                {
                    "index": int(p["index"]),
                    "score": _jsonable(p["score"]),
                    "metrics": {k: _jsonable(v) for k, v in p["metrics"].items()},
                }
                for p in self.pages
            ],
        }

    def vendor_warning(self) -> dict:
        """The vendor-facing warning block used by the hold response."""
        return {
            "title": VENDOR_HOLD_TITLE,
            "message": VENDOR_HOLD_MESSAGE,
            "issues": [
                {"code": i.code, "message": i.message, "hint": i.hint}
                for i in self.issues
            ],
        }


def _jsonable(v: Any) -> Any:
    """Cast numpy scalars to native Python. Flask's encoder raises on np.float64
    and every metric here comes out of numpy."""
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    if isinstance(v, (np.integer, int)) and not isinstance(v, bool):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


# --------------------------------------------------------------------------
# Normalisation helper
# --------------------------------------------------------------------------

def _piecewise(value: float, points: list[tuple[float, float]]) -> float:
    """Map `value` through a piecewise-linear curve defined by ascending
    (input, output) anchors. Clamped at both ends."""
    if value <= points[0][0]:
        return float(points[0][1])
    if value >= points[-1][0]:
        return float(points[-1][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return float(y1)
            t = (value - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return float(points[-1][1])


def score_to_tier(score: float, high: float = 85.0, low: float = 70.0) -> str:
    if score >= high:
        return "high"
    if score >= low:
        return "medium"
    return "low"


# --------------------------------------------------------------------------
# Per-page probe + shared intermediates
# --------------------------------------------------------------------------

@dataclass
class _Probe:
    gray: np.ndarray          # downscaled grayscale working image
    scale: float              # probe_px / original_px
    orig_h: int
    orig_w: int
    otsu_t: float
    paper_mask: np.ndarray
    ink_mask: np.ndarray
    paper_mean: float
    ink_mean: float
    ink_ratio: float


def _build_probe(image: np.ndarray, probe_max_dim: int,
                 orig_shape: tuple[int, int] | None = None) -> _Probe:
    """Downscale-only grayscale probe plus the Otsu split reused by every
    appearance metric (avoids recomputing the threshold six times)."""
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)

    h, w = gray.shape[:2]
    scale = min(1.0, float(probe_max_dim) / max(h, w)) if max(h, w) > 0 else 1.0
    if scale < 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_AREA)

    # Resolution must reflect the TRUE pixel count, not the probe. When the
    # caller already downscaled before handing us the image, it passes the
    # original shape through explicitly.
    if orig_shape is not None:
        orig_h, orig_w = int(orig_shape[0]), int(orig_shape[1])
        eff_scale = min(1.0, float(probe_max_dim) / max(orig_h, orig_w)) if max(orig_h, orig_w) else 1.0
    else:
        orig_h, orig_w = h, w
        eff_scale = scale

    otsu_t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    paper_mask = gray > otsu_t
    ink_mask = ~paper_mask
    n_paper = int(paper_mask.sum())
    n_ink = int(ink_mask.sum())

    paper_mean = float(gray[paper_mask].mean()) if n_paper else float(gray.mean())
    ink_mean = float(gray[ink_mask].mean()) if n_ink else float(gray.mean())
    ink_ratio = float(ink_mask.mean())

    return _Probe(
        gray=gray, scale=eff_scale, orig_h=orig_h, orig_w=orig_w,
        otsu_t=float(otsu_t), paper_mask=paper_mask, ink_mask=ink_mask,
        paper_mean=paper_mean, ink_mean=ink_mean, ink_ratio=ink_ratio,
    )


# --------------------------------------------------------------------------
# Sub-metrics
# --------------------------------------------------------------------------

def _m_blur(p: _Probe) -> tuple[float, dict]:
    """Laplacian variance. MUST run on the raw grayscale - CLAHE roughly
    doubles this figure and would make every blurred scan look sharp."""
    lap_var = float(cv2.Laplacian(p.gray, cv2.CV_64F).var())
    gx = cv2.Sobel(p.gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(p.gray, cv2.CV_32F, 0, 1, ksize=3)
    edge_density = float((cv2.magnitude(gx, gy) > 40).mean())

    score = _piecewise(lap_var, [(60, 0), (100, 30), (300, 70), (800, 100)])
    # Text-sparse pages depress lap_var. We log ink_ratio alongside rather
    # than adjusting for it - the correction is unvalidated and would need
    # corpus data before it can be trusted.
    return score, {
        "laplacian_var": lap_var,
        "edge_density": edge_density,
        "ink_ratio": p.ink_ratio,
    }


def _m_resolution(p: _Probe) -> tuple[float, dict]:
    short = min(p.orig_h, p.orig_w)
    mp = (p.orig_h * p.orig_w) / 1e6
    # 1275px (US Letter at 150 DPI) is the observed corpus norm and those
    # documents extract successfully, so it must score near the top rather
    # than being treated as merely acceptable.
    score = _piecewise(short, [(700, 0), (900, 35), (1100, 70),
                               (1275, 92), (1500, 100)])
    if mp < 0.8:
        score = min(score, 40.0)
    return score, {
        "short_side_px": short,
        "long_side_px": max(p.orig_h, p.orig_w),
        "megapixels": mp,
    }


def _m_cropping(p: _Probe, blocks: list[dict] | None) -> tuple[float, dict]:
    """Content running off the page edge - e.g. a scan whose right-hand amount
    column has been guillotined.

    An edge must satisfy BOTH tests to count:

      1. Band content - the inner 1.5% border strip carries ink AND
         high-frequency detail. Screens out full-bleed colour header bars and
         printed frame rules, which are flat fill.
      2. Edge transection - the outermost few pixel rows contain ink that
         alternates with whitespace. Cut-off text runs into the final pixel
         line and alternates; a solid black scanner border is uniformly dark
         with no transitions, and a properly-margined page has no ink there
         at all.

    HONEST LIMITATION, measured on the 100-invoice corpus (all known-good):
    28 of them trip a SINGLE edge legitimately - letterheads bleeding to the
    top, left-margin rules, scanner borders. Only 2 trip two edges. So a
    single edge is scored as a mild deduction but never raises CROPPED; the
    issue needs 2+ edges. That trades recall on the single-guillotined-edge
    case for a false-positive rate low enough to be usable. `cropping` is
    also deliberately NOT in CRITICAL_METRICS for the same reason - it must
    not be able to cap the document score on its own. Revisit once there are
    labelled positive examples to calibrate against.
    """
    h, w = p.gray.shape[:2]
    depth = 3
    band_h = max(6, int(0.015 * h))
    band_w = max(6, int(0.015 * w))

    specs = (
        ("top",    p.ink_mask[:band_h, :],  p.ink_mask[:depth, :],    p.gray[:band_h, :]),
        ("bottom", p.ink_mask[-band_h:, :], p.ink_mask[-depth:, :],   p.gray[-band_h:, :]),
        ("left",   p.ink_mask[:, :band_w].T, p.ink_mask[:, :depth].T, p.gray[:, :band_w]),
        ("right",  p.ink_mask[:, -band_w:].T, p.ink_mask[:, -depth:].T, p.gray[:, -band_w:]),
    )

    cropped_edges: list[str] = []
    edge_stats: dict[str, dict] = {}
    for name, band, strip, region in specs:
        band_ink = float(band.mean())
        band_lap = float(cv2.Laplacian(region, cv2.CV_64F).var())
        line = strip.any(axis=0)
        line_frac = float(line.mean())
        transitions = (
            float(np.abs(np.diff(line.astype(np.int8))).sum()) / max(len(line), 1)
        )
        edge_stats[name] = {
            "band_ink": round(band_ink, 4), "band_lap": round(band_lap, 1),
            "line_frac": round(line_frac, 4), "transitions": round(transitions, 4),
        }
        if (band_ink > 0.015 and band_lap > 40
                and line_frac > 0.010 and transitions > 0.006):
            cropped_edges.append(name)

    clipped: dict[str, int] = {}
    if blocks:
        for b in blocks:
            box = b.get("_probe_box")
            if not box:
                continue
            x0, y0, x1, y1 = box
            if x0 <= band_w:
                clipped["left"] = clipped.get("left", 0) + 1
            if x1 >= w - band_w:
                clipped["right"] = clipped.get("right", 0) + 1
            if y0 <= band_h:
                clipped["top"] = clipped.get("top", 0) + 1
            if y1 >= h - band_h:
                clipped["bottom"] = clipped.get("bottom", 0) + 1

    n = len(cropped_edges)
    if n == 0:
        score = 100.0
    elif n == 1:
        # Mild nudge only: too common in legitimate documents to punish hard.
        score = 85.0
        if clipped.get(cropped_edges[0], 0) >= 3:
            score = 72.0
    else:
        score = max(0.0, 100.0 - 30.0 * n)
        for edge in cropped_edges:
            if clipped.get(edge, 0) >= 3:
                score = max(0.0, score - 10.0)

    return score, {
        "cropped_edges": cropped_edges,
        "edge_count": n,
        "clipped_blocks": clipped,
        "edges": edge_stats,
    }


def _projection_profile_skew(ink_mask: np.ndarray,
                             limit_deg: float = 8.0,
                             step_deg: float = 0.5) -> float:
    """Estimate text skew by maximising the variance of the horizontal
    projection profile over candidate rotations.

    When lines of text are level, every row is either dense ink or empty
    whitespace, so the row-sum profile has high variance. Tilt smears ink
    across rows and flattens it. This is the standard document-deskew
    estimator and, unlike a whole-page minAreaRect, it measures the *text*
    rather than the page rectangle.

    Runs on a heavily downscaled copy (~500px) so the ~33 candidate
    rotations stay cheap.
    """
    h, w = ink_mask.shape[:2]
    if h < 32 or w < 32:
        return 0.0
    small = (ink_mask.astype(np.uint8)) * 255
    scale = min(1.0, 500.0 / max(h, w))
    if scale < 1.0:
        small = cv2.resize(small, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
    if small.sum() == 0:
        return 0.0

    sh, sw = small.shape[:2]
    centre = (sw / 2.0, sh / 2.0)
    best_angle, best_score = 0.0, -1.0
    angle = -limit_deg
    while angle <= limit_deg + 1e-9:
        m = cv2.getRotationMatrix2D(centre, angle, 1.0)
        rot = cv2.warpAffine(small, m, (sw, sh), flags=cv2.INTER_NEAREST,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        profile = rot.sum(axis=1, dtype=np.float64)
        score = float(np.diff(profile).__pow__(2).sum())
        if score > best_score:
            best_score, best_angle = score, angle
        angle += step_deg
    return float(best_angle)


def _m_skew(p: _Probe, blocks: list[dict] | None) -> tuple[float, dict, bool]:
    """Text baseline tilt.

    Block-based estimation is preferred and free: the OCR quadrilaterals give
    a direct measurement of baseline angle, far more robust than a whole-page
    minAreaRect. The pixel fallback reuses the angle computation from
    services/preprocessing_service.apply_skew_correction - angle only, we
    never warp anything here.
    """
    estimated = False
    angles: list[float] = []
    tall_blocks = 0
    counted = 0

    if blocks:
        for b in blocks:
            quad = b.get("_probe_quad")
            if not quad or len(quad) < 4:
                continue
            (x_tl, y_tl), (x_tr, y_tr) = quad[0], quad[1]
            width = math.hypot(x_tr - x_tl, y_tr - y_tl)
            if width < 30:
                continue
            angles.append(math.degrees(math.atan2(y_tr - y_tl, x_tr - x_tl)))
            counted += 1
            box = b.get("_probe_box")
            if box and (box[3] - box[1]) > (box[2] - box[0]):
                tall_blocks += 1

    if not angles:
        estimated = True
        skew_deg = _projection_profile_skew(p.ink_mask)
        spread = 0.0
        raw = {"skew_deg": skew_deg, "skew_spread_deg": 0.0, "sample": 0,
               "tall_block_ratio": 0.0, "method": "projection_profile"}
        # Deliberately never assert ROTATED without block data. A whole-page
        # ink minAreaRect reports ~90 degrees on perfectly upright invoices
        # (it locks onto the page rectangle, not the text baselines) and
        # produced a 40% false-positive rate on the known-good corpus.
        score = _piecewise(abs(skew_deg),
                           [(0.5, 100), (1, 90), (3, 60), (7, 20), (12, 0)])
        return score, raw, estimated
    else:
        arr = np.asarray(angles, dtype=np.float64)
        skew_deg = float(np.median(arr))
        spread = float(np.percentile(arr, 90) - np.percentile(arr, 10))

    raw = {
        "skew_deg": skew_deg,
        "skew_spread_deg": spread,
        "sample": counted,
        "tall_block_ratio": (tall_blocks / counted) if counted else 0.0,
    }

    # Full-page rotation. Note use_angle_cls=True in the OCR engine already
    # flips individual *lines* 180 degrees, so a whole-page 180 rotation is
    # partly masked; sideways rotation is what this reliably catches.
    rotated = abs(skew_deg) > 60 or (counted >= 10 and tall_blocks / counted > 0.6)
    if rotated:
        raw["rotated"] = True
        return 0.0, raw, estimated

    score = _piecewise(abs(skew_deg),
                       [(0.5, 100), (1, 90), (3, 60), (7, 20), (12, 0)])
    return score, raw, estimated


def _m_lighting(p: _Probe) -> tuple[float, dict]:
    """Uneven illumination and gross under/over-exposure.

    Framed as paper *uniformity*, not highlight clipping: a clean white scan
    has ~60% of pixels above 247, so a naive clipping penalty would fail every
    good invoice.
    """
    h, w = p.gray.shape[:2]
    gh, gw = max(1, h // 8), max(1, w // 8)
    tile_means: list[float] = []
    for i in range(8):
        for j in range(8):
            y0, y1 = i * gh, (i + 1) * gh if i < 7 else h
            x0, x1 = j * gw, (j + 1) * gw if j < 7 else w
            tile = p.gray[y0:y1, x0:x1]
            tile_paper = p.paper_mask[y0:y1, x0:x1]
            if tile.size == 0:
                continue
            if tile_paper.any():
                tile_means.append(float(tile[tile_paper].mean()))
            else:
                tile_means.append(float(tile.mean()))

    if len(tile_means) < 4:
        illum_range = 0.0
    else:
        arr = np.asarray(tile_means)
        illum_range = float(np.percentile(arr, 90) - np.percentile(arr, 10))

    score = _piecewise(illum_range, [(15, 100), (40, 60), (90, 0)])
    if p.paper_mean < 110:
        score = min(score, 40.0)
    if p.paper_mean > 252 and (p.paper_mean - p.ink_mean) < 60:
        score = min(score, 45.0)

    return score, {
        "illum_range": illum_range,
        "paper_mean": p.paper_mean,
        "tiles": len(tile_means),
    }


def _m_contrast(p: _Probe) -> tuple[float, dict]:
    """Ink/paper separation. Raw only - CLAHE would flatten this to a constant."""
    gap = p.paper_mean - p.ink_mean
    score = _piecewise(gap, [(25, 0), (40, 15), (70, 50), (100, 80), (140, 100)])
    return score, {"gap": gap, "std": float(p.gray.std()),
                   "otsu_threshold": p.otsu_t}


def _m_noise(p: _Probe) -> tuple[float, dict]:
    """Immerkaer fast Gaussian-sigma estimator plus a speckle ratio.

    Masking the kernel response to paper pixels is essential: text edges
    otherwise dominate the response and every dense invoice reads as noisy.
    """
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
    resp = cv2.filter2D(p.gray.astype(np.float32), -1, kernel)
    if p.paper_mask.any():
        sigma = float(np.abs(resp[p.paper_mask]).mean() * math.sqrt(math.pi / 2) / 6.0)
    else:
        sigma = float(np.abs(resp).mean() * math.sqrt(math.pi / 2) / 6.0)

    # Fraction of ink removed by a morphological opening: high means the ink
    # is mostly isolated specks rather than connected strokes.
    #
    # Compute this with boolean logic, NOT uint8 subtraction. OpenCV's even
    # kernels carry an anchor offset, so `opened` can contain pixels `ink`
    # does not; `ink_u8 - opened` then underflows to 255 and the "ratio"
    # comes out in the tens instead of [0, 1].
    ink_u8 = p.ink_mask.astype(np.uint8)
    opened = cv2.morphologyEx(ink_u8, cv2.MORPH_OPEN,
                              np.ones((3, 3), np.uint8)).astype(bool)
    ink_sum = int(p.ink_mask.sum())
    removed = int(np.logical_and(p.ink_mask, ~opened).sum())
    speckle_ratio = float(removed / max(ink_sum, 1))

    score = _piecewise(sigma, [(2, 100), (5, 75), (10, 45), (20, 0)])
    # Printed invoice text at ~2px stroke width legitimately loses a large
    # share of its ink to a 3x3 opening, so this cap is deliberately set well
    # above what clean documents produce (corpus p95 is ~0.75).
    if speckle_ratio > 0.90:
        score = min(score, 50.0)

    return score, {"sigma_paper": sigma, "speckle_ratio": speckle_ratio}


def _m_readability(p: _Probe, blocks: list[dict] | None) -> tuple[float, dict, bool]:
    """How legible the detected text is: how tall it is, and how much of it
    the recogniser was unsure about."""
    if blocks:
        heights = [b["_probe_box"][3] - b["_probe_box"][1]
                   for b in blocks if b.get("_probe_box")]
        confs = [float(b.get("confidence", 1.0)) for b in blocks]
        median_h = float(np.median(heights)) if heights else 0.0
        low_conf_ratio = (
            float(sum(1 for c in confs if c < 0.80) / len(confs)) if confs else 0.0
        )
        h_score = _piecewise(median_h,
                             [(7, 0), (9, 20), (12, 45), (16, 75), (22, 100)])
        lc_score = _piecewise(low_conf_ratio,
                              [(0.05, 100), (0.15, 70), (0.30, 35), (0.50, 0)])
        score = 0.6 * h_score + 0.4 * lc_score
        return score, {
            "median_text_h_px": median_h,
            "low_conf_ratio": low_conf_ratio,
            "h_score": h_score,
            "lowconf_score": lc_score,
        }, False

    # Pixel fallback: stroke width via distance transform.
    ink_u8 = (p.ink_mask.astype(np.uint8)) * 255
    dist = cv2.distanceTransform(ink_u8, cv2.DIST_L2, 3)
    vals = dist[dist > 0]
    stroke = float(2.0 * np.median(vals)) if vals.size else 0.0
    # ~1.9px is the corpus norm for cleanly-printed 150 DPI invoice body text.
    h_score = _piecewise(stroke, [(0.8, 10), (1.2, 40), (1.6, 70),
                                  (1.9, 90), (2.5, 100)])
    return h_score, {"stroke_width_px": stroke, "h_score": h_score}, True


def _m_completeness(p: _Probe, blocks: list[dict] | None) -> tuple[float, dict, bool]:
    """Is there a whole invoice's worth of content, spread over the page?

    This subsumes the old MIN_OCR_WORDS gate.
    """
    h, w = p.gray.shape[:2]
    page_area = float(h * w) or 1.0

    if blocks:
        count = len(blocks)
        band_hit = set()
        text_area = 0.0
        for b in blocks:
            box = b.get("_probe_box")
            if not box:
                continue
            y_c = (box[1] + box[3]) / 2.0
            band_hit.add(min(19, max(0, int(20 * y_c / max(h, 1)))))
            text_area += max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
        coverage = len(band_hit) / 20.0
        area_ratio = text_area / page_area
        estimated = False
    else:
        # Without blocks, approximate from connected components of ink.
        ink_u8 = (p.ink_mask.astype(np.uint8)) * 255
        n_labels, _, stats, centroids = cv2.connectedComponentsWithStats(ink_u8, 8)
        keep = [i for i in range(1, n_labels) if stats[i, cv2.CC_STAT_AREA] >= 12]
        count = len(keep)
        band_hit = {min(19, max(0, int(20 * centroids[i][1] / max(h, 1)))) for i in keep}
        coverage = len(band_hit) / 20.0
        area_ratio = float(p.ink_ratio)
        estimated = True

    c_score = _piecewise(count, [(2, 0), (6, 15), (15, 40), (30, 70), (60, 100)])
    v_score = _piecewise(coverage, [(0.15, 0), (0.35, 60), (0.60, 100)])
    if area_ratio < 0.005 or area_ratio > 0.75:
        a_score = 0.0
    elif 0.03 <= area_ratio <= 0.50:
        a_score = 100.0
    elif area_ratio < 0.03:
        a_score = _piecewise(area_ratio, [(0.005, 0), (0.03, 100)])
    else:
        a_score = _piecewise(area_ratio, [(0.50, 100), (0.75, 0)])

    score = 0.5 * c_score + 0.3 * v_score + 0.2 * a_score
    return score, {
        "block_count": count,
        "vertical_coverage": coverage,
        "text_area_ratio": area_ratio,
        "count_score": c_score,
        "coverage_score": v_score,
    }, estimated


def _m_ocr_confidence(blocks: list[dict] | None) -> tuple[float, dict, bool]:
    """See the module docstring for why this is weighted 0.05."""
    if not blocks:
        return 70.0, {"mean_conf": None, "low_conf_ratio": None}, True
    confs = [float(b.get("confidence", 1.0)) for b in blocks]
    mean_conf = float(np.mean(confs))
    low_conf_ratio = float(sum(1 for c in confs if c < 0.80) / len(confs))
    # Re-anchored so the observed corpus (0.899 - 0.987) spreads across
    # 40-100 rather than collapsing into a single point near the top.
    score = _piecewise(mean_conf,
                       [(0.85, 0), (0.90, 40), (0.94, 70), (0.97, 95), (0.985, 100)])
    return score, {"mean_conf": mean_conf, "low_conf_ratio": low_conf_ratio}, False


# --------------------------------------------------------------------------
# Issue detection
# --------------------------------------------------------------------------

def _detect_issues(scores: dict[str, float],
                   raws: dict[str, dict]) -> list[QualityIssue]:
    found: list[tuple[str, str, float, float]] = []   # code, metric, value, shortfall

    def add(code: str, metric: str, value: float, cut: float, actual: float):
        found.append((code, metric, value, cut - actual))

    if raws.get("skew", {}).get("rotated"):
        add("ROTATED", "skew", raws["skew"].get("skew_deg", 0.0), 100.0, 0.0)
    if scores["blur"] < 45:
        add("BLURRY", "blur", raws["blur"]["laplacian_var"], 45.0, scores["blur"])
    # Needs 2+ transected edges. A single edge is legitimate on 28% of the
    # known-good corpus, so it deducts score but never raises the issue.
    if raws.get("cropping", {}).get("edge_count", 0) >= 2:
        add("CROPPED", "cropping", scores["cropping"], 60.0, scores["cropping"])
    if raws.get("completeness", {}).get("coverage_score", 100) < 40:
        add("INCOMPLETE_DOCUMENT", "completeness",
            raws["completeness"]["vertical_coverage"], 40.0,
            raws["completeness"]["coverage_score"])
    if scores["resolution"] < 50:
        add("LOW_RESOLUTION", "resolution",
            raws["resolution"]["short_side_px"], 50.0, scores["resolution"])
    if scores["skew"] < 55 and not raws.get("skew", {}).get("rotated"):
        add("SKEWED", "skew", raws["skew"]["skew_deg"], 55.0, scores["skew"])
    if raws.get("readability", {}).get("h_score", 100) < 45:
        add("SMALL_TEXT", "readability",
            raws["readability"].get("median_text_h_px",
                                    raws["readability"].get("stroke_width_px", 0)),
            45.0, raws["readability"]["h_score"])
    if scores["contrast"] < 45:
        add("LOW_CONTRAST", "contrast", raws["contrast"]["gap"], 45.0, scores["contrast"])
    if scores["lighting"] < 55:
        add("POOR_LIGHTING", "lighting",
            raws["lighting"]["illum_range"], 55.0, scores["lighting"])
    if raws.get("completeness", {}).get("count_score", 100) < 40:
        add("SPARSE_TEXT", "completeness",
            raws["completeness"]["block_count"], 40.0,
            raws["completeness"]["count_score"])
    if scores["noise"] < 50:
        add("NOISY", "noise", raws["noise"]["sigma_paper"], 50.0, scores["noise"])

    mean_conf = raws.get("ocr_confidence", {}).get("mean_conf")
    lcr = raws.get("ocr_confidence", {}).get("low_conf_ratio")
    if (mean_conf is not None and mean_conf < 0.88) or (lcr is not None and lcr > 0.25):
        add("LOW_OCR_CONFIDENCE", "ocr_confidence",
            mean_conf if mean_conf is not None else 0.0, 100.0, scores["ocr_confidence"])

    # Sort by severity, then by how far below its cut-point the metric fell,
    # so issues[0] is always the headline problem for the UI.
    found.sort(key=lambda t: (SEVERITY_RANK[ISSUE_SEVERITY[t[0]]], -t[3]))

    issues = []
    for code, metric, value, _shortfall in found:
        message, hint = ISSUE_MESSAGES[code]
        issues.append(QualityIssue(
            code=code, severity=ISSUE_SEVERITY[code], metric=metric,
            value=float(value) if value is not None else 0.0,
            message=message, hint=hint,
        ))
    return issues


# --------------------------------------------------------------------------
# Page + document assessment
# --------------------------------------------------------------------------

def _prepare_blocks(blocks: list[dict] | None, probe: _Probe) -> list[dict] | None:
    """Attach probe-space geometry to each OCR block.

    Incoming boxes are in ORIGINAL pixel coordinates; every metric works in
    probe space, so convert once here rather than in each metric.
    """
    if not blocks:
        return None
    out = []
    s = probe.scale
    for b in blocks:
        quad = b.get("box")
        if not quad or len(quad) < 4:
            continue
        pts = [(float(x) * s, float(y) * s) for x, y in quad[:4]]
        xs = [pt[0] for pt in pts]
        ys = [pt[1] for pt in pts]
        nb = dict(b)
        nb["_probe_quad"] = pts
        nb["_probe_box"] = [min(xs), min(ys), max(xs), max(ys)]
        out.append(nb)
    return out or None


def assess_page(raw_image: np.ndarray,
                blocks: list[dict] | None = None,
                *,
                probe_max_dim: int = 1600,
                orig_shape: tuple[int, int] | None = None,
                weights: dict[str, float] | None = None) -> dict:
    """Assess a single page. Returns a dict with `score`, `metrics`
    (name -> SubMetric), `raws`, and `issues`."""
    w = weights or DEFAULT_WEIGHTS
    probe = _build_probe(raw_image, probe_max_dim, orig_shape)
    pblocks = _prepare_blocks(blocks, probe)

    # Degenerate page: blank, inverted, or all-black. Nothing else is meaningful.
    if probe.ink_ratio < 0.002 or probe.ink_ratio > 0.6:
        message, hint = ISSUE_MESSAGES["INCOMPLETE_DOCUMENT"]
        metrics = {
            name: SubMetric(name, 0.0, w[name], {"degenerate": True}, True)
            for name in METRIC_ORDER
        }
        return {
            "score": 0.0,
            "metrics": metrics,
            "raws": {"degenerate": {"ink_ratio": probe.ink_ratio}},
            "issues": [QualityIssue("INCOMPLETE_DOCUMENT", "critical",
                                    "completeness", probe.ink_ratio,
                                    message, hint)],
        }

    scores: dict[str, float] = {}
    raws: dict[str, dict] = {}
    estimated: dict[str, bool] = {}

    scores["blur"], raws["blur"] = _m_blur(probe)
    scores["resolution"], raws["resolution"] = _m_resolution(probe)
    scores["cropping"], raws["cropping"] = _m_cropping(probe, pblocks)
    scores["lighting"], raws["lighting"] = _m_lighting(probe)
    scores["contrast"], raws["contrast"] = _m_contrast(probe)
    scores["noise"], raws["noise"] = _m_noise(probe)
    scores["skew"], raws["skew"], estimated["skew"] = _m_skew(probe, pblocks)
    scores["readability"], raws["readability"], estimated["readability"] = \
        _m_readability(probe, pblocks)
    scores["completeness"], raws["completeness"], estimated["completeness"] = \
        _m_completeness(probe, pblocks)
    scores["ocr_confidence"], raws["ocr_confidence"], estimated["ocr_confidence"] = \
        _m_ocr_confidence(pblocks)

    page_score = aggregate(scores, w)
    issues = _detect_issues(scores, raws)

    metrics = {
        name: SubMetric(name, round(scores[name], 1), w[name], raws[name],
                        estimated.get(name, False))
        for name in METRIC_ORDER
    }
    return {"score": page_score, "metrics": metrics, "raws": raws, "issues": issues}


def aggregate(scores: dict[str, float],
              weights: dict[str, float] | None = None) -> float:
    """Weighted mean, capped by a critical-dimension floor.

    A pure weighted mean lets one catastrophic dimension be averaged away: an
    invoice that is sharp, well-lit, high-res, unskewed and clean but whose
    right-hand amount column is guillotined scores cropping=20 and still lands
    near 88 - it would sail through as "high". The floor caps it at 45.
    """
    w = weights or DEFAULT_WEIGHTS
    weighted = sum(w[k] * scores.get(k, 0.0) for k in w)
    hard_floor = min(scores.get(k, 100.0) + CRITICAL_FLOOR_MARGIN
                     for k in CRITICAL_METRICS)
    return round(min(weighted, hard_floor, 100.0), 1)


def assess_quality(raw_images: list[np.ndarray],
                   ocr_blocks: list[list[dict]] | None = None,
                   *,
                   orig_shapes: list[tuple[int, int]] | None = None,
                   thresholds: tuple[float, float] = (85.0, 70.0),
                   weights: dict[str, float] | None = None,
                   probe_max_dim: int = 1600,
                   max_pages: int = 5) -> QualityReport:
    """Assess a document.

    raw_images  RAW decoded pages (RGB or grayscale uint8). NOT CLAHE-processed -
                see the module docstring; blur/contrast/lighting/noise are
                meaningless on an enhanced image.
    ocr_blocks  Optional per-page list of {"text", "confidence", "box": [[x,y]x4]}
                in the coordinate space of the corresponding raw image. When
                omitted, block-derived metrics fall back to pixel estimators and
                are flagged `estimated`.
    orig_shapes Optional per-page (h, w) of the true source page, for when the
                caller already downscaled before calling. Resolution is scored
                from this, never from the probe.

    Document score is min(page_scores): one unreadable page holds the whole
    document, because the totals could be on that page.
    """
    t0 = time.perf_counter()
    high, low = thresholds
    w = weights or DEFAULT_WEIGHTS

    if not raw_images:
        return QualityReport(
            score=0.0, tier="low", metrics={}, issues=[], pages=[],
            thresholds={"high": high, "low": low},
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )

    n = min(len(raw_images), max_pages)
    # If block lists and images disagree in length, zip to the shorter rather
    # than crashing. _run_document_ocr skips pages with no detections, so the
    # two can legitimately desynchronise on a document with a blank page.
    blocks_available = ocr_blocks is not None and len(ocr_blocks) >= 1

    page_results = []
    for i in range(n):
        blocks = None
        if blocks_available and i < len(ocr_blocks):
            blocks = ocr_blocks[i]
        shape = orig_shapes[i] if orig_shapes and i < len(orig_shapes) else None
        page_results.append(
            assess_page(raw_images[i], blocks, probe_max_dim=probe_max_dim,
                        orig_shape=shape, weights=w)
        )

    worst_idx = min(range(len(page_results)), key=lambda i: page_results[i]["score"])
    worst = page_results[worst_idx]
    doc_score = float(worst["score"])

    pages = [
        {
            "index": i,
            "score": pr["score"],
            "metrics": {k: m.score for k, m in pr["metrics"].items()},
        }
        for i, pr in enumerate(page_results)
    ]

    # Union the issues across pages, keeping the worst page's ordering first.
    seen = set()
    issues: list[QualityIssue] = []
    for issue in worst["issues"]:
        if issue.code not in seen:
            seen.add(issue.code)
            issues.append(issue)
    for i, pr in enumerate(page_results):
        if i == worst_idx:
            continue
        for issue in pr["issues"]:
            if issue.code not in seen:
                seen.add(issue.code)
                issues.append(issue)

    return QualityReport(
        score=doc_score,
        tier=score_to_tier(doc_score, high, low),
        metrics=worst["metrics"],
        issues=issues,
        pages=pages,
        thresholds={"high": high, "low": low},
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
    )
