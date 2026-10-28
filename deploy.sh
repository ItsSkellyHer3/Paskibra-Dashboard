#!/usr/bin/env bash
set -Eeuo pipefail

# ============================================================================
# Paskibra V2 — one-command deployment
# Usage: ./deploy.sh [user@server] [local-project-directory]
# The remote application directory is always ~/paskibra_v2.
# ============================================================================

TARGET_HOST="${1:-adhyastha@server.tailb096be.ts.net}"
INPUT_DIR="${2:-$(dirname -- "${BASH_SOURCE[0]}")}"
LOCAL_DIR="$(cd -- "$INPUT_DIR" && pwd)"
REMOTE_DIR="paskibra_v2"
CONTROL_SOCKET="${TMPDIR:-/tmp}/ssh_deploy_${USER:-user}_$$"
SSH_OPTS=(
    -o ControlMaster=auto
    -o "ControlPath=${CONTROL_SOCKET}"
    -o ControlPersist=120s
    -o ConnectTimeout=10
)

cleanup() {
    ssh -O exit -o "ControlPath=${CONTROL_SOCKET}" "$TARGET_HOST" >/dev/null 2>&1 || true
    rm -f -- "$CONTROL_SOCKET" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if ! command -v ssh >/dev/null 2>&1; then
    echo "ERROR: ssh is required to deploy this project." >&2
    exit 1
fi

echo "=========================================================="
echo "  Paskibra V2 deployment"
echo "  Target: ${TARGET_HOST}"
echo "  Remote directory: ~/${REMOTE_DIR}"
echo "=========================================================="

echo
echo "[1/5] Connecting to ${TARGET_HOST}..."
if ! ssh "${SSH_OPTS[@]}" "$TARGET_HOST" "echo '  SSH connection established.'"; then
    echo "ERROR: Could not connect to ${TARGET_HOST} via SSH." >&2
    echo "Check the hostname, network connection, and SSH credentials." >&2
    exit 1
fi

echo
echo "[2/5] Backing up the current server folder..."
ssh "${SSH_OPTS[@]}" "$TARGET_HOST" 'bash -s' <<'REMOTE_BACKUP'
set -euo pipefail
REMOTE_DIR="$HOME/paskibra_v2"
if [ -d "$REMOTE_DIR" ] && [ -n "$(ls -A "$REMOTE_DIR" 2>/dev/null)" ]; then
    BACKUP="$HOME/paskibra_v2-backup-$(date +%Y%m%d_%H%M%S)"
    echo "  Saving current files to $BACKUP"
    cp -a "$REMOTE_DIR" "$BACKUP"
else
    echo "  No existing application files to back up."
fi
mkdir -p "$REMOTE_DIR"

SERVICE_BACKUP_TIME="$(date +%Y%m%d_%H%M%S)"
for SERVICE_FILE in /etc/systemd/system/paskibra-v2.service /etc/systemd/system/paskibra_v2.service; do
    if [ -r "$SERVICE_FILE" ]; then
        cp "$SERVICE_FILE" "$HOME/paskibra-v2-service-backup-${SERVICE_BACKUP_TIME}.service"
        echo "  Saved existing service unit to $HOME/paskibra-v2-service-backup-${SERVICE_BACKUP_TIME}.service"
    fi
done
REMOTE_BACKUP

echo
echo "[3/5] Uploading application files..."
if command -v rsync >/dev/null 2>&1; then
    rsync -rltz --no-owner --no-group --no-perms --info=progress2 \
        -e "ssh -S ${CONTROL_SOCKET} -o ControlPersist=120s -o ConnectTimeout=10" \
        --exclude='.git/' \
        --exclude='.venv/' \
        --exclude='venv/' \
        --exclude='vrnv/' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='.env' \
        --exclude='.env.*' \
        --exclude='paskibra_v2.db*' \
        --exclude='instance/vapid_private.pem' \
        --exclude='static/uploads/' \
        --exclude='static/uploads/.optimized/' \
        "${LOCAL_DIR}/" "${TARGET_HOST}:${REMOTE_DIR}/"
else
    echo "  rsync is unavailable; sending a filtered archive instead."
    tar -C "$LOCAL_DIR" -czf - \
        --exclude='./.git' \
        --exclude='./.venv' \
        --exclude='./venv' \
        --exclude='./vrnv' \
        --exclude='./__pycache__' \
        --exclude='*.pyc' \
        --exclude='./.env' \
        --exclude='./.env.*' \
        --exclude='./paskibra_v2.db*' \
        --exclude='./instance/vapid_private.pem' \
        --exclude='./static/uploads' \
        . | ssh "${SSH_OPTS[@]}" "$TARGET_HOST" \
        "mkdir -p '${REMOTE_DIR}' && tar -xzf - -C '${REMOTE_DIR}'"
fi

echo
echo "[4/5] Setting up the remote launcher and restarting the service if present..."
ssh -tt "${SSH_OPTS[@]}" "$TARGET_HOST" \
    "cd ~/paskibra_v2 && chmod +x run.sh && \
     if [ -f paskibra-v2.service ]; then \
         echo '  Installing and restarting paskibra-v2.service...' && \
         sudo install -m 644 paskibra-v2.service /etc/systemd/system/paskibra-v2.service && \
         sudo systemctl daemon-reload && \
         sudo systemctl enable paskibra-v2.service && \
         sudo systemctl restart paskibra-v2.service; \
     elif [ -f /etc/systemd/system/paskibra-v2.service ] || [ -f /usr/lib/systemd/system/paskibra-v2.service ] || [ -f /lib/systemd/system/paskibra-v2.service ]; then \
         echo '  Restarting paskibra-v2.service...' && sudo systemctl daemon-reload && sudo systemctl restart paskibra-v2.service; \
     elif [ -f /etc/systemd/system/paskibra_v2.service ] || [ -f /usr/lib/systemd/system/paskibra_v2.service ] || [ -f /lib/systemd/system/paskibra_v2.service ]; then \
         echo '  Restarting paskibra_v2.service...' && sudo systemctl daemon-reload && sudo systemctl restart paskibra_v2.service; \
     else \
         echo '  No Paskibra systemd service is installed; files are deployed.'; \
     fi"

echo
echo "[5/5] Checking remote status..."
ssh "${SSH_OPTS[@]}" "$TARGET_HOST" 'bash -s' <<'REMOTE_STATUS'
set -euo pipefail
attempt=0
until python3 -c 'from urllib.request import urlopen; response = urlopen("http://127.0.0.1:5000/auth/login", timeout=2); response.close()' >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
        echo "  ERROR: Paskibra did not answer on port 5000 within 120 seconds."
        systemctl status paskibra-v2.service --no-pager -l 2>/dev/null || systemctl status paskibra_v2.service --no-pager -l 2>/dev/null || true
        exit 1
    fi
    sleep 2
done
echo "  Paskibra is responding on port 5000."
if systemctl is-active --quiet paskibra-v2.service 2>/dev/null; then
    echo "  paskibra-v2.service is active."
elif systemctl is-active --quiet paskibra_v2.service 2>/dev/null; then
    echo "  paskibra_v2.service is active."
else
    echo "  No active Paskibra service was found."
    echo "  To start manually: cd ~/paskibra_v2 && ./run.sh"
fi
REMOTE_STATUS

echo
echo "=========================================================="
echo "  Deployment files synchronized to ~/${REMOTE_DIR}."
echo "  Server database, uploads, and VAPID key were preserved."
echo "=========================================================="
