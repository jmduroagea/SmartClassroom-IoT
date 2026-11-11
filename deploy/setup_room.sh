#!/usr/bin/env bash
# Setup of the ROOM Pi (Pi 26): DS18B20 temperature sensor, USB microphone, fan.
#
#     ./setup_room.sh SERVER_IP        e.g.  ./setup_room.sh 10.12.220.101
#
# Run once. Stops at the first error. Reboots at the end (1-Wire needs it).
# Safe to run again: finished steps are skipped.
set -eu
export DEBIAN_FRONTEND=noninteractive

# ---- Settings ----------------------------------------------------------------
SERVER_IP="${1:-}"
NEW_HOSTNAME="smartroom-room"
REPO_URL="https://github.com/jmduroagea/SmartClassroom-IoT.git"
REPO_DIR="$HOME/SmartClassroom-IoT"
VENV_DIR="$HOME/smartroom-venv"
BROKER_PORT=1883
BROKER_TEST_SECONDS=5
VOSK_MODEL="vosk-model-small-en-us-0.15"
VOSK_URL="https://alphacephei.com/vosk/models/$VOSK_MODEL.zip"

step() { echo; echo "===== $* ====="; }
trap 'echo; echo "!!!!! FAILED at line $LINENO. Nothing after this point was done."' ERR

if [[ ! "$SERVER_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 SERVER_IP   (the IP of the Server Pi, e.g. 10.12.220.101)"
  exit 2
fi

step "1/7 System packages (git, Python venv, PortAudio for the microphone, MQTT clients, unzip)"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv libportaudio2 mosquitto-clients unzip

step "2/7 Project repository"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" pull --quiet
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi

step "3/7 Python packages, pinned, in $VENV_DIR"
[[ -d "$VENV_DIR" ]] || python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements-room.txt"

step "4/7 1-Wire on GPIO4 for the DS18B20"
sudo raspi-config nonint do_onewire 0

step "5/7 Vosk English model"
if [[ -d "$HOME/$VOSK_MODEL" ]]; then
  echo "already present"
else
  wget -q -O "/tmp/$VOSK_MODEL.zip" "$VOSK_URL"
  unzip -q "/tmp/$VOSK_MODEL.zip" -d "$HOME"
  rm "/tmp/$VOSK_MODEL.zip"
fi

step "6/7 .env"
if [[ -f "$REPO_DIR/.env" ]]; then
  echo ".env already exists, left untouched"
else
  {
    echo "MQTT_HOST=$SERVER_IP"
    echo "MQTT_PORT=$BROKER_PORT"
    echo "VOSK_MODEL_PATH=$HOME/$VOSK_MODEL"
  } > "$REPO_DIR/.env"
  echo ".env created"
fi

step "7/7 Hostname -> $NEW_HOSTNAME (applies after reboot)"
sudo raspi-config nonint do_hostname "$NEW_HOSTNAME"

step "CHECKS"
"$VENV_DIR/bin/python" -c "import paho.mqtt.client, vosk, sounddevice; print('python packages: OK')"
ls -d "$HOME/$VOSK_MODEL"
cat "$REPO_DIR/.env"
if timeout "$BROKER_TEST_SECONDS" mosquitto_pub -h "$SERVER_IP" -p "$BROKER_PORT" -t glo/setup/test -m "room OK"; then
  echo "broker on $SERVER_IP: OK"
else
  echo "!!!!! broker on $SERVER_IP NOT reachable (is the Server Pi set up and on?)"
fi

step "WHAT CHANGED (and how to undo it)"
cat <<EOF
- apt: git python3-venv libportaudio2 mosquitto-clients unzip
      undo: sudo apt-get remove libportaudio2 mosquitto-clients unzip
- Python packages in $VENV_DIR       undo: rm -rf $VENV_DIR
- 1-Wire on                          undo: sudo raspi-config nonint do_onewire 1
- Vosk model in ~/$VOSK_MODEL        undo: rm -r ~/$VOSK_MODEL
- Repository and .env in $REPO_DIR   undo: rm -rf $REPO_DIR
- Hostname $NEW_HOSTNAME             undo: sudo raspi-config nonint do_hostname raspberrypi
After the reboot: ./deploy/run.sh room
EOF

step "Rebooting (the connection will close; that is expected)"
sudo reboot
