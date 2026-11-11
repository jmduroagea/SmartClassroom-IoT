import unittest
from server.brain.core.state_machine import StateMachine, State
from common.clock import FakeClock

class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.emitted_actions = []
        # Callback function to store actions emitted asynchronously by timers
        self.emit = lambda action: self.emitted_actions.append(action)
        self.sm = StateMachine(clock=self.clock, emit=self.emit)

    def test_valid_entry_and_exit(self):
        # 1. No temperature reading yet (None)
        actions = self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.INSIDE)
        self.assertIn({"type": "say", "text": "Welcome, Gloria."}, actions)
        self.assertIn({"type": "access", "access": "in", "card_id": "CARD_GLORIA", "name": "Gloria"}, actions)

        # 2. Exit
        actions = self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.IDLE)
        self.assertIn({"type": "say", "text": "Goodbye, Gloria."}, actions)
        self.assertIn({"type": "access", "access": "out", "card_id": "CARD_GLORIA", "name": "Gloria"}, actions)

        # 3. With temperature reading (rounded to 1 decimal)
        self.sm.handle_temperature(0.0, 22.56)
        actions = self.sm.handle_card("CARD_JOSE", is_known=True, user_name="Jose")
        self.assertIn({"type": "say", "text": "Welcome, Jose. The temperature is 22.6 degrees."}, actions)

    def test_unknown_card_while_inside_keeps_inside(self):
        self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.INSIDE)

        actions = self.sm.handle_card("UNKNOWN", is_known=False)
        self.assertEqual(self.sm.state, State.INSIDE)  # Room remains occupied by Gloria
        self.assertEqual(self.sm.current_user_card, "CARD_GLORIA")
        self.assertIn({"type": "say", "text": "Card not recognized."}, actions)

    def test_lock_after_three_failures(self):
        self.sm.handle_card("UNKNOWN1", is_known=False)
        self.sm.handle_card("UNKNOWN2", is_known=False)
        actions = self.sm.handle_card("UNKNOWN3", is_known=False)
        self.assertEqual(self.sm.state, State.LOCKED)
        self.assertTrue(any(a.get("text") == "System locked" for a in actions))

    def test_unlock_from_web(self):
        self.sm.state = State.LOCKED
        self.sm.unlock()
        self.assertEqual(self.sm.state, State.IDLE)

    def test_room_occupied(self):
        self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        actions = self.sm.handle_card("CARD_JOSE", is_known=True, user_name="Jose")
        self.assertEqual(self.sm.state, State.INSIDE)
        self.assertIn({"type": "access", "access": "occupied", "card_id": "CARD_JOSE", "name": "Jose"}, actions)
        self.assertIn({"type": "say", "text": "Room occupied."}, actions)

    def test_card_while_locked(self):
        self.sm.state = State.LOCKED
        actions = self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.LOCKED)
        self.assertIn({"type": "access", "access": "denied", "card_id": "CARD_GLORIA", "name": "Gloria"}, actions)
        self.assertFalse(any(a.get("type") == "say" for a in actions))

    def test_pir_starts_waiting_card_and_timers(self):
        self.sm.handle_pir()
        self.assertEqual(self.sm.state, State.WAITING_CARD)

        # Check prompt at 3s
        self.clock.advance(3.0)
        self.assertIn({"type": "say", "text": "scan your card"}, self.emitted_actions)
        self.assertEqual(len(self.emitted_actions), 1)

        # Check reminder at 8s (3 + 5)
        self.clock.advance(5.0)
        self.assertIn({"type": "say", "text": "Reminder: scan your card"}, self.emitted_actions)
        self.assertEqual(len(self.emitted_actions), 2)

        # Timeout back to IDLE
        self.clock.advance(30.0)
        self.assertEqual(self.sm.state, State.IDLE)

    def test_unknown_card_is_logged_without_a_name(self):
        actions = self.sm.handle_card("UNKNOWN", is_known=False)
        self.assertIn({"type": "access", "access": "denied", "card_id": "UNKNOWN", "name": None}, actions)

    def test_locking_and_unlocking_are_system_events(self):
        for attempt in range(StateMachine.MAX_FAILED_ATTEMPTS):
            actions = self.sm.handle_card(f"UNKNOWN{attempt}", is_known=False)
        self.assertIn({"type": "system_event", "event": "locked", "device": "door",
                       "detail": "3 unknown cards"}, actions)
        actions = self.sm.unlock()
        self.assertIn({"type": "system_event", "event": "unlocked", "device": "web", "detail": ""}, actions)

    def test_unlock_when_not_locked_does_nothing(self):
        self.assertEqual(self.sm.unlock(), [])
