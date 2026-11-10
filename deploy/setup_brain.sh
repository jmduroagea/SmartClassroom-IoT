#!/usr/bin/env bash
# Setup of the BRAIN Pi (Pi 6): Mosquitto broker, brain (Python) and web (Node.js).
# Run once. Stops at the first error. Reboots at the end.
set -eu
export DEBIAN_FRONTEND=noninteractive

# ---- Settings ----------------------------------------------------------------
NEW_HOSTNAME="smartroom-brain"
REPO_URL="https://github.com/jmduroagea/SmartClassroom-IoT.git"
REPO_DIR="$HOME/SmartClassroom-IoT"
MOSQUITTO_CONF_SRC="$REPO_DIR/server/mosquitto/smartroom.conf"
MOSQUITTO_CONF_DST="/etc/mosquitto/conf.d/smartroom.conf"
BROKER_PORT=1883
NODE_VERSION="v20.20.2"                 # official build available for this Pi (pi_info.sh)
NODE_DIST="node-$NODE_VERSION-linux-armv7l"
NODE_URL="https://nodejs.org/dist/$NODE_VERSION"

step() { echo; echo "===== $* ====="; }
trap 'echo; echo "!!!!! FAILED at line $LINENO. Nothing after this point was done."' ERR

step "1/7 Project repository"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" pull --quiet
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi

step "2/7 Mosquitto broker"
sudo apt-get update -qq
sudo apt-get install -y -qq mosquitto mosquitto-clients
sudo cp "$MOSQUITTO_CONF_SRC" "$MOSQUITTO_CONF_DST"
sudo systemctl enable --quiet mosquitto
sudo systemctl restart mosquitto

step "3/7 Node.js $NODE_VERSION (official build, checksum verified)"
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

step "4/7 Python packages for user $(whoami) only"
pip3 install --user --quiet paho-mqtt pymongo

step "5/7 Web dependencies (npm install, can take a few minutes on a Pi 3)"
(cd "$REPO_DIR/server/web" && npm install --omit=dev --no-audit --no-fund --loglevel=error)

step "6/7 .env"
if [[ -f "$REPO_DIR/.env" ]]; then
  echo ".env already exists, left untouched"
else
  cat > "$REPO_DIR/.env" <<EOF
MQTT_HOST=localhost
MQTT_PORT=$BROKER_PORT
# Fill in with the etu-web2 credentials (never commit this file):
# MONGO_URI=mongodb://USER:PASSWORD@etu-web2.ut-capitole.fr:27017/DATABASE
EOF
  echo ".env created (MONGO_URI still to be filled in)"
fi

step "7/7 Hostname -> $NEW_HOSTNAME (applies after reboot)"
sudo raspi-config nonint do_hostname "$NEW_HOSTNAME"

step "CHECKS"
echo "node $(node --version), npm $(npm --version)"
python3 -c "import paho.mqtt.client, pymongo; print('python packages: OK')"
systemctl is-active mosquitto
ss -ltn | grep ":$BROKER_PORT " && echo "broker listening on all interfaces"
mosquitto_sub -h localhost -t glo/setup/test -C 1 -W 5 & sleep 1
mosquitto_pub -h localhost -t glo/setup/test -m "broker OK"
wait || echo "!!!!! broker test FAILED: the message did not come back"

step "WHAT CHANGED (and how to undo it)"
cat <<EOF
- apt: mosquitto mosquitto-clients   undo: sudo apt-get remove mosquitto mosquitto-clients
- Broker config $MOSQUITTO_CONF_DST  undo: sudo rm $MOSQUITTO_CONF_DST
- Node.js in /usr/local              undo: sudo rm -rf /usr/local/bin/{node,npm,npx,corepack} /usr/local/lib/node_modules /usr/local/include/node
- pip (user): paho-mqtt pymongo      undo: pip3 uninstall paho-mqtt pymongo
- Repository in $REPO_DIR            undo: rm -rf $REPO_DIR
- Hostname $NEW_HOSTNAME             undo: sudo raspi-config nonint do_hostname raspberrypi
EOF

step "Rebooting (the connection will close; that is expected)"
sudo reboot
