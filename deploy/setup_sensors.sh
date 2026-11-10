#!/usr/bin/env bash
# Setup of the SENSORS Pi (Pi 26): PIR, RFID, LED, speaker, DS18B20, microphone, fan.
# Run once. Stops at the first error. Reboots at the end.
set -eu
export DEBIAN_FRONTEND=noninteractive

# ---- Settings ----------------------------------------------------------------
NEW_HOSTNAME="smartroom-sensors"
BROKER_IP="10.12.220.106"            # the brain Pi (Pi 6)
REPO_URL="https://github.com/jmduroagea/SmartClassroom-IoT.git"
REPO_DIR="$HOME/SmartClassroom-IoT"
VOSK_MODEL="vosk-model-small-en-us-0.15"
VOSK_URL="https://alphacephei.com/vosk/models/$VOSK_MODEL.zip"

step() { echo; echo "===== $* ====="; }
trap 'echo; echo "!!!!! FAILED at line $LINENO. Nothing after this point was done."' ERR

step "1/7 System packages (espeak-ng, PortAudio, MQTT clients, unzip)"
sudo apt-get update -qq
sudo apt-get install -y -qq espeak-ng libportaudio2 mosquitto-clients unzip

step "2/7 Python packages for user $(whoami) only"
pip3 install --user --quiet paho-mqtt vosk sounddevice

step "3/7 UART on for the RFID reader (Linux console off the UART, Bluetooth untouched)"
sudo raspi-config nonint do_serial 2

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

step "6/7 Project repository and .env"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" pull --quiet
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
if [[ -f "$REPO_DIR/.env" ]]; then
  echo ".env already exists, left untouched"
else
  printf "MQTT_HOST=%s\nMQTT_PORT=1883\nVOSK_MODEL=%s\n" "$BROKER_IP" "$HOME/$VOSK_MODEL" > "$REPO_DIR/.env"
  echo ".env created"
fi

step "7/7 Hostname -> $NEW_HOSTNAME (applies after reboot)"
sudo raspi-config nonint do_hostname "$NEW_HOSTNAME"

step "CHECKS"
python3 -c "import paho.mqtt.client, vosk, sounddevice; print('python packages: OK')"
espeak-ng --version
ls -d "$HOME/$VOSK_MODEL"
cat "$REPO_DIR/.env"

step "WHAT CHANGED (and how to undo it)"
cat <<EOF
- apt: espeak-ng libportaudio2 mosquitto-clients unzip
      undo: sudo apt-get remove espeak-ng libportaudio2 mosquitto-clients unzip
- pip (user): paho-mqtt vosk sounddevice
      undo: pip3 uninstall paho-mqtt vosk sounddevice
- UART on, serial console off        undo: sudo raspi-config nonint do_serial 0
- 1-Wire on                          undo: sudo raspi-config nonint do_onewire 1
- Vosk model in ~/$VOSK_MODEL        undo: rm -r ~/$VOSK_MODEL
- Repository in $REPO_DIR            undo: rm -rf $REPO_DIR
- Hostname $NEW_HOSTNAME             undo: sudo raspi-config nonint do_hostname raspberrypi
EOF

step "Rebooting (the connection will close; that is expected)"
sudo reboot
