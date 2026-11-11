"""Unit tests of the EMERGENCY state (#20): entry from every state, what the
brain does on entry, and what it refuses while the emergency lasts."""

import unittest

from common.clock import FakeClock
from server.brain.core.state_machine import State, StateMachine

GLORIA_CARD = "CARD_GLORIA"
EMERGENCY_ID = "em-20261110T090000"  # FakeClock starts at 2026-11-10 09:00:00 UTC
TEMP = 41.5


def entry_actions(person, temp=TEMP):
    """Everything the brain must do when the emergency is declared (spec v4)."""
    return [
        {"type": "set_fan", "speed": 0},
        {"type": "set_led", "color": "red", "mode": "blink"},
        {"type": "set_alarm", "enabled": True},
        {"type": "set_mic", "enabled": True},
        {"type": "set_pir", "enabled": False},
        {"type": "alert_units", "emergency_id": EMERGENCY_ID, "temp": temp, "person": person},
    ]


class TestEmergency(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.emitted = []
        self.sm = StateMachine(clock=self.clock, emit=self.emitted.append)

    def enter(self):
        self.sm.handle_card(GLORIA_CARD, is_known=True, user_name="Gloria")

    def lock(self):
        for attempt in range(StateMachine.MAX_FAILED_ATTEMPTS):
            self.sm.handle_card(f"UNKNOWN_{attempt}", is_known=False)

    def test_from_idle_nobody_inside(self):
        actions = self.sm.handle_emergency("rate", TEMP)
        self.assertEqual(self.sm.state, State.EMERGENCY)
        self.assertEqual(actions, entry_actions(person=None))

    def test_from_waiting_card_cancels_the_prompt(self):
        self.sm.handle_pir()
        actions = self.sm.handle_emergency("rate", TEMP)
        self.assertEqual(actions, entry_actions(person=None))
        self.clock.advance(60)
        self.assertEqual(self.emitted, [])  # no "scan your card" during the emergency

    def test_from_inside_names_the_person(self):
        self.enter()
        actions = self.sm.handle_emergency("rate", TEMP)
        self.assertEqual(actions, entry_actions(person="Gloria"))

    def test_from_locked(self):  # T21
        self.lock()
        self.assertEqual(self.sm.state, State.LOCKED)
        actions = self.sm.handle_emergency("rate", TEMP)
        self.assertEqual(self.sm.state, State.EMERGENCY)
        self.assertEqual(actions, entry_actions(person=None))

    def test_person_who_left_is_not_named(self):
        self.enter()
        self.enter()  # second scan: Gloria leaves
        actions = self.sm.handle_emergency("rate", TEMP)
        self.assertEqual(actions, entry_actions(person=None))

    def test_simulated_without_a_reading(self):
        actions = self.sm.handle_emergency("simulated")
        self.assertEqual(actions, entry_actions(person=None, temp=None))
        self.assertEqual(self.sm.emergency_trigger, "simulated")

    def test_second_emergency_is_ignored(self):
        self.sm.handle_emergency("rate", TEMP)
        self.clock.advance(5)
        self.assertEqual(self.sm.handle_emergency("simulated"), [])
        self.assertEqual(self.sm.emergency_id, EMERGENCY_ID)

    def test_unknown_trigger_is_refused(self):
        with self.assertRaises(ValueError):
            self.sm.handle_emergency("smoke", TEMP)
        self.assertEqual(self.sm.state, State.IDLE)

    def test_fan_is_refused_from_web_and_voice(self):  # T19
        self.enter()
        self.sm.handle_emergency("rate", TEMP)
        self.assertEqual(self.sm.handle_web_fan(2), [])
        self.assertEqual(self.sm.handle_fan_command({"speed": 2}), [])
        self.assertEqual(self.sm.handle_voice_command("hot"), [])
