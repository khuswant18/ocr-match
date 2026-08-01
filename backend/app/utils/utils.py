import io
import base64
# pyrefly: ignore [missing-import]
import cv2
# pyrefly: ignore [missing-import]
import numpy as np
# pyrefly: ignore [missing-import]
import fitz
# pyrefly: ignore [missing-import]
from flask import request
# pyrefly: ignore [missing-import]
from PIL import Image

def convert_to_base64(img):
    img = Image.fromarray(img.astype("uint8"))
    raw_bytes = io.BytesIO()
    img.save(raw_bytes, "JPEG")
    raw_bytes.seek(0)
    img_base64 = base64.b64encode(raw_bytes.read())
    return str(img_base64)

def _is_pdf(file_bytes: bytes) -> bool:
    return file_bytes[:5] == b'%PDF-'

def pdf_to_images(pdf_bytes: bytes, dpi: int = 300) -> list:
    """Convert every page of a PDF to a high-resolution RGB numpy array."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        if pix.n == 4:
            img_array = cv2.cvtColor(img_array, cv2.COLOR_BGRA2RGB)
        images.append(img_array)
    doc.close()
    return images

def preprocess_for_ocr(img: np.ndarray) -> np.ndarray:
    """
    Return a single enhanced image for OCR (light CLAHE).
    """
    if len(img.shape) == 2:
        gray = img
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        

    clahe_light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe_light.apply(gray)
    rgb = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)

    return np.ascontiguousarray(rgb)

def _downscale_probe(img: np.ndarray, max_dim: int) -> np.ndarray:
    """Downscale-only copy used for quality analysis.

    A 300-DPI PDF page is 2480x3508x3 (~26 MB); at 1600px it is ~1.8 MB. The
    quality metrics all work on a bounded probe anyway, so shrinking here
    keeps peak memory sane on multi-page PDFs.
    """
    h, w = img.shape[:2]
    if max_dim and max(h, w) > max_dim:
        scale = max_dim / float(max(h, w))
        return cv2.resize(img, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_AREA)
    return img


def load_images_from_bytes(file_bytes: bytes, *, with_raw: bool = False,
                           raw_max_dim: int = 1600):
    """
    Turn raw uploaded file bytes (PDF or image) into a flat list of
    preprocessed images (one per page), ready for OCR. Returns None if the
    bytes are empty or cannot be decoded.

    with_raw=True additionally returns the RAW (un-CLAHE'd) page probes and
    each page's true original (h, w), as `(processed, raw_probes, orig_shapes)`.
    The quality layer needs the raw decode: `preprocess_for_ocr` applies CLAHE,
    which roughly doubles Laplacian variance and would make every blurred scan
    look sharp, while flattening the contrast and lighting signals entirely.

    Both lists come from the SAME single decode/render - the PDF is rasterised
    once and the enhancement applied to a copy. Returns (None, None, None) on
    failure when with_raw is set.
    """
    if not file_bytes:
        return (None, None, None) if with_raw else None

    if _is_pdf(file_bytes):
        raw_images = pdf_to_images(file_bytes, dpi=300)
        if not raw_images:
            return (None, None, None) if with_raw else None
        processed = [preprocess_for_ocr(img) for img in raw_images]
        if not with_raw:
            return processed
        shapes = [(img.shape[0], img.shape[1]) for img in raw_images]
        probes = [_downscale_probe(img, raw_max_dim) for img in raw_images]
        return processed, probes, shapes

    npimg = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    if img is None:
        return (None, None, None) if with_raw else None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    processed = [preprocess_for_ocr(img)]
    if not with_raw:
        return processed
    return (processed,
            [_downscale_probe(img, raw_max_dim)],
            [(img.shape[0], img.shape[1])])

def load_images_from_request():
    """
    Read the uploaded file from the Flask request and return a flat list
    of preprocessed images (one per page), ready for OCR.
    """
    file = request.files.get('file')
    if file is None:
        return None

    return load_images_from_bytes(file.read())

def load_image():
    images = load_images_from_request()
    if images:
        return images[0]
    return None