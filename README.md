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
| Door Pi | `door/` | PIR, RFID reader (UART), USB speaker (espeak-ng), door LED |
| Room Pi | `room/` | DS18B20 temperature probe (every 2 s), USB microphone (Vosk), FS90R fan |
| Server Pi | Mosquitto | MQTT broker |
| Server Pi | `server/brain/` | State machine, emergency detection, the only writer to MongoDB |
| Server Pi | `server/web/` | Express API + AngularJS web app (port 3001) |
| etu-web2 | MongoDB | Database `smartroom` |
| Laptop | `emergency_center/` | Simulated emergency centre, subscribes to `glo/alert/#` |

Architecture rules (agreed with the teachers, never break them):

- **The device Pis only talk to the broker.** They publish what they measure and obey orders.
  They never decide anything.
- **The web never talks to the Pis.** Every command goes to `glo/web/cmd` and the brain decides.
- **Only the brain writes to MongoDB.** Express may read MongoDB directly (accepted by
  Mr Gaudou, provided the architecture is shown in a diagram).
- **Everything works offline.** Speech-to-text (Vosk) and text-to-speech (espeak-ng) run
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
The only shared code is `common/` (MQTT contract, configuration, clock, message bus), which is
copied to each Pi. The simulation lives in `compose.yaml` (repository root) and `docker/`.

### Constants and configuration

- **No magic numbers.** Every timing, threshold, pin, speed level and duty cycle has a name.
- Values that change between environments (broker host, MongoDB URI, web password) come from
  **environment variables**, read in `common/config.py` (or `server/web/config.js`).
- **Secrets never go in the repository.** Local values go in a `.env` file, which git ignores.
  The repository is public, and GitHub secret scanning blocks pushes that contain secrets.

### Dependencies

- Every machine uses the **same versions**: the Pis, the simulation and CI. Python 3.9
  (Debian bullseye, as on the Pis), Node.js 20 and Mosquitto 2.0.
- Python versions are pinned with `==` in `requirements-brain.txt` (Server Pi),
  `requirements-door.txt` and `requirements-room.txt`; CI installs `requirements-dev.txt`. Node versions are pinned
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

We use three levels, and only the scenario tests need Docker:

- **Unit tests** (`pytest tests/unit`) check each core's logic alone, replacing every
  neighbour with a test double. No broker, no database, no Docker: they run in seconds and are
  the first thing to write.
- **Scenario tests** (`pytest tests/scenarios`) check the whole system end to end. They start
  the simulation themselves (see below) and stop it at the end. **The test plays the role of
  the Pis**: it publishes what a Pi would publish (a card, a
  temperature, a fan confirmation), always built with `common/messages.build()` so it follows
  the same contract as the real Pis. They are **black box**: they check the result only through
  MQTT and the web API, never by reading MongoDB directly. What was saved in the database is
  checked through the web's read endpoints (`/api/access`, `/api/env`, `/api/emergencies`...).
  No endpoint exists only for tests.
- **The hardware check** (`python3 -m door.hw_check`, same for room) runs on each Pi in class
  and ends with a PASS/FAIL table. It is run first: if every device passes and the scenarios
  pass, a remaining problem can only be in the connection between them.

**Rule:** every pull request that changes logic includes its tests. We do not require TDD.
The robustness tests T1 to T26 of the specification are covered by these levels.

---

## Simulation environment

The whole system runs on one laptop with Docker Compose, without any Raspberry Pi.
Everything is defined in `compose.yaml` (repository root) and `docker/`.

### What runs

- `broker`: Mosquitto 2.0.11 with `server/mosquitto/smartroom.conf`.
- `mongo`: MongoDB with its data in memory, so **every start is a clean database**.
- `setup-db`: runs `server/setup_db.py` (indexes and test users) and exits.
- `brain`: starts once the broker is healthy and `setup-db` has finished.
- `web`: Express + AngularJS on http://localhost:3001.
- `door`: the Door Pi program (`python -m door.main --sim-topics`) with fake hardware.
- `room`: the Room Pi program (`python -m room.main --sim-topics`) with fake hardware. Its
  sensor gives 21 °C exactly, with no noise, until a test publishes another temperature.
- `emergency_center`: the simulated emergency centre, listening on `glo/alert/#`.

The simulated Pis run their real code with fake hardware, only on the `iot` network. The fakes
are driven through `sim/` topics and report what they did there:

| Topic | Direction | Message |
|---|---|---|
| `sim/door/card` | test → door | `{"card_id": "CARD_GLORIA"}`: a card scanned |
| `sim/door/motion` | test → door | `{}`: movement in front of the PIR |
| `sim/door/led` | door → test | `{"color": "green", "on": true}` |
| `sim/door/speaker/said` | door → test | `{"text": "Welcome, Gloria."}` |
| `sim/room/temp` | test → room | `{"temp": 25.0}`: the sensor reads this from now on |
| `sim/room/voice` | test → room | `{"text": "ok computer i'm hot"}`: a phrase heard |
| `sim/room/fan` | room → test | `{"speed": 2}`: the fan moved |

