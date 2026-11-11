// Tests of the API routes, with a fake broker and a fake database.
// Run with: npm test

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const request = require('supertest');

const {
  createApp, WEB_CMD_TOPIC, WEB_CMD_QOS, HISTORY_LIMIT, MAX_HOURS, DEFAULT_HOURS,
  MAX_REPORT_DAYS, ACCESS_TYPES, DEFAULT_ACCESS_LIMIT, MAX_ACCESS_LIMIT,
  LAST_UNKNOWN_MINUTES,
} = require('../app');
const { FakeBroker, fakeDb } = require('./fakes');

const PASSWORD = 'test-password';

const NOW = new Date('2026-11-10T12:00:00Z');

function setup({ connected = true, collections = {}, dbDown = false } = {}) {
  const broker = new FakeBroker({ connected });
  const getDb = dbDown
    ? async () => { throw new Error('database not reachable'); }
    : async () => fakeDb(collections);
  const app = createApp({ broker, getDb, webPassword: PASSWORD, now: () => NOW });
  return { app, broker };
}

// --- Fan (T8) ----------------------------------------------------------------

test('POST /api/fan with a valid speed publishes the command', async () => {
  const { app, broker } = setup();
  const res = await request(app).post('/api/fan').send({ speed: 2 });
  assert.equal(res.status, 200);
  assert.deepEqual(broker.published, [
    { topic: WEB_CMD_TOPIC, message: { action: 'fan', speed: 2 }, options: { qos: WEB_CMD_QOS } },
  ]);
});

for (const body of [{ speed: 9 }, { speed: -1 }, { speed: '2' }, { speed: true }, {}]) {
  test(`POST /api/fan with ${JSON.stringify(body)} returns 400 and publishes nothing`, async () => {
    const { app, broker } = setup();
    const res = await request(app).post('/api/fan').send(body);
    assert.equal(res.status, 400);
    assert.deepEqual(broker.published, []);
  });
}

test('POST /api/fan without a body returns 400 and publishes nothing', async () => {
  const { app, broker } = setup();
  const res = await request(app).post('/api/fan');
  assert.equal(res.status, 400);
  assert.deepEqual(broker.published, []);
});

test('POST /api/fan with broken JSON returns 400', async () => {
  const { app, broker } = setup();
  const res = await request(app)
    .post('/api/fan')
    .set('Content-Type', 'application/json')
    .send('{"speed": ');
  assert.equal(res.status, 400);
  assert.deepEqual(broker.published, []);
});

// --- Cards -------------------------------------------------------------------

test('POST /api/users with card_id and name publishes new_card', async () => {
  const { app, broker } = setup();
  const res = await request(app).post('/api/users').send({ card_id: ' 0F00A1B2C3 ', name: 'Gloria' });
  assert.equal(res.status, 200);
  assert.deepEqual(broker.published[0].message, {
    action: 'new_card',
    card_id: '0F00A1B2C3',
    name: 'Gloria',
  });
});

for (const body of [
  { card_id: '', name: 'Gloria' },
  { card_id: '0F00A1B2C3', name: '   ' },
  { name: 'Gloria' },
  { card_id: 1234, name: 'Gloria' },
]) {
  test(`POST /api/users with ${JSON.stringify(body)} returns 400`, async () => {
    const { app, broker } = setup();
    const res = await request(app).post('/api/users').send(body);
    assert.equal(res.status, 400);
    assert.deepEqual(broker.published, []);
  });
}

test('GET /api/users returns the users from the database', async () => {
  const users = [{ card_id: '0F00A1B2C3', name: 'Gloria' }];
  const { app } = setup({ collections: { users } });
  const res = await request(app).get('/api/users');
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, users);
});

// --- Unlock ------------------------------------------------------------------

test('POST /api/unlock publishes unlock', async () => {
  const { app, broker } = setup();
  const res = await request(app).post('/api/unlock');
  assert.equal(res.status, 200);
  assert.deepEqual(broker.published[0].message, { action: 'unlock' });
});

