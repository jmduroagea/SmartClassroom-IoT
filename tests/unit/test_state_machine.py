import unittest
from server.brain.core.state_machine import StateMachine, State

class TestStateMachine(unittest.TestCase):
    def test_valid_entry_and_exit(self):
        sm = StateMachine()
        actions = sm.process_card_scan("CARD_GLORIA", "Gloria")
        self.assertEqual(sm.state, State.INSIDE)
        self.assertEqual(actions[0], {"type": "say", "text": "Welcome, Gloria"})
        self.assertEqual(actions[1]["event_type"], "in")

        actions = sm.process_card_scan("CARD_GLORIA", "Gloria")
        self.assertEqual(sm.state, State.IDLE)
        self.assertEqual(actions[0], {"type": "say", "text": "Goodbye, Gloria"})
        self.assertEqual(actions[1]["event_type"], "out")

    def test_lock_after_three_failures(self):
        sm = StateMachine()
        sm.process_card_scan("UNKNOWN", None)
        sm.process_card_scan("UNKNOWN", None)
        actions = sm.process_card_scan("UNKNOWN", None)
        self.assertEqual(sm.state, State.LOCKED)
        self.assertTrue(any(a.get("text") == "System locked" for a in actions))

    def test_unlock_from_web(self):
        sm = StateMachine()
        sm.state = State.LOCKED
        actions = sm.unlock()
        self.assertEqual(sm.state, State.IDLE)
        self.assertEqual(len(actions), 1)

if __name__ == '__main__':
    unittest.main()
