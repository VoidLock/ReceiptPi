#!/usr/bin/env bash
set -euo pipefail

# Installs the receipt-printer systemd service.
# Usage: sudo ./scripts/install_service.sh [install-dir] [user]
# - install-dir: path to this repo (default: parent dir of this script)
# - user: system user to run the service as (default: SUDO_USER or current user)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${1:-$(cd "$SCRIPT_DIR/.." && pwd)}"
USER_TO_RUN="${2:-${SUDO_USER:-$(whoami)}}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"

SERVICE_NAME="receipt-printer.service"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"
ENV_PATH="/etc/default/receipt-printer"
TEMPLATE_PATH="${REPO_DIR}/deploy/receipt-printer.service.template"

if [ ! -f "$TEMPLATE_PATH" ]; then
  echo "Template not found: $TEMPLATE_PATH" >&2
  exit 1
fi

# Create environment file
sudo tee "$ENV_PATH" > /dev/null <<EOF
# Environment for receipt-printer service
NTFY_HOST=${NTFY_HOST:-https://ntfy.giffnet.com}
NTFY_TOPIC=${NTFY_TOPIC:-RecieptPi_Print}
PRINTER_VENDOR=${PRINTER_VENDOR:-0x0fe6}
PRINTER_PRODUCT=${PRINTER_PRODUCT:-0x811e}
MEM_THRESHOLD_PERCENT=${MEM_THRESHOLD_PERCENT:-80}
MEM_RESUME_PERCENT=${MEM_RESUME_PERCENT:-70}
# You can add other env vars here if needed
EOF

# Render unit file from template
UNIT_CONTENT=$(sed \
  -e "s|%USER%|${USER_TO_RUN}|g" \
  -e "s|%WORKDIR%|${REPO_DIR}|g" \
  -e "s|%PYTHON%|${PYTHON_BIN}|g" \
  "$TEMPLATE_PATH")

echo "Installing systemd unit to $UNIT_PATH"
echo "$UNIT_CONTENT" | sudo tee "$UNIT_PATH" > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo "Service installed and started. Check status with:"
echo "  sudo systemctl status $SERVICE_NAME"
