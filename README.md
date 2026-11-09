# SmartClassroom IoT

IoT project week, Université Toulouse Capitole. Team: Ignacio, José María, Gloria.
Teachers: Laurent Marsan and Benoît Gaudou.

A connected classroom with two use cases:

1. **Access control and voice assistant.** A PIR sensor detects someone at the door, they scan
   their RFID card, the speaker welcomes them and says the temperature, and they control a fan
   by voice ("I'm hot", "I'm cold", "What's the temperature?", "Help") or from the web app.
   Three unknown cards in a row lock the system until it is unlocked from the web.
2. **Thermal emergency and evacuation.** A fast temperature rise (≥ 5 °C in 30 s) triggers an
   emergency from any state: the fan stops and is locked, the door LED blinks, the speaker
   repeats an evacuation message, the emergency units are notified, and the web shows who was
   inside and whether they left. All emergency calls are simulated.

The full functional specification (scenarios, state machine, MongoDB schema, web API and the
list of robustness tests T1 to T26) is in `docs/`. This README explains **how the system is
built and how we work**. Read it entirely before writing code.

---

## Architecture

| Machine | Program | Role |
|---|---|---|
| Door Pi | `door/` | PIR, RFID reader (UART), USB speaker, door LED |
| Room Pi | `room/` | DS18B20 temperature probe (every 2 s), USB microphone (Vosk), FS90R fan |
| Server Pi | Mosquitto | MQTT broker |
| Server Pi | `server/brain/` | State machine, emergency detection, the only writer to MongoDB |
| Server Pi | `server/web/` | Express API + AngularJS web app (port 3001) |
| etu-web2 (laptop as fallback) | MongoDB | Database `smartroom` |
| Laptop | `emergency_center/` | Simulated emergency centre, subscribes to `glo/alert/#` |

Architecture rules (agreed with the teachers, never break them):

- **The device Pis only talk to the broker.** They publish what they measure and obey orders.
  They never decide anything.
- **The web never talks to the Pis.** Every command goes to `glo/web/cmd` and the brain decides.
- **Only the brain writes to MongoDB.** Express may read MongoDB directly (accepted by
  Mr Gaudou, provided the architecture is shown in a diagram).
- **Everything works offline.** Speech-to-text (Vosk) and text-to-speech (pico2wave) run
  locally; no external services.
- **The broker runs on the Server Pi**, not on a laptop. A laptop broker is only used for
  development.

---

## MQTT contract

All topics start with `glo/`. Payloads are UTF-8 JSON (except status messages). `ts` is an
ISO 8601 timestamp. A program that receives a message that does not follow the contract
discards it and logs it.

The contract is defined in **one place**: `common/topics.py` and `common/messages.py`. No topic
name or payload field is written by hand anywhere else.

---

## Design decisions

### Hexagonal architecture (ports and adapters) for the Python programs

We do not know yet exactly how every device behaves on the real Pis (RFID frame, Vosk speed on
a Pi 3, servo calibration, audio). The uncertainty is at the **edges**, so we isolate the edges:

- **Core**: the logic of each program. It imports no hardware library, no `paho`, no `pymongo`.
- **Ports**: Python `Protocol` classes describing what the core needs (`CardReader`,
  `MotionSensor`, `Speaker`, `DoorLight`, `TemperatureSensor`, `SpeechRecognizer`, `Fan`,
  `MessageBus`, `Repository`, `Clock`).
- **Adapters**: one file per device and technology, implementing a port. Each real adapter has
  a fake twin used by the tests and the simulation.
- **`main.py`**: the only place that chooses the adapters (real or simulated) and wires them to
  the core, with plain constructors (no dependency injection framework).

If a device works differently than expected, **only its adapter changes**.

The web server (Express + AngularJS) is **not** hexagonal: it is thin (routes that read MongoDB
and publish commands), and a layered structure is enough.

### Code organisation

Each program lives in its own folder (`door/`, `room/`, `server/brain/`, `server/web/`,
`emergency_center/`), and no device imports code from another. Inside each one, every
functionality has its own module: the core, the ports, one adapter per device, and `main.py`.
The only shared code is `common/` (MQTT contract, configuration, clock), which is copied to
each Pi.

### Constants and configuration

- **No magic numbers.** Every timing, threshold, pin, speed level and duty cycle has a name.
- Values that change between environments (broker host, MongoDB URI, web password) come from
  **environment variables**, read in `common/config.py` (or `server/web/config.js`).
- **Secrets never go in the repository.** Local values go in a `.env` file, which git ignores.
  The repository is public, and GitHub secret scanning blocks pushes that contain secrets.

### Time is a port

The brain has 3 s, 5 s, 30 s, 60 s and 2 min timers. All code gets the time and schedules
timers through the `Clock` port. Production uses `SystemClock`; tests use `FakeClock`, which
moves time forward instantly (`clock.advance(3)`). **Never call `time.time()`,
`time.sleep()` or `threading.Timer` directly in a core.**

### Device behaviour

- **RFID debounce:** the reader repeats a card while it is held; the same card is ignored for
  2 s.
- **Speaker:** no queue. If a new text arrives while one is playing, only the most recent one is
  kept and played next. Fixed sentences (alarm, prompts) are generated as WAV files once at
  start-up, because pico2wave is slow on a Pi 3.
- **Temperature:** readings with a failed CRC and readings of exactly 85.0 °C (the DS18B20
  power-on value) are discarded and logged, so a sensor fault never looks like a fire.