// --- Emergency with password (T20) ---------------------------------------------

for (const [route, action] of [
  ['/api/emergency/simulate', 'simulate_emergency'],
  ['/api/emergency/end', 'end_emergency'],
]) {
  test(`POST ${route} with the right password publishes ${action}`, async () => {
    const { app, broker } = setup();
    const res = await request(app).post(route).send({ password: PASSWORD });
    assert.equal(res.status, 200);
    assert.deepEqual(broker.published[0].message, { action });
  });

  for (const body of [{ password: 'wrong' }, { password: '' }, {}, { password: 123 }]) {
    test(`POST ${route} with ${JSON.stringify(body)} returns 401 and publishes nothing`, async () => {
      const { app, broker } = setup();
      const res = await request(app).post(route).send(body);
      assert.equal(res.status, 401);
      assert.deepEqual(broker.published, []);
    });
  }
}

// --- Broker disconnected -------------------------------------------------------

for (const [route, body] of [
  ['/api/fan', { speed: 1 }],
  ['/api/users', { card_id: '0F00A1B2C3', name: 'Gloria' }],
  ['/api/unlock', {}],
  ['/api/emergency/simulate', { password: PASSWORD }],
]) {
  test(`POST ${route} with the broker disconnected returns 503`, async () => {
    const { app, broker } = setup({ connected: false });
    const res = await request(app).post(route).send(body);
    assert.equal(res.status, 503);
    assert.deepEqual(broker.published, []);
  });
}

// --- Status --------------------------------------------------------------------

test('GET /api/status reads who is inside, temperature and fan from the database', async () => {
  const { app } = setup({
    collections: {
      access_log: [{ type: 'in', name: 'Gloria' }],
      env: [{ temp: 22.5, ts: '2026-11-10T09:00:00Z' }],
      fan_log: [{ speed: 2 }],
    },
  });
  const res = await request(app).get('/api/status');
  assert.equal(res.status, 200);
  assert.equal(res.body.inside, 'Gloria');
  assert.equal(res.body.temperature, 22.5);
  assert.equal(res.body.fanSpeed, 2);
});

async function status(collections) {
  const { app } = setup({ collections });
  const res = await request(app).get('/api/status');
  assert.equal(res.status, 200);
  return res.body;
}

const T = (minute) => `2026-11-10T09:${String(minute).padStart(2, '0')}:00Z`;

test('GET /api/status: nobody inside when the database is empty', async () => {
  const body = await status({});
  assert.equal(body.inside, null);
  assert.equal(body.state, 'normal');
  assert.equal(body.emergency, null);
  assert.deepEqual(body.devices, { door: 'unknown', room: 'unknown' });
});

for (const exit of ['out', 'evacuated', 'emergency_end']) {
  test(`GET /api/status: nobody inside after an '${exit}' that follows the 'in'`, async () => {
    const body = await status({
      access_log: [
        { type: 'in', name: 'Gloria', ts: T(1) },
        { type: exit, name: 'Gloria', ts: T(2) },
      ],
    });
    assert.equal(body.inside, null);
  });
}

for (const other of ['denied', 'occupied']) {
  test(`GET /api/status: a later '${other}' entry does not change who is inside`, async () => {
    const body = await status({
      access_log: [
        { type: 'in', name: 'Gloria', ts: T(1) },
        { type: other, name: 'Ignacio', ts: T(2) },
      ],
    });
    assert.equal(body.inside, 'Gloria');
  });
}

test('GET /api/status: the newest entry wins, whatever the order in the database', async () => {
  const body = await status({
    access_log: [
      { type: 'in', name: 'José María', ts: T(3) },
      { type: 'out', name: 'Gloria', ts: T(2) },
      { type: 'in', name: 'Gloria', ts: T(1) },
    ],
  });
  assert.equal(body.inside, 'José María');
});

