"""The Door Pi container: its real code with fake hardware, driven on sim/ topics (#38).

The test acts on the fake card reader and PIR, and checks what the door program
published to the brain and what its fake LEDs and speaker did.
"""

import time

from common import messages, topics
from tests.scenarios import simulation

SIM_CARD = "sim/door/card"
SIM_MOTION = "sim/door/motion"
SIM_LED = "sim/door/led"
SIM_SAID = "sim/door/speaker/said"
PROMPT_TIMEOUT = 8  # the brain asks for a card 3 s after the movement


def test_a_card_on_sim_goes_through_the_real_door_code(sim):
    sim.publish_sim(SIM_CARD, card_id="CARD_GLORIA")
    # The door program read it and published it to the brain, as with the RDM6300
    rfid = sim.wait_for_message(topics.DOOR_RFID)
    assert rfid["card_id"] == "CARD_GLORIA"
    sim.wait_for_status(lambda status: status["inside"] == "Gloria")
    # The brain's orders came back to the door program and reached its fake hardware
    said = sim.wait_for_message(SIM_SAID, lambda m: m["text"].startswith("Welcome, Gloria"))
    assert said["text"].startswith("Welcome, Gloria")
    sim.wait_for_message(SIM_LED, lambda m: m == {"color": "green", "on": True})


def test_the_same_card_read_twice_at_once_is_sent_once(sim):
    sim.publish_sim(SIM_CARD, card_id="CARD_GLORIA")
    sim.publish_sim(SIM_CARD, card_id="CARD_GLORIA")
    sim.wait_for_status(lambda status: status["inside"] == "Gloria")
    time.sleep(simulation.QUIET_TIME)
    assert len(sim.messages_on(topics.DOOR_RFID)) == 1


def test_motion_on_sim_makes_the_brain_ask_for_a_card(sim):
    sim.publish_sim(SIM_MOTION)
    sim.wait_for_message(topics.DOOR_MOTION)
    sim.wait_for_message(SIM_SAID, lambda m: "scan your card" in m["text"].lower(), PROMPT_TIMEOUT)


def test_the_web_shows_the_door_pi_online(sim):
    sim.wait_for_status(lambda status: status["devices"]["door"] == messages.STATUS_ONLINE)


def test_the_door_container_reaches_the_broker_but_not_mongodb(sim):
    # Like the real Door Pi: only on the iot network
    assert simulation.can_connect("door", "broker", 1883)
    assert not simulation.can_connect("door", "mongo", 27017)