- **Voice:** Vosk uses a grammar limited to our phrases plus `[unk]`, and results with low
  confidence are discarded, so background noise or the alarm itself does not trigger commands.

### Brain behaviour

- **States:** IDLE, WAITING_CARD, INSIDE, LOCKED, EMERGENCY. The state machine is pure: it
  receives events and returns actions (say, publish, save), and is tested without broker or
  database.
- **Waiting for a card:** prompt after 3 s, one reminder 5 s later, back to IDLE after 30 s
  more.
- **Fan from the web:** accepted in every state except EMERGENCY.
- **Emergency detection:** rise = current reading minus the minimum of the last 30 s. An
  emergency starts when the rise is ≥ 5 °C in **2 consecutive readings**. No detection until the
  buffer holds 30 s of readings.
- **End of an emergency:** if the person inside never scanned out, the brain records an
  `emergency_end` exit for them; the buffer is cleared and detection pauses for 60 s, so the
  still-hot probe does not trigger a new emergency.
- **Who is inside:** the last `in` in `access_log` without a later `out`, `evacuated` or
  `emergency_end`.

---

## Testing strategy

We test each part **independently**, replacing its neighbours with test doubles:

- **Fakes** (default): small working implementations of a port. `FakeSpeaker` stores what it
  "said" in a list; `FakeFan` stores its speed. Also used by the simulation.
- **Stubs:** return prepared values, e.g. a temperature sensor that returns a fixed sequence.
- **Mocks** (`unittest.mock`): only to check that an adapter calls its library correctly, e.g.
  that the MQTT adapter publishes on the right topic with the right QoS.
- **FakeClock:** to test timers without waiting.

We use three levels: **unit tests** of each core (run everywhere and in CI), **scenario tests**
of the whole system against the simulation, and a **hardware check** on each Pi that tests
every real device one by one and ends with a PASS/FAIL table. In class, the hardware check is
run first.

**Rule:** every pull request that changes logic includes its tests. We do not require TDD.
The robustness tests T1 to T26 of the specification are covered by these levels.

---

## Simulation environment

The whole system runs on one laptop with Docker Compose, without any Raspberry Pi. Each
component runs in **its own container**, with only the network access it has in reality: the
door, room and emergency centre containers can only reach the broker, and only the brain and the
web can reach MongoDB.

The door and room containers only receive their own folder plus `common/`. So if device code
reads MongoDB or imports server code, **it fails in the simulation**, exactly as it would on
the Pi. The architecture rules are checked, not just promised.

The simulated devices are the fake adapters. They are driven through `sim/` topics: a test
publishes on `sim/door/card`, and the fake RFID reader turns it into a card scan, going through
the same code path as a real card. Fake actuators report what they did (`sim/door/speaker/said`,
`sim/room/fan/actual`), so scenarios check the physical result.

The simulation cannot prove the wiring, the RFID frame, Vosk's speed or the audio: that is
what the hardware check is for.

---

## Continuous integration

GitHub Actions runs on every pull request: `ruff` (lint and format) and `pytest tests/unit`.
The check is required by the `main` ruleset, so a pull request with failing tests cannot be
merged.

There is **no continuous deployment**: GitHub cannot reach the Pis on the university network,
and we do not modify the teacher's Pi setup. Deployment is one manual command (below).

---

## Deployment to the Raspberry Pis

- The Pis are **preconfigured by the teacher**. We never reflash them and change as little as
  possible.
- We reach them by **SSH from the university computer** (they do not accept connections from
  our laptops). They only see the university network.
- **First session:** run `deploy/inventory.sh` on each Pi to list what is already installed
  (Python packages, Mosquitto, Node.js, pico2wave, Vosk model) and whether the Pi reaches the
  internet and etu-web2 (port 27017).
- **Getting the code:** if the Pis reach the internet, each Pi clones the repository and pulls.
  Otherwise the university computer pulls and copies with `rsync` over SSH.
- **Deploying:** `deploy/deploy.sh <door|room|server>` updates the code, runs the hardware
  check and restarts the systemd service.
- **Configuration:** each Pi gets its settings (Server Pi address as `MQTT_HOST`, MongoDB URI)
  through environment variables in its systemd service, never in the code.
- **Time at the university is for integration only.** Development happens at home with the
  simulation. Test first what cannot be simulated: RFID, Vosk on the Pi 3, the fan, the audio.

---

## How we work

### Tasks

Every task is a GitHub issue. **Nobody assigns tasks to others**: pick an open issue, assign
it to yourself and move it to "In progress" on the project board. If you are blocked, say so
in the issue.

### Branches and pull requests

`main` is protected: changes only reach it through a pull request approved by another team
member.

1. Update main: `git checkout main && git pull`
2. Create a branch named after the issue: `git checkout -b feat/12-door-led`
   (prefixes: `feat/`, `fix/`, `test/`, `docs/`)
3. Commit your own work with clear messages: `Add LED blink mode (#12)`
4. Push and open a pull request. In the description, explain **in your own words** what changes
   and why, and write `Closes #12` so the issue closes when it is merged.
5. Another member reviews and approves it. Resolve the comments, then merge.

### Rules

- **Each of us must be able to explain the whole project** (course requirement). Never merge
  code you cannot explain.
- Code that contains logic comes with its tests.
- No secrets in the repository.
- AI assistants follow [AGENTS.md](AGENTS.md): the human commits, the human decides the
  architecture, and the human writes the pull request.