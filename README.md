<p align="center"><img src="./images/OCR-logo.png" alt="Logo" width="100"></p>
<h1 align="center">Invoice OCR App</h1>

Web application for recognizing and managing data from invoices using Optical Character Recognition (OCR).

## 🌟 Features
* Recognize and extract information from invoices in image or PDF format
* User registration and administrative authentication configurations
* Choose between automated preprocessing choices and dedicated OCR pipelines (Tesseract & PaddleOCR)
* Automatically extract vital info: VAT number, IBAN, SWIFT, amounts, etc.
* Save, manage, search, and filter identified invoices through your database
* Organization support for shared invoice scopes among multi-tenant users

## 🏗️ Tech Stack
- **Backend Server**: Python, Flask
- **Frontend UI**: React.js
- **CV & OCR Engines**: OpenCV, Tesseract OCR, PaddleOCR
- **Database**: PostgreSQL 15
- **Infrastructure**: Docker & Docker Compose

---

## 🚀 Installation & Real Setup Steps

Follow these tested steps to get the application spun up locally. The entire application is containerized, so you won't need to manually configure Python or Node environments.

### Prerequisites
- **Docker** and **Docker Compose** installed and actively running on your machine.

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/khuswant18/ocr-match.git
   cd ocr-match
   ```

2. **Build and start the application via Docker**
   The application services (Postgres, Python Backend, React Frontend) are ready to be built.
   ```bash
   docker-compose up --build -d
   ```
   *(Note: This might take a few minutes the first time to download base images like `postgres:15`, `node`, and Python dependencies).*

3. **Verify the services**
   Make sure all containers booted up successfully:
   ```bash
   docker-compose ps
   ```
   You should see `frontend`, `backend`, and `postgres` marked as `Up`.

4. **Access the application**
   Once everything is running, open your web browser and navigate to:
   [http://localhost:3000](http://localhost:3000)

5. **Login via Admin Access**
   The backend initialization script will automatically seed an administrator user the very first time it creates the database relations. Use the following default credentials to securely log across your app:
   - **Email**: `admin`
   - **Password**: `admin`

---

## 🛑 Troubleshooting

* **PostgreSQL startup loops or crashes**: 
  If you altered the Postgres database version or encounter dirty local volume states, perform a clean volume wipe and restart by running:
  ```bash
  docker-compose down -v && docker-compose up --build -d
  ```

* **Backend dependencies failing to build**: 
  The `backend/Dockerfile` has been modernized to run on `python:3.10-slim-bullseye`. If you run into PaddlePaddle or package mismatches in the future, check `backend/requirements.txt` to ensure package version mappings correctly align with your CPU architecture (`aarch64` / `arm64` typically for Macs/M1).