test('GET /api/status: state is locked after a locked event', async () => {
  const body = await status({ system_log: [{ event: 'locked', ts: T(1) }] });
  assert.equal(body.state, 'locked');
});

test('GET /api/status: state is normal again after unlocked', async () => {
  const body = await status({
    system_log: [
      { event: 'locked', ts: T(1) },
      { event: 'unlocked', ts: T(2) },
    ],
  });
  assert.equal(body.state, 'normal');
});

test('GET /api/status: device events do not hide the lock', async () => {
  const body = await status({
    system_log: [
      { event: 'locked', ts: T(1) },
      { device: 'door', event: 'online', ts: T(2) },
    ],
  });
  assert.equal(body.state, 'locked');
  assert.equal(body.devices.door, 'online');
});

test('GET /api/status: shows each Pi online or offline from its last event', async () => {
  const body = await status({
    system_log: [
      { device: 'door', event: 'online', ts: T(1) },
      { device: 'door', event: 'offline', ts: T(2) },
      { device: 'room', event: 'online', ts: T(3) },
    ],
  });
  assert.deepEqual(body.devices, { door: 'offline', room: 'online' });
});

test('GET /api/status: returns the time of the temperature reading', async () => {
  const body = await status({ env: [{ temp: 21, ts: T(1) }, { temp: 23, ts: T(2) }] });
  assert.equal(body.temperature, 23);
  assert.equal(body.temperatureTs, T(2));
});

const EMERGENCY = {
  started_at: T(5),
  ended_at: null,
  trigger: 'rate',
  trigger_temp: 40.5,
  person: { card_id: 'A1B2', name: 'Gloria' },
  evacuated_at: null,
  not_evacuated_alert: false,
  calls: [],
  readings: [{ ts: T(5), temp: 40.5 }],
};

test('GET /api/status: an open emergency gives state emergency and its summary', async () => {
  const body = await status({ emergencies: [EMERGENCY] });
  assert.equal(body.state, 'emergency');
  assert.deepEqual(body.emergency, {
    startedAt: T(5),
    trigger: 'rate',
    triggerTemp: 40.5,
    person: 'Gloria',
    evacuated: false,
    evacuatedAt: null,
    notEvacuated: false,
    helpRequested: false,
  });
});

test('GET /api/status: the emergency wins over the lock', async () => {
  const body = await status({
    emergencies: [EMERGENCY],
    system_log: [{ event: 'locked', ts: T(1) }],
  });
  assert.equal(body.state, 'emergency');
});

test('GET /api/status: shows evacuation, help call and not-evacuated alert', async () => {
  const body = await status({
    emergencies: [{
      ...EMERGENCY,
      evacuated_at: T(7),
      not_evacuated_alert: true,
      calls: [{ ts: T(6), reason: 'start' }, { ts: T(6), reason: 'help' }],
    }],
  });
  assert.equal(body.emergency.evacuated, true);
  assert.equal(body.emergency.evacuatedAt, T(7));
  assert.equal(body.emergency.notEvacuated, true);
  assert.equal(body.emergency.helpRequested, true);
});

test('GET /api/status: an ended emergency is not shown', async () => {
  const body = await status({ emergencies: [{ ...EMERGENCY, ended_at: T(9) }] });
  assert.equal(body.state, 'normal');
  assert.equal(body.emergency, null);
});

test('GET /api/status: the summary does not send the readings', async () => {
  const body = await status({ emergencies: [EMERGENCY] });
  assert.equal(body.emergency.readings, undefined);
});

test('GET /api/status with the database down returns 500 and does not crash', async () => {
  const { app } = setup({ dbDown: true });
  const res = await request(app).get('/api/status');
  assert.equal(res.status, 500);
  assert.match(res.body.error, /not reachable/);
});

// --- Emergency history (#27) ---------------------------------------------------

test('GET /api/emergencies with no emergencies returns an empty list', async () => {
  const { app } = setup({ collections: {} });
  const res = await request(app).get('/api/emergencies');
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, []);
});

