import unittest
from server.brain.core.state_machine import StateMachine, State

class FakeClock:
    def __init__(self):
        self.events = []
    def schedule(self, delay, event_name):
        self.events.append((delay, event_name))

class TestStateMachine(unittest.TestCase):
    def test_valid_entry_and_exit(self):
        sm = StateMachine()
        actions = sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(sm.state, State.INSIDE)
        self.assertIn({"type": "say", "text": "Welcome, Gloria"}, actions)
        self.assertIn({"event_type": "in", "card_id": "CARD_GLORIA"}, actions)

        actions = sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(sm.state, State.IDLE)
        self.assertIn({"type": "say", "text": "Goodbye, Gloria"}, actions)
        self.assertIn({"event_type": "out", "card_id": "CARD_GLORIA"}, actions)

    def test_lock_after_three_failures(self):
        sm = StateMachine()
        sm.handle_card("UNKNOWN1", is_known=False)
        sm.handle_card("UNKNOWN2", is_known=False)
        actions = sm.handle_card("UNKNOWN3", is_known=False)
        self.assertEqual(sm.state, State.LOCKED)
        self.assertTrue(any(a.get("text") == "System locked" for a in actions))

    def test_unlock_from_web(self):
        sm = StateMachine()
        sm.state = State.LOCKED
        actions = sm.unlock()
        self.assertEqual(sm.state, State.IDLE)
        self.assertEqual(len(actions), 1)

    def test_room_occupied(self):
        sm = StateMachine()
        sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        actions = sm.handle_card("CARD_JOSE", is_known=True, user_name="Jose")
        self.assertEqual(sm.state, State.INSIDE)
        self.assertTrue(any("Access denied (OCCUPIED)" in a.get("msg", "") for a in actions))

    def test_card_while_locked(self):
        sm = StateMachine()
        sm.state = State.LOCKED
        actions = sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(sm.state, State.LOCKED)
        self.assertTrue(any("Access denied (LOCKED)" in a.get("msg", "") for a in actions))
        self.assertFalse(any(a.get("type") == "say" for a in actions))
        self.assertTrue(any(a.get("type") == "set_led" and a.get("mode") == "pulse" and a.get("color") == "red" for a in actions))

    def test_pir_starts_waiting_card_and_timers(self):
        clock = FakeClock()
        sm = StateMachine(clock=clock)
        sm.handle_pir()
        self.assertEqual(sm.state, State.WAITING_CARD)
        self.assertEqual(len(clock.events), 3)
        self.assertIn((3.0, "prompt_card"), clock.events)
        self.assertIn((5.0, "remind_card"), clock.events)
        self.assertIn((30.0, "timeout_idle"), clock.events)

    def test_timer_events(self):
        sm = StateMachine()
        sm.state = State.WAITING_CARD

        actions = sm.handle_timer_event("prompt_card")
        self.assertIn({"type": "say", "text": "Please scan your card"}, actions)

        actions = sm.handle_timer_event("remind_card")
        self.assertIn({"type": "say", "text": "Reminder: please scan your card"}, actions)

        actions = sm.handle_timer_event("timeout_idle")
        self.assertEqual(sm.state, State.IDLE)
        self.assertTrue(any(a.get("type") == "set_led" and a.get("mode") == "off" for a in actions))
