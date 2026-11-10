"""MQTT topic names. This is the only place where they are written.

Every program imports them from here (for example topics.DOOR_RFID) instead of
writing the text by hand, so a typo becomes a Python error instead of a lost message.
"""

PREFIX = "glo"

# Door Pi -> brain
DOOR_MOTION = f"{PREFIX}/door/motion"
DOOR_RFID = f"{PREFIX}/door/rfid"

# Brain -> Door Pi
DOOR_SPEAKER_SAY = f"{PREFIX}/door/speaker/say"
DOOR_PIR_ENABLE = f"{PREFIX}/door/pir/enable"
DOOR_LED_CMD = f"{PREFIX}/door/led/cmd"

# Room Pi -> brain
ROOM_ENV = f"{PREFIX}/room/env"
ROOM_VOICE = f"{PREFIX}/room/voice"
ROOM_FAN_STATE = f"{PREFIX}/room/fan/state"

# Brain -> Room Pi
ROOM_MIC_ENABLE = f"{PREFIX}/room/mic/enable"
ROOM_FAN_CMD = f"{PREFIX}/room/fan/cmd"

# Web server (Express) -> brain
WEB_CMD = f"{PREFIX}/web/cmd"

# Brain -> emergency centre
ALERT_UNITS = f"{PREFIX}/alert/units"
ALERT_CALL = f"{PREFIX}/alert/call"
ALERT_ALL = f"{PREFIX}/alert/#"  # the emergency centre subscribes to every alert

# Each Pi -> everyone (plain text "online"/"offline", retained, last will)
DOOR_STATUS = f"{PREFIX}/door/status"
ROOM_STATUS = f"{PREFIX}/room/status"
