import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"
os.environ["OMP_NUM_THREADS"] = "1"
import cv2
cv2.setNumThreads(0)
from paddleocr import PaddleOCR
print("Starting...")
ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
print("Loaded PaddleOCR")
img = cv2.imread('../sample/invoice.jpg')
print("Image shape:", img.shape)
result = ocr.ocr(img, cls=True)
print("Finished!")
