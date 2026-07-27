import cv2
import numpy as np
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from app.ocr.paddleOCR import ocr

def visualize_ocr(image_path, output_path):
    print(f"Reading image/pdf: {image_path}")
    from app.utils.utils import pdf_to_images, _is_pdf
    
    with open(image_path, 'rb') as f:
        file_bytes = f.read()
        
    images = []
    if _is_pdf(file_bytes):
        images = pdf_to_images(file_bytes, dpi=300)
    else:
        img = cv2.imread(image_path)
        if img is not None:
            images = [cv2.cvtColor(img, cv2.COLOR_BGR2RGB)]
            
    if not images:
        print("Failed to load image or PDF.")
        return
        
    for page_num, img_rgb in enumerate(images):
        print(f"Running PaddleOCR on page {page_num + 1}...")
        results = ocr.ocr(img_rgb, cls=True)
        
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        
        print("Drawing bounding boxes...")
        if results and results[0]:
            for line in results[0]:
                box = line[0]
                pts = np.array(box, np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(img_bgr, [pts], True, (0, 255, 0), 2)
                cv2.circle(img_bgr, (int(box[0][0]), int(box[0][1])), 4, (255, 0, 0), -1)

        out_path = output_path
        if len(images) > 1:
            base, ext = os.path.splitext(output_path)
            out_path = f"{base}_page{page_num + 1}{ext}"
            
        print(f"Saving visualized image to: {out_path}")
        cv2.imwrite(out_path, img_bgr)
        
    print("Done!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 visualize_paddle.py <path_to_image_or_pdf>")
        sys.exit(1)
        
    input_file = sys.argv[1]
    base, ext = os.path.splitext(input_file)
    output_file = f"{base}_visualized.jpg"
    
    visualize_ocr(input_file, output_file)
