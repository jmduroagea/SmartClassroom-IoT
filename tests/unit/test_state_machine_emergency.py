import unittest
from server.brain.core.state_machine import StateMachine, State
from common.clock import FakeClock

class TestEmergencyTransitions(unittest.TestCase):
    def test_entry_from_every_state(self):
        states_to_test = [State.IDLE, State.WAITING_CARD, State.INSIDE, State.LOCKED]
        for initial_state in states_to_test:
            clock = FakeClock()
            sm = StateMachine(clock=clock)
            sm.state = initial_state
            actions = sm.handle_emergency({"type": "EMERGENCY"})

            self.assertEqual(sm.state, State.EMERGENCY)
            self.assertTrue(any(a.get("type") == "set_fan" and a.get("locked") is True for a in actions))
            self.assertTrue(any(a.get("type") == "set_led" and a.get("color") == "red" and a.get("mode") == "blink" for a in actions))
            self.assertTrue(any(a.get("type") == "set_mic" and a.get("enabled") is True for a in actions))
            self.assertTrue(any(a.get("type") == "set_pir" and a.get("enabled") is False for a in actions))

    def test_fan_commands_refused_in_emergency(self):
        clock = FakeClock()
        sm = StateMachine(clock=clock)
        sm.state = State.EMERGENCY
        actions = sm.handle_fan_command({"action": "start"})
        self.assertEqual(len(actions), 0)
