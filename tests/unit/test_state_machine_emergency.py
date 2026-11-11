import unittest
from server.brain.core.state_machine import StateMachine, State
from common.clock import FakeClock

class TestEmergencyTransitions(unittest.TestCase):
    def setUp(self):
        self.emit = lambda action: None

    def test_entry_from_every_state(self):
        states_to_test = [State.IDLE, State.WAITING_CARD, State.INSIDE, State.LOCKED]
        for initial_state in states_to_test:
            clock = FakeClock()
            sm = StateMachine(clock=clock, emit=self.emit)
            sm.state = initial_state
            actions = sm.handle_emergency({"type": "EMERGENCY"})

            self.assertEqual(sm.state, State.EMERGENCY)
            self.assertTrue(any(a.get("type") == "set_fan" and a.get("locked") is True for a in actions))

    def test_fan_commands_refused_in_emergency(self):
        clock = FakeClock()
        sm = StateMachine(clock=clock, emit=self.emit)
        sm.state = State.EMERGENCY
        actions = sm.handle_fan_command({"action": "start"})
        self.assertEqual(len(actions), 0)