test('GET /api/emergencies returns each emergency without its readings', async () => {
  const { app } = setup({
    collections: {
      emergencies: [{
        ...EMERGENCY,
        ended_at: T(9),
        evacuated_at: T(7),
        not_evacuated_alert: true,
        calls: [{ ts: T(6), reason: 'help' }, { ts: T(8), reason: 'not_evacuated' }],
      }],
    },
  });
  const res = await request(app).get('/api/emergencies');
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, [{
    startedAt: T(5),
    endedAt: T(9),
    inProgress: false,
    trigger: 'rate',
    triggerTemp: 40.5,
    person: 'Gloria',
    evacuatedAt: T(7),
    notEvacuated: true,
    calls: [{ ts: T(6), reason: 'help' }, { ts: T(8), reason: 'not_evacuated' }],
  }]);
});

test('GET /api/emergencies shows the current emergency first, marked in progress', async () => {
  const { app } = setup({
    collections: {
      emergencies: [
        { ...EMERGENCY, started_at: T(1), ended_at: T(2) },
        { ...EMERGENCY, started_at: T(5), ended_at: null },
      ],
    },
  });
  const res = await request(app).get('/api/emergencies');
  assert.deepEqual(res.body.map((e) => [e.startedAt, e.inProgress]), [[T(5), true], [T(1), false]]);
});

test('GET /api/emergencies with nobody inside gives person null and no calls', async () => {
  const { app } = setup({
    collections: { emergencies: [{ ...EMERGENCY, person: null, calls: undefined, ended_at: T(9) }] },
  });
  const res = await request(app).get('/api/emergencies');
  assert.equal(res.body[0].person, null);
  assert.deepEqual(res.body[0].calls, []);
});

test(`GET /api/emergencies returns only the ${HISTORY_LIMIT} newest`, async () => {
  const many = Array.from({ length: HISTORY_LIMIT + 5 }, (_, i) => ({
    ...EMERGENCY,
    started_at: `2026-11-10T${String(i).padStart(2, '0')}:00:00Z`,
    ended_at: `2026-11-10T${String(i).padStart(2, '0')}:30:00Z`,
  }));
  const { app } = setup({ collections: { emergencies: many } });
  const res = await request(app).get('/api/emergencies');
  assert.equal(res.body.length, HISTORY_LIMIT);
  assert.equal(res.body[0].startedAt, many[many.length - 1].started_at);
});

test('GET /api/emergencies with the database down returns 500', async () => {
  const { app } = setup({ dbDown: true });
  const res = await request(app).get('/api/emergencies');
  assert.equal(res.status, 500);
});

// --- Temperature chart (#29) ------------------------------------------------------

// A reading `minutes` before NOW (plus some seconds inside that minute).
const reading = (minutes, temp, seconds = 0) => ({
  ts: new Date(NOW.getTime() - minutes * 60000 + seconds * 1000),
  temp,
});

test('GET /api/env returns one average per minute, oldest first', async () => {
  const { app } = setup({
    collections: {
      env: [
        reading(5, 22.0, 10), reading(5, 23.0, 20), reading(5, 24.0, 30),
        reading(3, 25.04),
      ],
    },
  });
  const res = await request(app).get('/api/env?hours=1');
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, [
    { ts: '2026-11-10T11:55:00Z', temp: 23 },
    { ts: '2026-11-10T11:57:00Z', temp: 25 },
  ]);
});

test('GET /api/env leaves out readings older than the period', async () => {
  const { app } = setup({ collections: { env: [reading(61, 30), reading(59, 20)] } });
  const res = await request(app).get('/api/env?hours=1');
  assert.deepEqual(res.body.map((p) => p.temp), [20]);
});

test(`GET /api/env without hours covers the default ${DEFAULT_HOURS} hours`, async () => {
  const { app } = setup({
    collections: { env: [reading(DEFAULT_HOURS * 60 + 1, 30), reading(DEFAULT_HOURS * 60 - 1, 20)] },
  });
  const res = await request(app).get('/api/env');
  assert.deepEqual(res.body.map((p) => p.temp), [20]);
});

