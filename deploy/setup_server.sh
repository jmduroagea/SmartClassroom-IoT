#!/usr/bin/env bash
# Setup of the SERVER Pi (Pi 1): Mosquitto broker, brain (Python) and web (Node.js).
#
#     ./setup_server.sh
#
# Run once on a clean image. It asks for the web password, stops at the first
# error and reboots at the end. Safe to run again: finished steps are skipped.
set -eu
export DEBIAN_FRONTEND=noninteractive

# ---- Settings ----------------------------------------------------------------
NEW_HOSTNAME="smartroom-server"
REPO_URL="https://github.com/jmduroagea/SmartClassroom-IoT.git"
REPO_DIR="$HOME/SmartClassroom-IoT"
VENV_DIR="$HOME/smartroom-venv"
MOSQUITTO_CONF_SRC="$REPO_DIR/server/mosquitto/smartroom.conf"
MOSQUITTO_CONF_DST="/etc/mosquitto/conf.d/smartroom.conf"
BROKER_PORT=1883
MONGO_URI="mongodb://etu-web2.ut-capitole.fr:27017"   # no credentials needed (teacher)
MONGO_DB="smartroom"
MONGO_TIMEOUT_MS=5000
NODE_VERSION="v20.20.2"                 # official build that runs on this Pi
NODE_DIST="node-$NODE_VERSION-linux-armv7l"
NODE_URL="https://nodejs.org/dist/$NODE_VERSION"

step() { echo; echo "===== $* ====="; }
trap 'echo; echo "!!!!! FAILED at line $LINENO. Nothing after this point was done."' ERR

# Asked first, so the rest runs without anyone watching. Never shown or saved
# anywhere except this Pi's .env.
if [[ ! -f "$REPO_DIR/.env" ]]; then
  read -r -s -p "Web password (for the emergency buttons): " WEB_PASSWORD; echo
  read -r -s -p "Same password again: " WEB_PASSWORD_AGAIN; echo
  if [[ -z "$WEB_PASSWORD" || "$WEB_PASSWORD" != "$WEB_PASSWORD_AGAIN" ]]; then
    echo "The passwords are empty or different. Nothing was done."
    exit 1
  fi
fi

step "1/8 System packages (git, Python venv, Mosquitto, tmux)"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv mosquitto mosquitto-clients tmux

step "2/8 Project repository"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" pull --quiet
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi

step "3/8 Mosquitto broker, open to the network"
sudo cp "$MOSQUITTO_CONF_SRC" "$MOSQUITTO_CONF_DST"
sudo systemctl enable --quiet mosquitto
sudo systemctl restart mosquitto

step "4/8 Node.js $NODE_VERSION (official build, checksum verified)"
if [[ "$(node --version 2>/dev/null || true)" == "$NODE_VERSION" ]]; then
  echo "already installed"
else
  cd /tmp
  wget -q "$NODE_URL/$NODE_DIST.tar.xz" "$NODE_URL/SHASUMS256.txt"
  grep " $NODE_DIST.tar.xz\$" SHASUMS256.txt | sha256sum -c -
  sudo tar -xJf "$NODE_DIST.tar.xz" -C /usr/local --strip-components=1 \
       "$NODE_DIST/bin" "$NODE_DIST/lib" "$NODE_DIST/include" "$NODE_DIST/share"
  rm "$NODE_DIST.tar.xz" SHASUMS256.txt
  cd - >/dev/null
fi

step "5/8 Python packages, pinned, in $VENV_DIR"
[[ -d "$VENV_DIR" ]] || python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements-brain.txt"

step "6/8 Web dependencies, exact versions from the lock file (a few minutes on a Pi 3)"
(cd "$REPO_DIR/server/web" && npm ci --omit=dev --no-audit --no-fund --loglevel=error)

step "7/8 .env"
if [[ -f "$REPO_DIR/.env" ]]; then
  echo ".env already exists, left untouched"
else
  {
    echo "MQTT_HOST=localhost"
    echo "MQTT_PORT=$BROKER_PORT"
    echo "MONGO_URI=$MONGO_URI"
    echo "MONGO_DB=$MONGO_DB"
    printf "WEB_PASSWORD=%q\n" "$WEB_PASSWORD"    # quoted, so any character is safe
  } > "$REPO_DIR/.env"
  chmod 600 "$REPO_DIR/.env"                     # only this user can read the password
  echo ".env created"
fi

step "8/8 Hostname -> $NEW_HOSTNAME (applies after reboot)"
sudo raspi-config nonint do_hostname "$NEW_HOSTNAME"

step "CHECKS"
echo "node $(node --version), npm $(npm --version)"
"$VENV_DIR/bin/python" -c "import paho.mqtt.client, pymongo; print('python packages: OK')"
systemctl is-active mosquitto
mosquitto_sub -h localhost -t glo/setup/test -C 1 -W 5 & sleep 1
mosquitto_pub -h localhost -t glo/setup/test -m "broker OK"
wait || echo "!!!!! broker test FAILED: the message did not come back"
"$VENV_DIR/bin/python" -c "
from pymongo import MongoClient
MongoClient('$MONGO_URI', serverSelectionTimeoutMS=$MONGO_TIMEOUT_MS).admin.command('ping')
print('MongoDB on etu-web2: OK')" || echo "!!!!! MongoDB on etu-web2 NOT reachable"
grep -v "^WEB_PASSWORD" "$REPO_DIR/.env"

step "WHAT CHANGED (and how to undo it)"
cat <<EOF
- apt: git python3-venv mosquitto mosquitto-clients tmux
      undo: sudo apt-get remove mosquitto mosquitto-clients tmux
- Broker config $MOSQUITTO_CONF_DST  undo: sudo rm $MOSQUITTO_CONF_DST
- Node.js in /usr/local              undo: sudo rm -rf /usr/local/bin/{node,npm,npx,corepack} /usr/local/lib/node_modules /usr/local/include/node
- Python packages in $VENV_DIR       undo: rm -rf $VENV_DIR
- Repository and .env in $REPO_DIR   undo: rm -rf $REPO_DIR
- Hostname $NEW_HOSTNAME             undo: sudo raspi-config nonint do_hostname raspberrypi
After the reboot: ./deploy/start_server.sh   (brain, web and emergency centre)
EOF

step "Rebooting (the connection will close; that is expected)"
sudo reboot