A card published on `sim/door/card` goes through the same code path as one read by the RDM6300,
and a phrase on `sim/room/voice` through the same wake word and phrase list as one heard by Vosk.
Topics starting with `sim/` exist only in the simulation and are not part of the contract
(`common/messages.py`): they travel on their own connection (`common/sim_link.py`).

### How it reproduces the real system

- **Isolated networks.** `iot` (MQTT) and `db` (MongoDB) are internal: no internet, and only
  the containers that reach a service in reality are on its network. A program that tries to
  reach something it should not **fails in the simulation**, exactly as it would on the Pis.
  `edge` is the only way in from the laptop: the broker (`127.0.0.1:1883`) and the web
  (`127.0.0.1:3001`), as on the university network. MongoDB is never exposed to the laptop.
- **Same versions as the Pis.** Python 3.9 on Debian bullseye (`docker/python.Dockerfile`),
  Node.js 20 (`docker/web.Dockerfile`), Mosquitto 2.0.11, and the same pinned libraries.
- **Same settings.** Each container gets the same environment variables as its Pi
  (`MQTT_HOST`, `MONGO_URI`...), with simulation values. The code does not know where it runs.
- **Mounted code.** Each container only receives the files it uses, read-only. Code changes
  need no rebuild, only a restart; images are rebuilt only when dependencies change.

### How to use it

```
docker compose up --build    # first time, or after changing requirements or package-lock
docker compose up -d         # start everything in the background
docker compose ps            # state of each container
docker compose logs brain    # what a program is doing
docker compose restart brain # after changing its code
docker compose down          # stop everything (the database is deleted)
```

Docker Desktop must be running. To play a Pi by hand, publish what it would publish:

```
docker compose exec broker mosquitto_pub -t glo/door/rfid -m '{"ts":"2026-11-10T18:00:00","card_id":"CARD_GLORIA"}'
docker compose exec broker mosquitto_sub -t "glo/#" -v    # watch every message
```

In PowerShell, escape the inner quotes of the JSON as `\"`.

### What it cannot prove

The wiring, the RFID frame, Vosk's speed on a Pi 3, the servo and the audio: that is what the
hardware check is for. The laptop is x86 and the Pis are ARM; nothing in our code depends on it.

---

## Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and on `main`:

- **Python job**, inside `python:3.9-slim-bullseye` (the Pis' Python and Debian):
  `ruff check .` (lint only, no formatting; `ruff.toml` targets Python 3.9, so code that
  would not run on the Pis fails) and `pytest tests/unit`.
- **Web job**, inside `node:20-bullseye-slim`: `npm ci` and `npm test`.
- **Scenarios job**, directly on the GitHub runner (it starts containers itself, so it cannot
  run inside one): `pytest tests/scenarios`, which builds and starts the simulation. The system
  under test runs the Pis' versions inside the containers; the test runner only acts as a
  client.

The check is required by the `main` ruleset, so a pull request with failing checks cannot be
merged.

There is **no continuous deployment**: GitHub cannot reach the Pis on the university network.
Deployment is manual (below).

---

## Deployment to the Raspberry Pis

- Three Pis 3 B+ with Raspbian 11 (32-bit). They reach the internet and etu-web2 directly
  (no proxy, no tunnel).

  - **Pi 1** (10.12.220.101): Server (broker, brain and web), `deploy/setup_server.sh`
  - **Pi 6** (10.12.220.106): Door, `deploy/setup_door.sh 10.12.220.101`
  - **Pi 26** (10.12.220.126): Room, `deploy/setup_room.sh 10.12.220.101`

- We reach them by **SSH from the university computer** (the university network does not
  accept our laptops). There is no VPN: etu-web2 is only reachable from the university, so
  tests and development always use the simulation's own MongoDB.
- **Running a script on a Pi from Windows:** copy it with `scp` and remove the Windows line
  endings on the Pi before running it (piping it from PowerShell adds a `\r` that breaks bash).
  `-t` keeps the terminal, so the Server script can ask for the password:
  `ssh -t pi@IP "tr -d '\r' < /tmp/script.sh > /tmp/clean.sh && bash /tmp/clean.sh ARGUMENTS"`
- **Setting up a Pi:** run its setup script once. It installs the system packages, clones the
  repository, installs the pinned Python packages in `~/smartroom-venv`, writes the `.env` and
  reboots. The Door and Room scripts take the Server Pi's IP as argument; the Server script asks
  for the web password. Running a script again skips what is already done.
- **Running:** `git pull`, then `./deploy/run.sh <door|room|brain|web>` in a terminal on the Pi
  (the Server Pi needs two terminals: brain and web). It loads the Pi's `.env` and starts the
  program; Ctrl+C stops it. There are no services: if a program or the SSH session stops, start
  it again.
- **Configuration:** each Pi has a `.env` (never committed), written by its setup script: the
  Server Pi's IP as `MQTT_HOST` on the Door and Room Pis; the MongoDB URI and the web password on
  the Server Pi. The programs only read environment variables, so always start them with
  `run.sh`.
- **Never deploy with `compose.yaml`:** it is the simulation, and its web password is public.
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