test('GET /api/env with no readings returns an empty list', async () => {
  const { app } = setup({});
  const res = await request(app).get('/api/env?hours=6');
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, []);
});

for (const hours of ['0', String(MAX_HOURS + 1), '-1', '1.5', 'abc', '']) {
  test(`GET /api/env?hours=${hours} returns 400`, async () => {
    const { app } = setup({});
    const res = await request(app).get(`/api/env?hours=${hours}`);
    assert.equal(res.status, 400);
  });
}

test('GET /api/env with the database down returns 500', async () => {
  const { app } = setup({ dbDown: true });
  const res = await request(app).get('/api/env?hours=1');
  assert.equal(res.status, 500);
});

// --- Report for a period (#28) ----------------------------------------------------

// The period used by most report tests: 10:00 to 11:00, before NOW (12:00).
const FROM = '2026-11-10T10:00:00Z';
const TO = '2026-11-10T11:00:00Z';
const at = (hhmm) => new Date(`2026-11-10T${hhmm}:00Z`);
const access = (type, hhmm, name = 'Gloria') => ({ type, name, card_id: 'A1', ts: at(hhmm) });

const reportUrl = (query) => `/api/report?${new URLSearchParams(query)}`;

async function report(collections, from = FROM, to = TO) {
  const { app } = setup({ collections });
  const res = await request(app).get(reportUrl({ from, to }));
  assert.equal(res.status, 200, JSON.stringify(res.body));
  return res.body;
}

test('GET /api/report of an empty period gives zeros and nulls', async () => {
  const body = await report({});
  assert.equal(body.from, '2026-11-10T10:00:00.000Z');
  assert.equal(body.to, '2026-11-10T11:00:00.000Z');
  assert.equal(body.occupiedSeconds, 0);
  assert.deepEqual(body.temperature, { average: null, max: null, readings: 0 });
  assert.deepEqual(body.access, Object.fromEntries(ACCESS_TYPES.map((t) => [t, 0])));
  assert.deepEqual(body.emergencies, []);
});

test('GET /api/report adds up the visits inside the period', async () => {
  const body = await report({
    access_log: [
      access('in', '10:10'), access('out', '10:20'),
      access('in', '10:30', 'Ignacio'), access('evacuated', '10:45', 'Ignacio'),
    ],
  });
  assert.equal(body.occupiedSeconds, 25 * 60);
});

test('GET /api/report counts a visit that started before the period from its start', async () => {
  const body = await report({ access_log: [access('in', '09:50'), access('out', '10:15')] });
  assert.equal(body.occupiedSeconds, 15 * 60);
});

test('GET /api/report counts a visit still going on at the end of the period until the end', async () => {
  const body = await report({ access_log: [access('in', '10:40'), access('out', '11:30')] });
  assert.equal(body.occupiedSeconds, 20 * 60);
});

test('GET /api/report counts someone inside the whole period', async () => {
  const body = await report({ access_log: [access('in', '09:00')] });
  assert.equal(body.occupiedSeconds, 60 * 60);
});

test('GET /api/report does not count the future when the period ends after now', async () => {
  // NOW is 12:00: someone inside since 11:30 counts 30 minutes, not until 13:00.
  const body = await report({ access_log: [access('in', '11:30')] }, '2026-11-10T11:00:00Z', '2026-11-10T13:00:00Z');
  assert.equal(body.occupiedSeconds, 30 * 60);
});

test('GET /api/report: denied and occupied attempts do not change the occupied time', async () => {
  const body = await report({
    access_log: [
      access('in', '10:00'), access('occupied', '10:05', 'Ignacio'),
      access('denied', '10:06', null), access('out', '10:10'),
    ],
  });
  assert.equal(body.occupiedSeconds, 10 * 60);
});

