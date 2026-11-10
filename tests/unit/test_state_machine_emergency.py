import unittest
from server.brain.core.state_machine import StateMachine, State

class TestEmergencyTransitions(unittest.TestCase):
    def test_entry_from_every_state(self):
        states_to_test = [State.IDLE, State.WAITING_CARD, State.INSIDE, State.LOCKED]
        for initial_state in states_to_test:
            sm = StateMachine()
            sm.state = initial_state
            actions = sm.handle_emergency({"type": "EMERGENCY"})
            
            self.assertEqual(sm.state, State.EMERGENCY)
            self.assertTrue(any(a.get("type") == "publish" and a.get("topic") == "glo/alert/units" for a in actions))
            self.assertTrue(any(a.get("type") == "set_fan" and a.get("locked") is True for a in actions))

    def test_fan_commands_refused_in_emergency(self):
        sm = StateMachine()
        sm.state = State.EMERGENCY
        actions = sm.handle_fan_command({"action": "start"})
        self.assertTrue(any("refused" in a.get("msg", "").lower() for a in actions))

if __name__ == '__main__':
    unittest.main()
