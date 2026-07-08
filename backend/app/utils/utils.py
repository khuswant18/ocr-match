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


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Correct small rotations (<5 deg) common in scanned invoices."""
    coords = np.column_stack(np.where(gray < 200))
    if len(coords) < 100:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    elif angle > 45:
        angle = 90 - angle
    else:
        angle = -angle
    if abs(angle) < 0.3 or abs(angle) > 5.0:
        return gray
    h, w = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def preprocess_for_ocr(img: np.ndarray) -> np.ndarray:
    """
    Return a single enhanced image for OCR (light CLAHE).
    """
    if len(img.shape) == 2:
        gray = img
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    gray = _deskew(gray)

    clahe_light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe_light.apply(gray)
    rgb = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)

    return np.ascontiguousarray(rgb)

def load_images_from_bytes(file_bytes: bytes):
    """
    Turn raw uploaded file bytes (PDF or image) into a flat list of
    preprocessed images (one per page), ready for OCR. Returns None if the
    bytes are empty or cannot be decoded.

    Shared by the /paddleOCR HTTP route and the background worker, so both
    paths run the identical PDF-vs-image + preprocessing pipeline.
    """
    if not file_bytes:
        return None

    if _is_pdf(file_bytes):
        raw_images = pdf_to_images(file_bytes, dpi=300)
        if not raw_images:
            return None
        return [preprocess_for_ocr(img) for img in raw_images]

    npimg = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return [preprocess_for_ocr(img)]


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
    """Legacy single-image loader for preprocessing routes."""
    page_variants = load_images_from_request()
    if page_variants and len(page_variants) > 0:
        return page_variants[0][0]
    return None