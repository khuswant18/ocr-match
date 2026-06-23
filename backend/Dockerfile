FROM python:3.10-slim-bullseye

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV KMP_DUPLICATE_LIB_OK True
ENV OMP_NUM_THREADS 1
ENV OPENBLAS_NUM_THREADS 1
ENV MKL_NUM_THREADS 1
ENV VECLIB_MAXIMUM_THREADS 1
ENV NUMEXPR_NUM_THREADS 1

# PaddleOCR model cache — pointed at a persistent volume mount
ENV PADDLEOCR_HOME /root/.paddleocr

RUN apt-get update && apt-get install -y \
    python3-opencv \
    gcc \
    g++ \
    libmupdf-dev

RUN apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
COPY ./requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

# Pre-download the fastembed model so it's baked into the image (~130MB ONNX, no PyTorch/CUDA)
# This works fine at build time because it's pure Python/ONNX — no inference engine crash.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

# NOTE: PaddleOCR model pre-download is intentionally skipped here.
# PaddlePaddle's inference engine segfaults when initialised in a Docker
# build layer on ARM64 (Apple Silicon). Models download automatically on
# first request at runtime and are cached in the paddle_models volume.

COPY . /app

CMD ["python", "run.py"]
