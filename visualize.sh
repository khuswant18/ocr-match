#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: ./visualize.sh <path_to_pdf_or_image>"
    echo "Example: ./visualize.sh test_samples/my_invoice.pdf"
    exit 1
fi

FILE_PATH=$1

echo "Visualizing layout for: $FILE_PATH"
# Run the python script inside the backend container, passing the file path
/Applications/Docker.app/Contents/Resources/bin/docker exec ocr-match-backend-1 python3 /app/visualize_paddle.py "/app/$FILE_PATH"

echo ""
echo "Done! You can find the visualized images saved right next to your original file."
