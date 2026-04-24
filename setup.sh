#!/usr/bin/env bash
set -euo pipefail

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[setup]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
error()   { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }
section() { echo -e "\n${CYAN}══ $* ══${NC}"; }

# ── helper ────────────────────────────────────────────────────────────────────
gen_secret() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40 || true; }

# ─────────────────────────────────────────────────────────────────────────────
# 1. Choose run mode
# ─────────────────────────────────────────────────────────────────────────────
section "Run mode"
echo ""
echo "  How do you want to run OCR-Match?"
echo ""
echo "  [1] Docker   — all services in containers (recommended for first run)"
echo "  [2] Local    — Python venv + Node (nvm) directly on your machine"
echo ""
read -rp "  Enter 1 or 2: " RUN_MODE

[[ "$RUN_MODE" == "1" || "$RUN_MODE" == "2" ]] || error "Invalid choice. Enter 1 or 2."

# ─────────────────────────────────────────────────────────────────────────────
# 2. Check shared prerequisites
# ─────────────────────────────────────────────────────────────────────────────
section "Prerequisites"

command -v git >/dev/null 2>&1 || error "Git is not installed."

if [[ "$RUN_MODE" == "1" ]]; then
  command -v docker >/dev/null 2>&1 || error "Docker is not installed. Install it from https://www.docker.com/get-started"
  docker info >/dev/null 2>&1        || error "Docker daemon is not running. Start Docker Desktop and try again."

  if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  else
    error "Docker Compose is not installed. It is bundled with Docker Desktop."
  fi
  info "Docker OK  (compose: $COMPOSE)"
fi

