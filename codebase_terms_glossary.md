# Codebase Terminology & Glossary

This document provides explanations for the key technical terms, external libraries, and domain-specific concepts used throughout the codebase.

## 1. Core Libraries and Frameworks

* **PIL (Pillow) / `PIL.Image`**: Python Imaging Library. The standard library used for opening, manipulating, and saving images. In this codebase, it's frequently used to represent pages of documents before passing them to models.
* **cv2 (OpenCV)**: The Open Source Computer Vision Library. Used extensively for image preprocessing steps such as converting images to grayscale, applying CLAHE, skew correction, and noise reduction. It handles images as NumPy arrays.
* **numpy (`np`)**: A library for working with large, multi-dimensional arrays and matrices. OpenCV uses NumPy arrays to represent images, and it is heavily used for fast mathematical operations on image data.
* **flask**: A lightweight web framework for Python. Used to build the REST API backend, manage routes, and handle incoming HTTP requests (like file uploads).
* **sqlalchemy / flask_sqlalchemy**: An Object-Relational Mapping (ORM) toolkit. Used to interact with the SQL database using Python classes instead of writing raw SQL queries.
* **paddleocr**: An OCR toolkit based on the PaddlePaddle deep learning framework. It is the primary engine used in this project to detect and recognize text and bounding boxes from document images.
* **transformers**: A library by Hugging Face that provides pre-trained models. In this project, it is used to load and run the `LayoutLMv3` model.
* **torch (PyTorch)**: A popular open-source machine learning framework. It serves as the underlying tensor and computation backend required by the `transformers` library and `LayoutLMv3`.
* **fitz (PyMuPDF)**: A high-performance PDF rendering and extraction library. Used to convert uploaded PDF documents into high-resolution images so they can be processed by the OCR pipeline.
* **qdrant_client**: The Python client for Qdrant, a vector database and similarity search engine, likely used for semantic search or retrieving similar documents/embeddings.
* **werkzeug**: A comprehensive WSGI web application library. It provides utilities for Flask, such as safely handling uploaded files and HTTP headers.

## 2. Document AI & Domain-Specific Concepts

* **OCR (Optical Character Recognition)**: The foundational technology used to convert images of typed, handwritten, or printed text into machine-encoded text.
* **LayoutLMv3**: A multimodal Transformer model designed for Document AI. Unlike standard NLP models that only look at text, LayoutLMv3 looks at the text, the layout (bounding boxes), and the image features simultaneously. It is used here to identify structured fields like "Invoice Number" or "Total Amount" from complex document layouts.
* **Bounding Box (bbox)**: A geometric rectangle that encloses a specific piece of text (a word, a line, or a paragraph) detected by the OCR engine. It is usually represented by coordinates `[x_min, y_min, x_max, y_max]` and is crucial for understanding the spatial layout of the document.
* **CLAHE (Contrast Limited Adaptive Histogram Equalization)**: An image processing technique used to improve the contrast in images. It operates on small regions (tiles) of the image rather than the entire image, which prevents the over-amplification of noise. It makes faded text easier for the OCR engine to read.
* **Binarization**: The process of converting a colored or grayscale image into a purely black-and-white (binary) image. This is a common preprocessing step to separate text (foreground) from the paper (background).
* **Grayscale**: Converting an image from RGB (colored) to a single channel representing shades of gray. This simplifies the image data for faster and more accurate processing by OpenCV and OCR engines.
* **Deskew / Skew Correction**: An algorithm to detect if a scanned document is tilted (skewed) and rotate it back to a perfectly straight horizontal alignment. This prevents text lines from bleeding into each other during extraction.
