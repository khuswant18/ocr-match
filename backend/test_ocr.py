import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"
os.environ["OMP_NUM_THREADS"] = "1"
import cv2
from paddleocr import PaddleOCR
ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=True)
img = cv2.imread('sample/invoice.jpg')
print("Running OCR...")
result = ocr.ocr(img, cls=True)
print("Finished!")
