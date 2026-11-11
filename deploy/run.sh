#!/usr/bin/env bash
# Starts one program of this Pi with the settings of its .env file.
#
#     ./deploy/run.sh door     # on the Door Pi
#     ./deploy/run.sh room     # on the Room Pi
#     ./deploy/run.sh brain    # on the Server Pi (one terminal)
#     ./deploy/run.sh web      # on the Server Pi (another terminal)
#
# Ctrl+C stops it. The programs only read environment variables, so this
# script is what turns .env into variables.
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"
PYTHON="$HOME/smartroom-venv/bin/python"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "No $ENV_FILE: run the setup script of this Pi first."
  exit 1
fi
set -a              # every variable defined from here on is exported
. "$ENV_FILE"
set +a
cd "$REPO_DIR"

case "${1:-}" in
  door)  exec "$PYTHON" door/door.py ;;
  room)  exec "$PYTHON" -m room.main ;;
  brain) exec "$PYTHON" -m server.brain.main ;;
  web)   cd server/web && exec node server.js ;;
  *)     echo "usage: $0 door|room|brain|web"; exit 2 ;;
esac