test('GET /api/report counts the access attempts of the period by type', async () => {
  const body = await report({
    access_log: [
      access('denied', '09:59', null),
      access('in', '10:00'), access('denied', '10:01', null), access('denied', '10:02', null),
      access('occupied', '10:03', 'Ignacio'), access('out', '10:30'),
      access('in', '11:00'),
    ],
  });
  assert.deepEqual(body.access, { in: 1, out: 1, denied: 2, occupied: 1, evacuated: 0, emergency_end: 0 });
});

test('GET /api/report gives the average and maximum temperature of the period', async () => {
  const body = await report({
    env: [
      { temp: 50, ts: at('09:59') },
      { temp: 21, ts: at('10:00') }, { temp: 22, ts: at('10:30') }, { temp: 23.5, ts: at('10:59') },
      { temp: 60, ts: at('11:00') },
    ],
  });
  assert.deepEqual(body.temperature, { average: 22.2, max: 23.5, readings: 3 });
});

test('GET /api/report lists the emergencies of the period and how they ended', async () => {
  const emergency = (start, extra) => ({ ...EMERGENCY, started_at: at(start), ended_at: at('10:50'), ...extra });
  const body = await report({
    emergencies: [
      emergency('09:30', {}),
      emergency('10:01', { evacuated_at: at('10:02') }),
      emergency('10:10', { evacuated_at: null }),
      emergency('10:20', { person: null }),
      emergency('10:55', { ended_at: null }),
    ],
  });
  assert.deepEqual(body.emergencies.map((e) => [e.startedAt, e.outcome]), [
    ['2026-11-10T10:01:00.000Z', 'evacuated'],
    ['2026-11-10T10:10:00.000Z', 'ended, not evacuated'],
    ['2026-11-10T10:20:00.000Z', 'nobody inside'],
    ['2026-11-10T10:55:00.000Z', 'in progress'],
  ]);
  assert.equal(body.emergencies[0].person, 'Gloria');
  assert.equal(body.emergencies[0].readings, undefined);
});

const BAD_RANGES = [
  ['missing from', { to: TO }],
  ['missing to', { from: FROM }],
  ['from is not a date', { from: 'yesterday', to: TO }],
  ['from equal to to', { from: FROM, to: FROM }],
  ['from after to', { from: TO, to: FROM }],
  [`more than ${MAX_REPORT_DAYS} days`, { from: '2026-10-01T00:00:00Z', to: '2026-11-02T00:00:00Z' }],
];
for (const [name, query] of BAD_RANGES) {
  test(`GET /api/report with ${name} returns 400`, async () => {
    const { app } = setup({});
    const res = await request(app).get(reportUrl(query));
    assert.equal(res.status, 400);
    assert.ok(res.body.error);
  });
}

test(`GET /api/report accepts exactly ${MAX_REPORT_DAYS} days`, async () => {
  await report({}, '2026-10-01T00:00:00Z', '2026-11-01T00:00:00Z');
});

test('GET /api/report with the database down returns 500', async () => {
  const { app } = setup({ dbDown: true });
  const res = await request(app).get(reportUrl({ from: FROM, to: TO }));
  assert.equal(res.status, 500);
});

// --- Access history (#30) ---------------------------------------------------------

test('GET /api/access returns the entries newest first', async () => {
  const { app } = setup({
    collections: {
      access_log: [
        access('in', '10:00'),
        { type: 'denied', name: null, card_id: 'FF99', ts: at('10:05') },
        access('out', '10:10'),
      ],
    },
  });
  const res = await request(app).get('/api/access');
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, [
    { ts: '2026-11-10T10:10:00.000Z', cardId: 'A1', name: 'Gloria', type: 'out' },
    { ts: '2026-11-10T10:05:00.000Z', cardId: 'FF99', name: null, type: 'denied' },
    { ts: '2026-11-10T10:00:00.000Z', cardId: 'A1', name: 'Gloria', type: 'in' },
  ]);
});

