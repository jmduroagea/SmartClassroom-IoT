import unittest
from server.brain.core.state_machine import StateMachine, State
from common.clock import FakeClock

class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.sm = StateMachine(clock=self.clock)

    def test_valid_entry_and_exit(self):
        self.sm.handle_temperature(0.0, 22.5) # Para que registre la temperatura
        actions = self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.INSIDE)
        self.assertIn({"type": "say", "text": "Welcome, Gloria. The temperature is 22.5 degrees."}, actions)
        self.assertIn({"type": "set_pir", "enabled": False}, actions)
        self.assertIn({"type": "set_mic", "enabled": True}, actions)

        actions = self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.IDLE)
        self.assertIn({"type": "set_fan", "speed": 0}, actions)
        self.assertIn({"type": "set_mic", "enabled": False}, actions)
        self.assertIn({"type": "set_pir", "enabled": True}, actions)

    def test_lock_after_three_failures(self):
        self.sm.handle_card("UNKNOWN1", is_known=False)
        self.sm.handle_card("UNKNOWN2", is_known=False)
        actions = self.sm.handle_card("UNKNOWN3", is_known=False)
        self.assertEqual(self.sm.state, State.LOCKED)
        self.assertTrue(any(a.get("text") == "System locked" for a in actions))

    def test_unlock_from_web(self):
        self.sm.state = State.LOCKED
        actions = self.sm.unlock()
        self.assertEqual(self.sm.state, State.IDLE)
        self.assertEqual(len(actions), 1)

    def test_room_occupied(self):
        self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        actions = self.sm.handle_card("CARD_JOSE", is_known=True, user_name="Jose")
        self.assertEqual(self.sm.state, State.INSIDE)
        self.assertIn({"type": "occupied", "card_id": "CARD_JOSE"}, actions)
        self.assertIn({"type": "say", "text": "Room occupied."}, actions)

    def test_card_while_locked(self):
        self.sm.state = State.LOCKED
        actions = self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.LOCKED)
        self.assertIn({"type": "denied", "card_id": "CARD_GLORIA"}, actions)
        self.assertFalse(any(a.get("type") == "say" for a in actions))

    def test_pir_starts_waiting_card_and_timers(self):
        self.sm.handle_pir()
        self.assertEqual(self.sm.state, State.WAITING_CARD)
        self.assertIsNotNone(self.sm.current_timer)

        # Simulamos que avanza el tiempo para ejecutar el callback en secuencia
        self.clock.advance(3.0)
        # A los 5 segundos desde el prompt...
        self.clock.advance(5.0)
        # A los 30 segundos desde el reminder vuelve a IDLE.
        self.clock.advance(30.0)
        self.assertEqual(self.sm.state, State.IDLE)
