# SmartClassroom IoT

IoT project week, Université Toulouse Capitole. Team: Ignacio, José María, Gloria.
Teachers: Laurent Marsan and Benoît Gaudou.

A connected classroom with two use cases:

1. **Access control and voice assistant.** A PIR sensor detects someone at the door, they scan
   their RFID card, the speaker welcomes them and says the temperature, and they control a fan
   by voice ("Ok Computer, I'm hot", "Ok Computer, I'm cold", "Ok Computer, what's the
   temperature?", "Ok Computer, help") or from the web app.
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
| Sensors Pi (`smartroom-sensors`) | `door/` | PIR, RFID reader (UART), USB speaker (espeak-ng), door LED |
| Sensors Pi (`smartroom-sensors`) | `room/` | DS18B20 temperature probe (every 2 s), USB microphone (Vosk), FS90R fan |
| Brain Pi (`smartroom-brain`) | Mosquitto | MQTT broker |
| Brain Pi (`smartroom-brain`) | `server/brain/` | State machine, emergency detection, the only writer to MongoDB |
| Brain Pi (`smartroom-brain`) | `server/web/` | Express API + AngularJS web app (port 3001) |
| etu-web2 | MongoDB | Database `smartroom` |
| Laptop | `emergency_center/` | Simulated emergency centre, subscribes to `glo/alert/#` |

Only two Raspberry Pis are available, so the sensors Pi runs `door` and `room` as **two
separate programs**, each with its own MQTT connection. They never talk to each other directly.

Architecture rules (agreed with the teachers, never break them):

- **The device programs only talk to the broker.** They publish what they measure and obey orders.
  They never decide anything.
- **The web never talks to the Pis.** Every command goes to `glo/web/cmd` and the brain decides.
- **Only the brain writes to MongoDB.** Express may read MongoDB directly (accepted by
  Mr Gaudou, provided the architecture is shown in a diagram).
- **Everything works offline.** Speech-to-text (Vosk) and text-to-speech (espeak-ng) run
  locally; no external services.
- **The broker runs on the brain Pi**, not on a laptop. A laptop broker is only used for
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

### Dependencies

- Every machine uses the **same versions**: the Pis, the simulation and CI. Python 3.9
  (Debian bullseye, as on the Pis), Node.js 20 and Mosquitto 2.0.
- Python versions are pinned with `==` in `requirements-brain.txt` and
  `requirements-sensors.txt`; CI installs `requirements-dev.txt`. Node versions are pinned
  in `server/web/package-lock.json` (always `npm ci`, never `npm install`, to deploy).
- All files use Linux line endings (`.gitattributes`), because scripts run on the Pis.

### Web security

AngularJS has known vulnerabilities with no fix (it is abandoned, but required by the course).
Never insert user text as HTML: no `ng-bind-html` and no `$sce.trustAsHtml`. `{{ }}` escapes
text and is safe.

### Time is a port

The brain has 3 s, 5 s, 30 s, 60 s and 2 min timers. All code gets the time and schedules
timers through the `Clock` port. Production uses `SystemClock`; tests use `FakeClock`, which
moves time forward instantly (`clock.advance(3)`). **Never call `time.time()`,
`time.sleep()` or `threading.Timer` directly in a core.**

### Device behaviour

- **RFID debounce:** the reader repeats a card while it is held; the same card is ignored for
  2 s.
- **Speaker:** espeak-ng, no queue. If a new text arrives while one is playing, only the most
  recent one is kept and played next.
- **Temperature:** readings with a failed CRC and readings of exactly 85.0 °C (the DS18B20
  power-on value) are discarded and logged, so a sensor fault never looks like a fire.
- **Voice:** every command starts with the wake word **"Ok Computer"**, including "Help".
  The speaker never says the wake word (a unit test checks every sentence), so it cannot
  trigger commands by itself, and people can speak while it is talking. Vosk also uses a
  grammar limited to our phrases plus `[unk]`, and discards results with low confidence.

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

The containers use the same base as the Pis (Python 3.9 on Debian bullseye, Node.js 20,
Mosquitto 2.0) and install the same pinned versions, so the simulation behaves like the Pis.

The simulated devices are the fake adapters. They are driven through `sim/` topics: a test
publishes on `sim/door/card`, and the fake RFID reader turns it into a card scan, going through
the same code path as a real card. Fake actuators report what they did (`sim/door/speaker/said`,
`sim/room/fan/actual`), so scenarios check the physical result.

The simulation cannot prove the wiring, the RFID frame, Vosk's speed or the audio: that is
what the hardware check is for.

---

## Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and on `main`:

- **Python job**, inside `python:3.9-slim-bullseye` (the Pis' Python and Debian):
  `ruff check .` (lint only, no formatting; `ruff.toml` targets Python 3.9, so code that
  would not run on the Pis fails) and `pytest tests/unit`.
- **Web job**, inside `node:20-bullseye-slim`: `npm ci` and `npm test`.

The check is required by the `main` ruleset, so a pull request with failing checks cannot be
merged.

There is **no continuous deployment**: GitHub cannot reach the Pis on the university network.
Deployment is one manual command (below).

---

## Deployment to the Raspberry Pis

- Two Pis 3 B+ with Raspbian 11 (32-bit), prepared with `deploy/setup_sensors.sh` and
  `deploy/setup_brain.sh`. Both reach the internet and etu-web2 directly (no proxy, no tunnel).
- We reach them by **SSH from the university computer** (the university network does not
  accept our laptops). There is no VPN: etu-web2 is only reachable from the university, so
  tests and development always use the simulation's own MongoDB.
- **Running a script on a Pi from Windows:** copy it with `scp` and remove the Windows line
  endings on the Pi before running it (piping it from PowerShell adds a `\r` that breaks bash):
  `ssh pi@IP "tr -d '\r' < /tmp/script.sh > /tmp/clean.sh && bash /tmp/clean.sh"`
- **Getting the code:** each Pi clones the repository and pulls.
- **Deploying:** `deploy/deploy.sh <sensors|brain>` updates the code, runs the hardware check
  and restarts the systemd services.
- **Configuration:** each Pi has a `.env` (never committed) with its settings: the brain Pi's IP
  as `MQTT_HOST` on the sensors Pi, the MongoDB URI on the brain Pi. The IPs come from DHCP and
  could change, so they are only ever written there.
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