if [[ "$RUN_MODE" == "2" ]]; then
  # ── Python version check ──────────────────────────────────────────────────
  REQUIRED_PY="3.10"
  PY_BIN=""

  for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
      major=${ver%%.*}; minor=${ver##*.}
      if [[ "$major" -eq 3 && "$minor" -ge 10 ]]; then
        PY_BIN="$candidate"
        info "Python found: $PY_BIN ($ver)"
        break
      fi
    fi
  done

  [[ -n "$PY_BIN" ]] || error "Python >= $REQUIRED_PY not found. Install it from https://www.python.org/downloads/"

  # ── Node / nvm check ─────────────────────────────────────────────────────
  NODE_VERSION="18"
  NVM_DIR="${NVM_DIR:-$HOME/.nvm}"

  if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    # shellcheck source=/dev/null
    source "$NVM_DIR/nvm.sh"
    info "nvm found: $(nvm --version)"
    NVM_AVAILABLE=true
  else
    NVM_AVAILABLE=false
    command -v node >/dev/null 2>&1 || error "Node.js is not installed and nvm was not found.\n  Install nvm: https://github.com/nvm-sh/nvm\n  or Node.js: https://nodejs.org"
    info "Node found: $(node --version)  (nvm not detected — skipping version pin)"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. Environment files  (.env per service)
# ─────────────────────────────────────────────────────────────────────────────
section "Environment files"

# ── 3a. Root .env — docker-compose / shared secrets ─────────────────────────
ROOT_ENV=".env"
if [[ ! -f "$ROOT_ENV" ]]; then
  echo ""
  echo "  OCR-Match needs a Groq API key to parse invoices."
  echo "  Get a free key at https://console.groq.com/keys"
  echo ""
  read -rp "  Enter your GROQ_API_KEY: " GROQ_KEY
  [[ -z "$GROQ_KEY" ]] && error "GROQ_API_KEY cannot be empty."

  cp ".env.example" "$ROOT_ENV"
  sed -i.bak "s|^GROQ_API_KEY=.*|GROQ_API_KEY=${GROQ_KEY}|" "$ROOT_ENV" && rm -f "$ROOT_ENV.bak"
  info "Created: $ROOT_ENV  (from .env.example)"
else
  info "$ROOT_ENV already exists — skipping."
  if ! grep -q "GROQ_API_KEY=" "$ROOT_ENV" || grep -q "GROQ_API_KEY=$" "$ROOT_ENV"; then
    warn "GROQ_API_KEY is missing or empty in $ROOT_ENV. Edit it before continuing."
  fi
fi

# ── Extract Groq key from root .env for use in backend/.env ──────────────────
GROQ_KEY_VALUE=$(grep "^GROQ_API_KEY=" "$ROOT_ENV" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "")

# ── 3b. backend/.env — Flask runtime ─────────────────────────────────────────
BACKEND_ENV="backend/.env"
if [[ ! -f "$BACKEND_ENV" ]]; then
  if [[ "$RUN_MODE" == "1" ]]; then
    DB_URI="mysql+mysqlconnector://root:root@mysql:3306/invoice_db"
    QDRANT_HOST_VAL="qdrant"
  else
    DB_URI="mysql+mysqlconnector://root:root@127.0.0.1:3306/invoice_db"
    QDRANT_HOST_VAL="localhost"
  fi

  cp "backend/.env.example" "$BACKEND_ENV"
  SECRET=$(gen_secret)
  sed -i.bak \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" \
    -e "s|^SQLALCHEMY_DATABASE_URI=.*|SQLALCHEMY_DATABASE_URI=${DB_URI}|" \
    -e "s|^GROQ_API_KEY=.*|GROQ_API_KEY=${GROQ_KEY_VALUE}|" \
    -e "s|^QDRANT_HOST=.*|QDRANT_HOST=${QDRANT_HOST_VAL}|" \
    "$BACKEND_ENV" && rm -f "$BACKEND_ENV.bak"
  info "Created: $BACKEND_ENV  (from backend/.env.example)"
else
  info "$BACKEND_ENV already exists — skipping."
  for var in SECRET_KEY SQLALCHEMY_DATABASE_URI GROQ_API_KEY; do
    grep -q "^${var}=" "$BACKEND_ENV" || warn "$var is missing from $BACKEND_ENV — add it manually."
  done
fi

# ── 3c. frontend/.env — React build ──────────────────────────────────────────
FRONTEND_ENV="frontend/.env"
if [[ ! -f "$FRONTEND_ENV" ]]; then
  cp "frontend/.env.example" "$FRONTEND_ENV"
  info "Created: $FRONTEND_ENV  (from frontend/.env.example)"
else
  info "$FRONTEND_ENV already exists — skipping."
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. Language environments  (local mode only)
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$RUN_MODE" == "2" ]]; then
  section "Python virtual environment  (backend)"

  VENV_DIR="backend/venv"
  if [[ -d "$VENV_DIR" ]]; then
    info "Virtual environment already exists at $VENV_DIR — skipping creation."
  else
    info "Creating Python venv with $PY_BIN..."
    "$PY_BIN" -m venv "$VENV_DIR"
    info "Created: $VENV_DIR"
  fi

  info "Installing Python dependencies..."
  "$VENV_DIR/bin/pip" install --upgrade pip -q
  "$VENV_DIR/bin/pip" install -r backend/requirements.txt -q
  info "Python dependencies installed."

  # ── Node environment ────────────────────────────────────────────────────────
  section "Node environment  (frontend)"

  if [[ "$NVM_AVAILABLE" == "true" ]]; then
    if nvm ls "$NODE_VERSION" >/dev/null 2>&1; then
      info "Node $NODE_VERSION already installed via nvm."
    else
      info "Installing Node $NODE_VERSION via nvm..."
      nvm install "$NODE_VERSION"
    fi
    nvm use "$NODE_VERSION"
    info "Active Node: $(node --version)  |  npm: $(npm --version)"
  else
    info "Using system Node: $(node --version)  |  npm: $(npm --version)"
  fi

  info "Installing frontend dependencies..."
  npm install --prefix frontend --silent
  info "npm packages installed."
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. PaddleOCR model weights check
# ─────────────────────────────────────────────────────────────────────────────
section "PaddleOCR model weights"

PADDLE_DIR="backend/paddle_models"
REQUIRED_MODELS=("en_PP-OCRv3_det_infer" "en_PP-OCRv3_rec_infer" "ch_ppocr_mobile_v2.0_cls_infer")
MISSING_MODELS=()

for model in "${REQUIRED_MODELS[@]}"; do
  [[ -d "$PADDLE_DIR/$model" ]] && [[ -n "$(ls -A "$PADDLE_DIR/$model" 2>/dev/null)" ]] || MISSING_MODELS+=("$model")
done

if [[ ${#MISSING_MODELS[@]} -gt 0 ]]; then
  warn "Missing or empty model directories:"
  for m in "${MISSING_MODELS[@]}"; do warn "  $PADDLE_DIR/$m"; done
  warn "If the repo uses Git LFS, run:  git lfs pull"
  warn "OCR will fail without these weights. Continuing anyway..."
else
  info "All PaddleOCR model weights found."
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. Launch
# ─────────────────────────────────────────────────────────────────────────────
section "Launch"

if [[ "$RUN_MODE" == "1" ]]; then
  # ── Docker path ─────────────────────────────────────────────────────────────
  info "Building and starting all Docker services (5–15 min on first run)..."
  $COMPOSE up --build -d

  info "Waiting for MySQL to become healthy..."
  MAX_WAIT=120; ELAPSED=0
  until $COMPOSE ps mysql 2>/dev/null | grep -q "healthy"; do
    sleep 5; ELAPSED=$((ELAPSED + 5)); echo -n "."
    [[ $ELAPSED -ge $MAX_WAIT ]] && { echo ""; warn "MySQL health check timed out. Check: $COMPOSE logs mysql"; break; }
  done
  echo ""

  info "Waiting for backend to respond..."
  ELAPSED=0
  until curl -sf http://localhost:5001/get-invoices >/dev/null 2>&1; do
    sleep 5; ELAPSED=$((ELAPSED + 5)); echo -n "."
    [[ $ELAPSED -ge $MAX_WAIT ]] && { echo ""; warn "Backend timed out. Check: $COMPOSE logs backend"; break; }
  done
  echo ""

  echo ""
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}  OCR-Match is up!  (Docker)${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo -e "  React frontend   →  ${GREEN}http://localhost:3000${NC}"
  echo -e "  Flask API        →  ${GREEN}http://localhost:5001${NC}"
  echo -e "  Qdrant dashboard →  ${GREEN}http://localhost:6333/dashboard${NC}"
  echo -e "  MySQL            →  localhost:3307  (root / root / invoice_db)"
  echo ""
  echo -e "  Stop:       ${YELLOW}$COMPOSE down${NC}"
  echo -e "  Full reset: ${YELLOW}$COMPOSE down -v${NC}"
  echo -e "  Logs:       ${YELLOW}$COMPOSE logs -f${NC}"
  echo ""

else
  # ── Local path ──────────────────────────────────────────────────────────────
  echo ""
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}  Local environment ready!${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo "  To start the backend (terminal 1):"
  echo -e "    ${CYAN}cd backend${NC}"
  echo -e "    ${CYAN}source venv/bin/activate${NC}"
  echo -e "    ${CYAN}python run.py${NC}"
  echo ""
  echo "  To start the frontend (terminal 2):"
  if [[ "$NVM_AVAILABLE" == "true" ]]; then
  echo -e "    ${CYAN}nvm use $NODE_VERSION${NC}"
  fi
  echo -e "    ${CYAN}npm start --prefix frontend${NC}"
  echo ""
  echo "  MySQL and Qdrant must be running before you start the backend."
  echo -e "  Start only those two services with Docker:"
  echo -e "    ${CYAN}docker compose up mysql qdrant -d${NC}"
  echo ""
fi
