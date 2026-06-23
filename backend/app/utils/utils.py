import io
import base64
import cv2
import numpy as np
import fitz
from flask import request
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


def preprocess_for_ocr(img: np.ndarray) -> list[np.ndarray]:
    print("preprocess_for_ocr",img) 
    """
    Return TWO versions of the image for dual-pass OCR:
      1. Light enhancement (good for clean/digital PDFs)
      2. Aggressive enhancement (good for faded scans)

    PaddleOCR runs on both and we merge the results, keeping the
    higher-confidence detection for each text region.
    """
    if len(img.shape) == 2:
        gray = img
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    gray = _deskew(gray)

    # Pass 1: Light CLAHE only
    clahe_light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    pass1 = clahe_light.apply(gray)
    pass1_rgb = cv2.cvtColor(pass1, cv2.COLOR_GRAY2RGB)

    # Pass 2: Aggressive — sharpen + stronger CLAHE + denoise
    clahe_strong = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
    enhanced = clahe_strong.apply(gray)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharpened = cv2.filter2D(enhanced, -1, kernel)
    denoised = cv2.fastNlMeansDenoising(sharpened, h=12, templateWindowSize=7, searchWindowSize=21)
    pass2_rgb = cv2.cvtColor(denoised, cv2.COLOR_GRAY2RGB)
    print("pass1_rgb",pass1_rgb,"pass2_rgb",pass2_rgb)
    return [pass1_rgb, pass2_rgb]


def load_images_from_request():
    """
    Read the uploaded file from the Flask request and return a list of
    (image_variants) ready for OCR. Each page produces multiple
    preprocessed variants for dual-pass OCR.
    """
    file = request.files.get('file')
    if file is None:
        return None

    file_bytes = file.read()
    if not file_bytes:
        return None

    if _is_pdf(file_bytes):
        raw_images = pdf_to_images(file_bytes, dpi=300)
        if not raw_images:
            return None
        all_variants = []
        for img in raw_images:
            all_variants.append(preprocess_for_ocr(img))
        print("all_variants",all_variants)
        return all_variants

    npimg = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return [preprocess_for_ocr(img)]


def load_image():
    """Legacy single-image loader for preprocessing routes."""
    page_variants = load_images_from_request()
    if page_variants and len(page_variants) > 0:
        return page_variants[0][0]
    return None