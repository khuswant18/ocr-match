import sys
import os
sys.path.insert(0, '/Users/khuswant/Desktop/ocr-match/backend')
from app.services.matching_service import get_po_items, _po_items_from_lines
print("fetching 4016684")
print(_po_items_from_lines(get_po_items('4016684')))
