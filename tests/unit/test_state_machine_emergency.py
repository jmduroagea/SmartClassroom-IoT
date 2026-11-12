"""Unit tests of the EMERGENCY state (#20): entry from every state, what the
brain does on entry, and what it refuses while the emergency lasts."""

import unittest

from common.clock import FakeClock
from server.brain.core.state_machine import State, StateMachine

GLORIA_CARD = "CARD_GLORIA"
EMERGENCY_ID = "em-20261110T090000"  # FakeClock starts at 2026-11-10 09:00:00 UTC
TEMP = 41.5


def entry_actions(person, temp=TEMP, trigger="rate"):
    """Everything the brain must do when the emergency is declared (spec v4)."""
    record_person = {"card_id": GLORIA_CARD, "name": person} if person else None
    return [
        {
            "type": "open_emergency_record", "emergency_id": EMERGENCY_ID,
            "trigger": trigger, "trigger_temp": temp, "person": record_person,
        },
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
        self.assertEqual(actions, entry_actions(person=None, temp=None, trigger="simulated"))
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

    # --- Readings during the emergency (#23) ---

    def test_every_reading_during_the_emergency_goes_to_the_record(self):
        self.sm.handle_emergency("rate", TEMP)
        for second in (2.0, 4.0):
            actions = self.sm.handle_temperature(second, 42.0)
            self.assertIn({"type": "emergency_reading", "emergency_id": EMERGENCY_ID, "value": 42.0}, actions)

    def test_env_keeps_one_reading_every_10_seconds_during_the_emergency(self):
        self.sm.handle_emergency("rate", TEMP)
        saved = []
        for second in range(100, 130, 2):
            actions = self.sm.handle_temperature(float(second), 42.0)
            saved += [a for a in actions if a["type"] == "save_temperature"]
        self.assertEqual(len(saved), 3)  # at 100, 110 and 120 s

    def test_no_emergency_readings_outside_an_emergency(self):
        actions = self.sm.handle_temperature(100.0, 22.0)
        self.assertEqual([a["type"] for a in actions], ["save_temperature"])

    # --- End of the emergency (#22) ---

    def end_actions(self, person_inside):
        actions = [
            {"type": "set_alarm", "enabled": False},
            {"type": "set_led", "color": "red", "mode": "off"},
            {"type": "set_fan", "speed": 0},
            {"type": "set_mic", "enabled": False},
            {"type": "set_pir", "enabled": True},
        ]
        if person_inside:
            actions.append({"type": "access", "access": "emergency_end", "card_id": GLORIA_CARD, "name": "Gloria"})
        actions.append({"type": "close_emergency_record", "emergency_id": EMERGENCY_ID})
        actions.append({"type": "reset_detector"})
        return actions

    def test_end_with_nobody_inside(self):
        self.sm.handle_emergency("simulated")
        self.assertEqual(self.sm.end_emergency(), self.end_actions(person_inside=False))
        self.assertEqual(self.sm.state, State.IDLE)

    def test_end_without_evacuation_logs_an_emergency_end_exit(self):  # T25
        self.enter()
        self.sm.handle_emergency("rate", TEMP)
        self.assertEqual(self.sm.end_emergency(), self.end_actions(person_inside=True))
        self.assertEqual(self.sm.state, State.IDLE)
        self.assertIsNone(self.sm.current_user_card)

    def test_after_the_end_the_person_must_scan_again_to_enter(self):  # T25
        self.enter()
        self.sm.handle_emergency("rate", TEMP)
        self.sm.end_emergency()
        actions = self.sm.handle_card(GLORIA_CARD, is_known=True, user_name="Gloria")
        self.assertIn({"type": "access", "access": "in", "card_id": GLORIA_CARD, "name": "Gloria"}, actions)
        self.assertEqual(self.sm.state, State.INSIDE)

    def test_an_emergency_that_started_locked_ends_in_idle(self):  # T21
        self.lock()
        self.sm.handle_emergency("rate", TEMP)
        actions = self.sm.end_emergency()
        unlocked = {"type": "system_event", "event": "unlocked", "device": "brain", "detail": "emergency ended"}
        self.assertIn(unlocked, actions)  # so the web stops showing "locked"
        self.assertEqual(self.sm.state, State.IDLE)
        self.assertEqual(self.sm.failed_attempts, 0)
        actions = self.sm.handle_card(GLORIA_CARD, is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.INSIDE)
        self.assertNotIn({"type": "set_led", "color": "red", "mode": "pulse"}, actions)

    def test_an_emergency_from_idle_does_not_write_unlocked(self):
        self.sm.handle_emergency("rate", TEMP)
        actions = self.sm.end_emergency()
        self.assertFalse(any(a.get("event") == "unlocked" for a in actions))

    def test_unlocked_is_written_only_for_the_emergency_that_lifted_the_lock(self):
        self.lock()
        self.sm.handle_emergency("rate", TEMP)
        self.sm.end_emergency()
        self.sm.handle_emergency("simulated")  # this one starts in IDLE
        actions = self.sm.end_emergency()
        self.assertFalse(any(a.get("event") == "unlocked" for a in actions))

    def test_end_outside_an_emergency_does_nothing(self):
        self.assertEqual(self.sm.end_emergency(), [])
        self.enter()
        self.assertEqual(self.sm.end_emergency(), [])
        self.assertEqual(self.sm.state, State.INSIDE)

    def test_fan_works_again_after_the_end(self):
        self.enter()
        self.sm.handle_emergency("rate", TEMP)
        self.sm.end_emergency()
        self.assertEqual(self.sm.handle_web_fan(2), [{"type": "set_fan", "speed": 2}])

    def test_a_new_emergency_after_the_end_gets_a_new_id(self):
        self.sm.handle_emergency("simulated")
        self.sm.end_emergency()
        self.clock.advance(120)
        actions = self.sm.handle_emergency("simulated")
        self.assertEqual(actions[0]["emergency_id"], "em-20261110T090200")
