from common.messages import FAN_SPEEDS
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

    def test_unknown_card_while_inside_says_room_occupied(self):
        self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.assertEqual(self.sm.state, State.INSIDE)

        actions = self.sm.handle_card("UNKNOWN", is_known=False)
        self.assertEqual(self.sm.state, State.INSIDE)  # Room remains occupied by Gloria
        self.assertEqual(self.sm.current_user_card, "CARD_GLORIA")
        self.assertEqual(actions, [
            {"type": "set_led", "color": "red", "mode": "pulse"},
            {"type": "access", "access": "occupied", "card_id": "UNKNOWN", "name": None},
            {"type": "say", "text": "Room occupied."},
        ])

    def test_unknown_cards_while_inside_never_lock_the_door(self):
        self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        for attempt in range(self.sm.MAX_FAILED_ATTEMPTS + 1):
            self.sm.handle_card(f"UNKNOWN{attempt}", is_known=False)
        self.assertEqual(self.sm.state, State.INSIDE)
        self.assertEqual(self.sm.failed_attempts, 0)

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
        for attempt in range(StateMachine.MAX_FAILED_ATTEMPTS - 1):
            actions = self.sm.handle_card(f"UNKNOWN{attempt}", is_known=False)
            self.assertFalse(any(a["type"] == "system_event" for a in actions))
        actions = self.sm.handle_card("UNKNOWN_LAST", is_known=False)
        self.assertIn({"type": "system_event", "event": "locked", "device": "door",
                       "detail": "3 unknown cards"}, actions)
        actions = self.sm.unlock()
        self.assertIn({"type": "system_event", "event": "unlocked", "device": "web", "detail": ""}, actions)

    def test_unlock_when_not_locked_does_nothing(self):
        self.assertEqual(self.sm.unlock(), [])

    def test_fan_initialization(self):
        sm = StateMachine(clock=self.clock, emit=self.emit)
        self.assertEqual(sm.fan_speed, 0)

    def test_fan_speed_sync_web_and_voice(self):
        self.sm.state = State.INSIDE
        self.sm.handle_web_fan(FAN_SPEEDS[3])
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[3])
        actions = self.sm.handle_voice_command("cold")
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[2])
        self.assertEqual(actions, [{"type": "set_fan", "speed": FAN_SPEEDS[2]}])

    def test_voice_hot_from_off_starts_at_middle(self):
        self.sm.state = State.INSIDE
        self.sm.fan_speed = 0
        actions = self.sm.handle_voice_command("hot")
        mid_speed = FAN_SPEEDS[len(FAN_SPEEDS) // 2]
        self.assertEqual(self.sm.fan_speed, mid_speed)
        self.assertEqual(actions, [{"type": "set_fan", "speed": mid_speed}])

    def test_voice_hot_one_level_up(self):
        self.sm.state = State.INSIDE
        self.sm.fan_speed = FAN_SPEEDS[1]
        actions = self.sm.handle_voice_command("hot")
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[2])
        self.assertEqual(actions[0], {"type": "set_fan", "speed": FAN_SPEEDS[2]})

    def test_voice_hot_at_maximum(self):
        self.sm.state = State.INSIDE
        self.sm.fan_speed = FAN_SPEEDS[-1]
        actions = self.sm.handle_voice_command("hot")
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[-1])
        self.assertEqual(actions, [{"type": "say", "text": "The fan is at maximum."}])

    def test_voice_cold_one_level_down(self):
        self.sm.state = State.INSIDE
        self.sm.fan_speed = FAN_SPEEDS[2]
        actions = self.sm.handle_voice_command("cold")
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[1])
        self.assertEqual(actions, [{"type": "set_fan", "speed": FAN_SPEEDS[1]}])

    def test_voice_cold_already_off(self):
        self.sm.state = State.INSIDE
        self.sm.fan_speed = 0
        actions = self.sm.handle_voice_command("cold")
        self.assertEqual(self.sm.fan_speed, 0)
        self.assertEqual(actions, [{"type": "say", "text": "The fan is already off."}])

    def test_voice_off_stops_the_fan_from_any_speed(self):
        self.sm.state = State.INSIDE
        self.sm.fan_speed = FAN_SPEEDS[2]
        actions = self.sm.handle_voice_command("off")
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[0])
        self.assertEqual(actions, [{"type": "set_fan", "speed": FAN_SPEEDS[0]}])

    def test_voice_off_when_already_off(self):
        self.sm.state = State.INSIDE
        self.sm.fan_speed = FAN_SPEEDS[0]
        actions = self.sm.handle_voice_command("off")
        self.assertEqual(actions, [{"type": "say", "text": "The fan is already off."}])

    def test_voice_off_is_ignored_when_nobody_is_inside(self):
        self.sm.state = State.IDLE
        self.sm.fan_speed = FAN_SPEEDS[2]
        self.assertEqual(self.sm.handle_voice_command("off"), [])
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[2])

    def test_voice_temp_says_the_last_reading(self):
        self.sm.state = State.INSIDE
        self.sm.last_known_temp = 21.46
        actions = self.sm.handle_voice_command("temp")
        self.assertEqual(actions, [{"type": "say", "text": "The temperature is 21.5 degrees."}])

    def test_voice_temp_says_a_whole_number_without_decimals(self):
        self.sm.state = State.INSIDE
        self.sm.last_known_temp = 25.0
        actions = self.sm.handle_voice_command("temp")
        self.assertEqual(actions, [{"type": "say", "text": "The temperature is 25 degrees."}])

    def test_voice_temp_before_any_reading(self):
        self.sm.state = State.INSIDE
        actions = self.sm.handle_voice_command("temp")
        self.assertEqual(actions, [{"type": "say", "text": "The temperature is not available yet."}])

    def test_voice_temp_does_not_touch_the_fan(self):
        self.sm.state = State.INSIDE
        self.sm.fan_speed = FAN_SPEEDS[2]
        self.sm.last_known_temp = 21.0
        self.sm.handle_voice_command("temp")
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[2])

    def test_voice_temp_is_ignored_outside_inside(self):
        self.sm.last_known_temp = 21.0
        for state in (State.IDLE, State.WAITING_CARD, State.LOCKED, State.EMERGENCY):
            with self.subTest(state=state):
                self.sm.state = state
                self.assertEqual(self.sm.handle_voice_command("temp"), [])

    def test_voice_refused_during_emergency(self):
        self.sm.state = State.EMERGENCY
        actions = self.sm.handle_voice_command("hot")
        self.assertEqual(actions, [])

    def test_fan_speed_not_reset_by_unknown_card(self):
        self.sm.state = State.INSIDE
        self.sm.handle_web_fan(FAN_SPEEDS[-1])
        self.sm.handle_card("UNKNOWN", is_known=False)
        actions = self.sm.handle_voice_command("hot")
        self.assertEqual(self.sm.fan_speed, FAN_SPEEDS[-1])
        self.assertEqual(actions, [{"type": "say", "text": "The fan is at maximum."}])

    # --- Forced exit from the web (#35) -------------------------------------

    def test_forced_exit_empties_the_room(self):
        self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.sm.handle_web_fan(2)
        actions = self.sm.force_exit()
        self.assertEqual(actions, [
            {"type": "access", "access": "forced_exit", "card_id": "CARD_GLORIA", "name": "Gloria"},
            {"type": "set_fan", "speed": 0},
            {"type": "set_mic", "enabled": False},
            {"type": "set_pir", "enabled": True},
        ])
        self.assertEqual(self.sm.state, State.IDLE)
        self.assertEqual(self.sm.fan_speed, 0)
        self.assertIsNone(self.sm.current_user_card)

    def test_after_a_forced_exit_someone_else_can_enter(self):
        self.sm.handle_card("CARD_GLORIA", is_known=True, user_name="Gloria")
        self.sm.force_exit()
        actions = self.sm.handle_card("CARD_JOSE", is_known=True, user_name="Jose")
        self.assertEqual(self.sm.state, State.INSIDE)
        self.assertIn({"type": "access", "access": "in", "card_id": "CARD_JOSE", "name": "Jose"}, actions)

    def test_forced_exit_with_nobody_inside_does_nothing(self):
        for state in (State.IDLE, State.WAITING_CARD, State.LOCKED, State.EMERGENCY):
            with self.subTest(state=state):
                self.sm.state = state
                self.assertEqual(self.sm.force_exit(), [])
                self.assertEqual(self.sm.state, state)