test(`GET /api/access without limit returns the last ${DEFAULT_ACCESS_LIMIT}`, async () => {
  const many = Array.from({ length: DEFAULT_ACCESS_LIMIT + 10 }, (_, i) => ({
    type: 'denied', name: null, card_id: `C${i}`, ts: new Date(NOW.getTime() - i * 60000),
  }));
  const { app } = setup({ collections: { access_log: many } });
  const res = await request(app).get('/api/access');
  assert.equal(res.body.length, DEFAULT_ACCESS_LIMIT);
  assert.equal(res.body[0].cardId, 'C0');
});

test('GET /api/access?limit=2 returns only 2', async () => {
  const { app } = setup({
    collections: { access_log: [access('in', '10:00'), access('out', '10:10'), access('in', '10:20')] },
  });
  const res = await request(app).get('/api/access?limit=2');
  assert.deepEqual(res.body.map((e) => e.type), ['in', 'out']);
});

test('GET /api/access with no entries returns an empty list', async () => {
  const { app } = setup({});
  const res = await request(app).get('/api/access');
  assert.deepEqual(res.body, []);
});

for (const limit of ['0', String(MAX_ACCESS_LIMIT + 1), '-5', '2.5', 'abc', '']) {
  test(`GET /api/access?limit=${limit} returns 400`, async () => {
    const { app } = setup({});
    const res = await request(app).get(`/api/access?limit=${limit}`);
    assert.equal(res.status, 400);
  });
}

test('GET /api/access with the database down returns 500', async () => {
  const { app } = setup({ dbDown: true });
  const res = await request(app).get('/api/access');
  assert.equal(res.status, 500);
});

// --- Last rejected card (#32) -----------------------------------------------------

const minutesAgo = (minutes) => new Date(NOW.getTime() - minutes * 60000);
const rejected = (cardId, minutes, name = null) => ({ type: 'denied', card_id: cardId, name, ts: minutesAgo(minutes) });

async function lastUnknown(collections) {
  const { app } = setup({ collections });
  const res = await request(app).get('/api/access/last-unknown');
  assert.equal(res.status, 200);
  return res.body;
}

test('GET /api/access/last-unknown gives the last rejected unknown card', async () => {
  const body = await lastUnknown({ access_log: [rejected('OLD1', 5), rejected('NEW2', 1)] });
  assert.deepEqual(body, { cardId: 'NEW2', ts: minutesAgo(1).toISOString() });
});

const NONE = { cardId: null, ts: null };

test('GET /api/access/last-unknown gives no card when nothing was rejected', async () => {
  assert.deepEqual(await lastUnknown({}), NONE);
});

test(`GET /api/access/last-unknown ignores cards rejected more than ${LAST_UNKNOWN_MINUTES} minutes ago`, async () => {
  assert.deepEqual(await lastUnknown({ access_log: [rejected('OLD1', LAST_UNKNOWN_MINUTES + 1)] }), NONE);
});

test('GET /api/access/last-unknown ignores known cards rejected while locked', async () => {
  const body = await lastUnknown({ access_log: [rejected('UNK1', 3), rejected('A1', 1, 'Gloria')] });
  assert.equal(body.cardId, 'UNK1');
});

test('GET /api/access/last-unknown ignores cards registered since', async () => {
  const body = await lastUnknown({
    access_log: [rejected('UNK1', 3), rejected('UNK2', 1)],
    users: [{ card_id: 'UNK2', name: 'Ignacio' }],
  });
  assert.equal(body.cardId, 'UNK1');
});

test('GET /api/access/last-unknown ignores other access types', async () => {
  const body = await lastUnknown({
    access_log: [{ type: 'occupied', card_id: 'X1', name: null, ts: minutesAgo(1) }],
  });
  assert.deepEqual(body, NONE);
});

test('GET /api/access/last-unknown with the database down returns 500', async () => {
  const { app } = setup({ dbDown: true });
  const res = await request(app).get('/api/access/last-unknown');
  assert.equal(res.status, 500);
});
