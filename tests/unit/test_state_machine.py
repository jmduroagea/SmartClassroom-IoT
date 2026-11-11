import unittest
from common.messages import FAN_SPEEDS
from server.brain.core.state_machine import StateMachine, State

class TestStateMachine(unittest.TestCase):

    def setUp(self):
        self.sm = StateMachine()
        self.speeds = list(FAN_SPEEDS) if not isinstance(FAN_SPEEDS, dict) else list(FAN_SPEEDS.values())

    def test_process_card_scan_grant(self):
        actions = self.sm.process_card_scan("CARD_1", "Gloria")
        self.assertEqual(self.sm.state, State.OCCUPIED)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0], {"type": "say", "text": "Welcome, Gloria!"})

    def test_process_card_scan_deny(self):
        actions = self.sm.process_card_scan("CARD_UNKNOWN", None)
        self.assertEqual(self.sm.state, State.OFF)
        self.assertEqual(actions[0], {"type": "say", "text": "Access denied"})

    # Issue #67 Unit Tests
    def test_voice_hot_from_off_to_middle(self):
        actions = self.sm.process_voice_command("hot")
        mid_speed = self.speeds[len(self.speeds) // 2]
        self.assertEqual(self.sm.fan_speed, mid_speed)
        self.assertEqual(actions, [{"type": "set_fan", "speed": mid_speed}])

    def test_voice_hot_one_level_up(self):
        if len(self.speeds) > 2:
            self.sm.fan_speed = self.speeds[1]
            actions = self.sm.process_voice_command("hot")
            expected_speed = self.speeds[2]
            self.assertEqual(self.sm.fan_speed, expected_speed)
            self.assertEqual(actions[0], {"type": "set_fan", "speed": expected_speed})

    def test_voice_hot_maximum(self):
        self.sm.fan_speed = self.speeds[-1]
        actions = self.sm.process_voice_command("hot")
        self.assertEqual(self.sm.fan_speed, self.speeds[-1])
        self.assertEqual(actions, [{"type": "say", "text": "The fan is at maximum."}])

    def test_voice_cold_one_level_down(self):
        self.sm.fan_speed = self.speeds[-1]
        actions = self.sm.process_voice_command("cold")
        expected_speed = self.speeds[-2]
        self.assertEqual(self.sm.fan_speed, expected_speed)
        self.assertEqual(actions, [{"type": "set_fan", "speed": expected_speed}])

    def test_voice_cold_already_off(self):
        self.sm.fan_speed = 0
        actions = self.sm.process_voice_command("cold")
        self.assertEqual(self.sm.fan_speed, 0)
        self.assertEqual(actions, [{"type": "say", "text": "The fan is already off."}])

    def test_voice_refused_during_emergency(self):
        self.sm.state = State.EMERGENCY
        actions_hot = self.sm.process_voice_command("hot")
        actions_cold = self.sm.process_voice_command("cold")
        self.assertEqual(actions_hot, [])
        self.assertEqual(actions_cold, [])

if __name__ == "__main__":
    unittest.main()
