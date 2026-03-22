## 🚀 Installation & Real Setup Steps

Follow these tested steps to get the application spun up locally. The entire application is containerized, so you won't need to manually configure Python, Node, MySQL, or Postgres environments cleanly on your host.                                                                 

### Prerequisites
- **Docker** and **Docker Compose** installed and actively running on your machine.                                                                             

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/khuswant18/ocr-match.git
   cd ocr-match
   ```

2. **Build and start the application via Docker**
   The application services (Postgres, MySQL, Python Backend, React Frontend) are containerized to instantly spin up.                                                                      
   ```bash
   docker-compose up --build -d
   ```
   *(Note: This might take a few minutes the first time to download base images like `postgres:15`, `mysql:8.0`, `node`, and Python dependencies).*

3. **Verify the services**
   Make sure all containers booted up successfully:
   ```bash
   docker-compose ps
   ```
   You should see `frontend`, `backend`, `postgres`, and `mysql` marked as `Up`.

4. **Access the application**
   Once everything is running, open your web browser and navigate to:
   [http://localhost:3000](http://localhost:3000)

5. **Login via Admin Access**
   The backend initialization script will automatically seed an administrator user the very first time it creates the database relations in PostgreSQL. Use the following default credentials to securely log across your app:                                   
   - **Email**: `admin`
   - **Password**: `admin`

---

## 🛑 Troubleshooting

* **PostgreSQL / MySQL startup loops or crashes**: 
  If you altered the Postgres database version or encounter dirty local volume states, perform a clean volume wipe and restart by running:                        
  ```bash
  docker-compose down -v && docker-compose up --build -d
  ```

* **Backend dependencies failing to build**: 
  The `backend/Dockerfile` has been modernized to run on `python:3.10-slim-bullseye`. If you run into PaddlePaddle or package mismatches in the future, check `backend/requirements.txt` to ensure package version mappings correctly align with your CPU architecture (`aarch64` / `arm64` typically for Macs/M1).