#!/usr/bin/env bash
# install.sh — deploy GroupMe Exporter to the host
#
# Usage:
#   sudo bash scripts/install.sh [/path/to/env/file]
#
# Reads GROUPME_INSTALL_DIR from the env file (default: /opt/groupme).
# All other secrets stay in the env file and never touch this script.

set -euo pipefail

ENV_FILE="${1:-/etc/groupme.env}"

# ── Validate env file ─────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found."
    echo "Copy .env.example to $ENV_FILE and fill in your values, then re-run."
    exit 1
fi

# Extract GROUPME_INSTALL_DIR, defaulting to /opt/groupme if not set
GROUPME_INSTALL_DIR=$(grep -E '^GROUPME_INSTALL_DIR=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' || true)
GROUPME_INSTALL_DIR="${GROUPME_INSTALL_DIR:-/opt/groupme}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Installing from: $REPO_ROOT"
echo "==> Installing to:   $GROUPME_INSTALL_DIR"

# ── Create directories ────────────────────────────────────────────────────────
mkdir -p "$GROUPME_INSTALL_DIR/tmp"

# ── Copy application files ────────────────────────────────────────────────────
echo "==> Copying source files..."
cp "$REPO_ROOT"/src/*.py       "$GROUPME_INSTALL_DIR/"
cp "$REPO_ROOT"/schema/*.sql   "$GROUPME_INSTALL_DIR/"
cp "$REPO_ROOT"/scripts/snapshot.sh "$GROUPME_INSTALL_DIR/"
chmod +x "$GROUPME_INSTALL_DIR/snapshot.sh"

# ── Python venv ───────────────────────────────────────────────────────────────
if [[ ! -d "$GROUPME_INSTALL_DIR/venv" ]]; then
    echo "==> Creating Python venv..."
    python3 -m venv "$GROUPME_INSTALL_DIR/venv"
fi
echo "==> Installing Python dependencies..."
"$GROUPME_INSTALL_DIR/venv/bin/pip" install -q -r "$REPO_ROOT/requirements.txt"

# ── Generate and install systemd service ──────────────────────────────────────
TEMPLATE="$REPO_ROOT/systemd/groupme-daemon.service"
SERVICE_DEST="/etc/systemd/system/groupme-daemon.service"

echo "==> Generating $SERVICE_DEST..."
sed "s|%%INSTALL_DIR%%|$GROUPME_INSTALL_DIR|g" "$TEMPLATE" > "$SERVICE_DEST"

systemctl daemon-reload
systemctl enable groupme-daemon
systemctl restart groupme-daemon

echo ""
echo "==> Done. Service status:"
systemctl status groupme-daemon --no-pager -l
