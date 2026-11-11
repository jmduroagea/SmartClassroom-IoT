#!/usr/bin/env bash
# Setup of the DOOR Pi (Pi 6): PIR, RFID reader on the UART, LEDs, USB speaker.
#
#     ./setup_door.sh SERVER_IP        e.g.  ./setup_door.sh 10.12.220.101
#
# Run once. Stops at the first error. Reboots at the end (the UART needs it).
# Safe to run again: finished steps are skipped.
set -eu
export DEBIAN_FRONTEND=noninteractive

# ---- Settings ----------------------------------------------------------------
SERVER_IP="${1:-}"
NEW_HOSTNAME="smartroom-door"
REPO_URL="https://github.com/jmduroagea/SmartClassroom-IoT.git"
REPO_DIR="$HOME/SmartClassroom-IoT"
VENV_DIR="$HOME/smartroom-venv"
BROKER_PORT=1883
BROKER_TEST_SECONDS=5
RFID_SERIAL_PORT="/dev/serial0"

step() { echo; echo "===== $* ====="; }
trap 'echo; echo "!!!!! FAILED at line $LINENO. Nothing after this point was done."' ERR

if [[ ! "$SERVER_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 SERVER_IP   (the IP of the Server Pi, e.g. 10.12.220.101)"
  exit 2
fi

step "1/7 System packages (git, Python venv, espeak-ng, MQTT clients)"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv espeak-ng mosquitto-clients

step "2/7 No broker on this Pi (only the Server Pi runs one)"
# This Pi may have been a broker before: two brokers on the network would let
# a program connect to the wrong one.
if systemctl is-enabled --quiet mosquitto 2>/dev/null || systemctl is-active --quiet mosquitto 2>/dev/null; then
  sudo systemctl disable --now --quiet mosquitto
  echo "local Mosquitto stopped and disabled"
else
  echo "no local Mosquitto"
fi

step "3/7 Project repository"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" pull --quiet
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi

step "4/7 Python packages, pinned, in $VENV_DIR"
[[ -d "$VENV_DIR" ]] || python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements-door.txt"

step "5/7 UART on for the RFID reader (Linux console off the UART, Bluetooth untouched)"
sudo raspi-config nonint do_serial 2

step "6/7 .env"
if [[ -f "$REPO_DIR/.env" ]]; then
  echo ".env already exists, left untouched"
else
  {
    echo "MQTT_HOST=$SERVER_IP"
    echo "MQTT_PORT=$BROKER_PORT"
    echo "RFID_SERIAL_PORT=$RFID_SERIAL_PORT"
  } > "$REPO_DIR/.env"
  echo ".env created"
fi

step "7/7 Hostname -> $NEW_HOSTNAME (applies after reboot)"
sudo raspi-config nonint do_hostname "$NEW_HOSTNAME"

step "CHECKS"
"$VENV_DIR/bin/python" -c "import paho.mqtt.client, serial, RPi.GPIO; print('python packages: OK')"
espeak-ng --version
cat "$REPO_DIR/.env"
if timeout "$BROKER_TEST_SECONDS" mosquitto_pub -h "$SERVER_IP" -p "$BROKER_PORT" -t glo/setup/test -m "door OK"; then
  echo "broker on $SERVER_IP: OK"
else
  echo "!!!!! broker on $SERVER_IP NOT reachable (is the Server Pi set up and on?)"
fi

step "WHAT CHANGED (and how to undo it)"
cat <<EOF
- apt: git python3-venv espeak-ng mosquitto-clients
      undo: sudo apt-get remove espeak-ng mosquitto-clients
- Local Mosquitto disabled (if any)  undo: sudo systemctl enable --now mosquitto
- Python packages in $VENV_DIR       undo: rm -rf $VENV_DIR
- UART on, serial console off        undo: sudo raspi-config nonint do_serial 0
- Repository and .env in $REPO_DIR   undo: rm -rf $REPO_DIR
- Hostname $NEW_HOSTNAME             undo: sudo raspi-config nonint do_hostname raspberrypi
After the reboot: ./deploy/run.sh door
EOF

step "Rebooting (the connection will close; that is expected)"
sudo reboot
