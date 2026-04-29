#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
#  Recon-Raven Installer for DragonOS / Ubuntu 22.04+
# ─────────────────────────────────────────────────────────────

RAVEN_DIR="${RAVEN_DIR:-$(cd "$(dirname "$0")" && pwd)}"
DATA_DIR="${RAVEN_DATA:-/var/lib/recon-raven}"
SERVICE_USER="${USER}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[*]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fail()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }

echo ""
echo "  🦅  Recon-Raven Installer"
echo "  ─────────────────────────"
echo ""

# ── Check prerequisites ─────────────────────────────────────

info "Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || fail "python3 not found — install Python 3.11+"
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Python: $PYVER"

command -v gpsd >/dev/null 2>&1    && ok "gpsd found"      || warn "gpsd not found — GPS features will be disabled"
command -v rtl_433 >/dev/null 2>&1 && ok "rtl_433 found"   || warn "rtl_433 not found — baseline captures will fail"
command -v rtl_power >/dev/null 2>&1 && ok "rtl_power found" || warn "rtl_power not found — signal alerter will fail"

# Check GNU Radio
python3 -c "import gnuradio" 2>/dev/null && ok "GNU Radio found" || warn "GNU Radio not found — engine scripts will fail"

# ── Create venv ──────────────────────────────────────────────

info "Setting up Python virtual environment..."

if [ ! -d "$RAVEN_DIR/venv" ]; then
    python3 -m venv "$RAVEN_DIR/venv"
    ok "Created venv at $RAVEN_DIR/venv"
else
    ok "Venv already exists"
fi

source "$RAVEN_DIR/venv/bin/activate"

info "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r "$RAVEN_DIR/requirements.txt"
ok "Dependencies installed"

# ── Configuration ────────────────────────────────────────────

if [ ! -f "$RAVEN_DIR/config.yml" ]; then
    cp "$RAVEN_DIR/config.example.yml" "$RAVEN_DIR/config.yml"
    ok "Created config.yml from example — edit as needed"
else
    ok "config.yml already exists"
fi

# ── Data directories ─────────────────────────────────────────

info "Creating data directories at $DATA_DIR..."
sudo mkdir -p "$DATA_DIR"/{captures,logs,baselines,reports}
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
ok "Data directories ready"

# ── Systemd service (optional) ───────────────────────────────

read -rp "$(echo -e "${CYAN}[?]${NC} Install systemd service? [y/N] ")" INSTALL_SERVICE

if [[ "${INSTALL_SERVICE,,}" == "y" ]]; then
    SERVICE_FILE="/etc/systemd/system/recon-raven.service"

    sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Recon-Raven SIGINT Platform
After=network.target gpsd.service
Wants=gpsd.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$RAVEN_DIR
ExecStart=$RAVEN_DIR/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable recon-raven
    ok "Systemd service installed and enabled"
    info "Start with: sudo systemctl start recon-raven"
else
    info "Skipped systemd install"
fi

# ── Done ─────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}  ✓  Recon-Raven installation complete${NC}"
echo ""
echo "  Quick start:"
echo "    cd $RAVEN_DIR"
echo "    source venv/bin/activate"
echo "    uvicorn backend.main:app --host 0.0.0.0 --port 8080"
echo ""
echo "  Dashboard: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo -e "${YELLOW}  ⚠  TX features are DISABLED by default. See LEGAL.md.${NC}"
echo ""
