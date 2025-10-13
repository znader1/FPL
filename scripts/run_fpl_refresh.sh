#!/usr/bin/env bash
set -euo pipefail

# --- CONFIG: set these to your actual paths ---
REPO_DIR="$HOME/path/to/your/FPL"                 # <- change me
VENV_DIR="$REPO_DIR/.venv"                        # <- change if different
PY="$VENV_DIR/bin/python"                         # or: /usr/bin/python3
LOG_DIR="$REPO_DIR/logs"
SSL_CERT_FILE_PATH="$($PY -c 'import certifi; print(certifi.where())' 2>/dev/null || echo "")"
# ----------------------------------------------

mkdir -p "$LOG_DIR"
cd "$REPO_DIR"

# Minimal environment because cron is very bare
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PYTHONPATH="$REPO_DIR"
# If you needed certs for requests (your earlier SSL issue), this helps:
if [ -n "$SSL_CERT_FILE_PATH" ]; then
  export SSL_CERT_FILE="$SSL_CERT_FILE_PATH"
  export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE_PATH"
fi

# Activate venv if it exists
if [ -d "$VENV_DIR" ]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

# Timestamped log
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
echo "[$STAMP] Starting FPL refresh..." >> "$LOG_DIR/fpl_refresh.log" 2>&1

# Run your snapshot script
$PY src/fpl_refresh_next_gw.py >> "$LOG_DIR/fpl_refresh.log" 2>&1

STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
echo "[$STAMP] Finished FPL refresh." >> "$LOG_DIR/fpl_refresh.log" 2>&1
