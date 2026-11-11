import json
import paho.mqtt.client as mqtt

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TOPIC = "glo/alert/#"

def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[EmergencyCenter] Conectado al broker MQTT (código: {rc})")
    client.subscribe(TOPIC)
    print(f"[EmergencyCenter] Suscrito a {TOPIC}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        payload = msg.payload.decode("utf-8")

    print("\n" + "="*50)
    print(f"🚨 [ALERTA DE EMERGENCIA RECIBIDA]")
    print(f"Tópico : {msg.topic}")
    print(f"Mensaje: {json.dumps(payload, indent=2)}")
    print("="*50 + "\n")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[EmergencyCenter] Conectando a {MQTT_BROKER}:{MQTT_PORT}...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

if __name__ == "__main__":
    main()
