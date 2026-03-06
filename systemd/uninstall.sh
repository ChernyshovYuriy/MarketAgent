#!/usr/bin/env bash
# systemd/uninstall.sh
# Stops and removes the ca-market-agent systemd units.
# Run as root:  sudo bash systemd/uninstall.sh

set -euo pipefail

SERVICE_NAME="ca-market-agent"
SYSTEMD_DIR="/etc/systemd/system"

[[ $EUID -eq 0 ]] || { echo "Run as root (sudo)." >&2; exit 1; }

for UNIT in "${SERVICE_NAME}.timer" "${SERVICE_NAME}.service"; do
    if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
        echo "Stopping $UNIT ..."
        systemctl stop "$UNIT"
    fi
    if systemctl is-enabled --quiet "$UNIT" 2>/dev/null; then
        echo "Disabling $UNIT ..."
        systemctl disable "$UNIT"
    fi
    TARGET="$SYSTEMD_DIR/$UNIT"
    if [[ -f "$TARGET" ]]; then
        echo "Removing $TARGET ..."
        rm "$TARGET"
    fi
done

systemctl daemon-reload
echo "Done. Unit files removed."
