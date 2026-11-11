// Tests of the API routes, with a fake broker and a fake database.
// Run with: npm test

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const request = require('supertest');

const { createApp, WEB_CMD_TOPIC, WEB_CMD_QOS } = require('../app');
const { FakeBroker, fakeDb } = require('./fakes');

const PASSWORD = 'test-password';

function setup({ connected = true, collections = {}, dbDown = false } = {}) {
  const broker = new FakeBroker({ connected });
  const getDb = dbDown
    ? async () => { throw new Error('database not reachable'); }
    : async () => fakeDb(collections);
  const app = createApp({ broker, getDb, webPassword: PASSWORD });
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

test('GET /api/status with the database down returns 500 and does not crash', async () => {
  const { app } = setup({ dbDown: true });
  const res = await request(app).get('/api/status');
  assert.equal(res.status, 500);
  assert.match(res.body.error, /not reachable/);
});
