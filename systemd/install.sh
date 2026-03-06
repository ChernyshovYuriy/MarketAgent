#!/usr/bin/env bash
# systemd/install.sh
# Installs, enables, and starts the ca-market-agent timer on Ubuntu / Jetson Nano.
# Run as root:  sudo bash systemd/install.sh

set -euo pipefail

SERVICE_NAME="ca-market-agent"
SYSTEMD_DIR="/etc/systemd/system"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Configurable defaults (edit or override via env) ----
PROJECT_DIR="${PROJECT_DIR:-/opt/ca_market_agent}"
RUN_USER="${RUN_USER:-ubuntu}"

# ------------------------------------------------------------------ #
# Helper                                                               #
# ------------------------------------------------------------------ #
log()  { echo "[install] $*"; }
die()  { echo "[error]   $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "This script must be run as root (sudo)."

# ------------------------------------------------------------------ #
# 1. Copy project to /opt if not already there                         #
# ------------------------------------------------------------------ #
if [[ "$SCRIPT_DIR" != "$PROJECT_DIR/systemd" ]]; then
    log "Copying project to $PROJECT_DIR ..."
    mkdir -p "$PROJECT_DIR"
    cp -r "$SCRIPT_DIR/.." "$PROJECT_DIR"
    chown -R "$RUN_USER:$RUN_USER" "$PROJECT_DIR"
else
    log "Project already at $PROJECT_DIR"
fi

# ------------------------------------------------------------------ #
# 2. Create virtualenv and install dependencies (if not present)       #
# ------------------------------------------------------------------ #
VENV="$PROJECT_DIR/venv"
if [[ ! -d "$VENV" ]]; then
    log "Creating virtualenv at $VENV ..."
    sudo -u "$RUN_USER" python3 -m venv "$VENV"
fi

log "Installing Python dependencies ..."
sudo -u "$RUN_USER" "$VENV/bin/pip" install --upgrade pip -q
sudo -u "$RUN_USER" "$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q

# ------------------------------------------------------------------ #
# 3. Seed the ticker database (idempotent — won't overwrite existing)  #
# ------------------------------------------------------------------ #
DBFILE="$PROJECT_DIR/storage/market_agent.db"
if [[ ! -f "$DBFILE" ]]; then
    log "Seeding ticker universe ..."
    sudo -u "$RUN_USER" "$VENV/bin/python" "$PROJECT_DIR/main.py" --seed-tickers
fi

# ------------------------------------------------------------------ #
# 4. Substitute actual paths / user into the unit files                #
# ------------------------------------------------------------------ #
for UNIT in ca-market-agent.service ca-market-agent.timer; do
    SRC="$PROJECT_DIR/systemd/$UNIT"
    DST="$SYSTEMD_DIR/$UNIT"
    log "Installing $UNIT → $DST"
    # Replace placeholder paths and user with real values
    sed \
        -e "s|/opt/ca_market_agent|$PROJECT_DIR|g" \
        -e "s|User=ubuntu|User=$RUN_USER|g" \
        -e "s|Group=ubuntu|Group=$RUN_USER|g" \
        "$SRC" > "$DST"
    chmod 644 "$DST"
done

# ------------------------------------------------------------------ #
# 5. Enable and start the timer (NOT the service directly)             #
# ------------------------------------------------------------------ #
log "Reloading systemd daemon ..."
systemctl daemon-reload

log "Enabling and starting the timer ..."
systemctl enable --now "${SERVICE_NAME}.timer"

# ------------------------------------------------------------------ #
# 6. Status summary                                                    #
# ------------------------------------------------------------------ #
echo ""
echo "=============================="
echo " Installation complete"
echo "=============================="
systemctl status "${SERVICE_NAME}.timer" --no-pager -l
echo ""
echo "Useful commands:"
echo "  Check timer schedule : systemctl list-timers ${SERVICE_NAME}.timer"
echo "  Watch live logs      : journalctl -u ${SERVICE_NAME} -f"
echo "  Run immediately      : systemctl start ${SERVICE_NAME}.service"
echo "  Stop timer           : systemctl disable --now ${SERVICE_NAME}.timer"
echo "  Uninstall            : sudo bash systemd/uninstall.sh"
