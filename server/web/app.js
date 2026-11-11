// The Express application: every route of the API, and nothing else.
//
// It does not create the MQTT client or the database connection: it receives
// them, so tests can pass fakes (no broker, no MongoDB). server.js creates the
// real ones and starts the server.
//
// The web never talks to the Pis: every command is published on glo/web/cmd
// and the brain decides. Express reads MongoDB directly (accepted by Mr Gaudou).

'use strict';

const crypto = require('crypto');
const path = require('path');
const express = require('express');

const WEB_CMD_TOPIC = 'glo/web/cmd';
// Ways of leaving the room (specification v4): a normal exit, an evacuation,
// or the brain closing the exit when an emergency ends without evacuation.
const EXIT_TYPES = ['out', 'evacuated', 'emergency_end'];
const HELP_REASON = 'help';
// How many past emergencies the history shows (decision 1A).
const HISTORY_LIMIT = 20;
// Temperature chart (decisions 1A, 2A): one average per minute, 1 to 24 hours back.
const MIN_HOURS = 1;
const MAX_HOURS = 24;
const DEFAULT_HOURS = 24;
const MS_PER_HOUR = 60 * 60 * 1000;
const MINUTE_FORMAT = '%Y-%m-%dT%H:%M:00Z';
const WEB_CMD_QOS = 1;
const FAN_SPEEDS = [0, 1, 2, 3];

const BAD_REQUEST = 400;
const UNAUTHORIZED = 401;
const SERVER_ERROR = 500;
const UNAVAILABLE = 503;

// Compares in constant time, so the answer time says nothing about how many
// characters were right. Both sides are hashed first to get the same length.
function passwordMatches(given, expected) {
  if (typeof given !== 'string') {
    return false;
  }
  const a = crypto.createHash('sha256').update(given).digest();
  const b = crypto.createHash('sha256').update(expected).digest();
  return crypto.timingSafeEqual(a, b);
}

function isNonEmptyText(value) {
  return typeof value === 'string' && value.trim() !== '';
}

// The last document of a collection that matches a filter.
function last(db, collection, filter = {}, timeField = 'ts') {
  return db.collection(collection).find(filter).sort({ [timeField]: -1 }).limit(1).next();
}

// What the web needs to know about the current emergency, without the
// hundreds of readings stored in the record (they are for the history).
function summarizeEmergency(doc) {
  if (!doc) {
    return null;
  }
  const calls = doc.calls || [];
  return {
    startedAt: doc.started_at,
    trigger: doc.trigger,
    triggerTemp: doc.trigger_temp,
    person: doc.person ? doc.person.name : null,
    evacuated: Boolean(doc.evacuated_at),
    evacuatedAt: doc.evacuated_at || null,
    notEvacuated: Boolean(doc.not_evacuated_alert),
    helpRequested: calls.some((call) => call.reason === HELP_REASON),
  };
}

// One row of the emergency history. The readings are left out: they are only
// for the per-emergency chart, which is an extra.
function historyEntry(doc) {
  return {
    startedAt: doc.started_at,
    endedAt: doc.ended_at || null,
    inProgress: !doc.ended_at,
    trigger: doc.trigger,
    triggerTemp: doc.trigger_temp,
    person: doc.person ? doc.person.name : null,
    evacuatedAt: doc.evacuated_at || null,
    notEvacuated: Boolean(doc.not_evacuated_alert),
    calls: (doc.calls || []).map((call) => ({ ts: call.ts, reason: call.reason })),
  };
}

// Parses ?hours= : missing gives the default, anything that is not a whole
// number between MIN_HOURS and MAX_HOURS gives null.
function parseHours(value) {
  if (value === undefined) {
    return DEFAULT_HOURS;
  }
  if (!/^\d+$/.test(value)) {
    return null;
  }
  const hours = Number(value);
  return hours >= MIN_HOURS && hours <= MAX_HOURS ? hours : null;
}

// The average temperature of each minute since a moment, oldest first.
// MongoDB does the work, so only one point per minute leaves the database.
function temperatureHistory(db, since) {
  return db.collection('env').aggregate([
    { $match: { ts: { $gte: since } } },
    { $group: { _id: { $dateToString: { format: MINUTE_FORMAT, date: '$ts' } }, temp: { $avg: '$temp' } } },
    { $sort: { _id: 1 } },
  ]).toArray();
}

// The emergency wins over the lock: an emergency lifts the lock (specification v4).
function systemState(emergency, lockEvent) {
  if (emergency) {
    return 'emergency';
  }
  if (lockEvent && lockEvent.event === 'locked') {
    return 'locked';
  }
  return 'normal';
}

/**
 * @param {object} deps
 * @param {{connected: boolean, publish: Function}} deps.broker  MQTT client (or a fake)
 * @param {() => Promise<object>} deps.getDb  returns the MongoDB database (or a fake)
 * @param {string} deps.webPassword  password for emergency commands
 * @param {() => Date} [deps.now]  current time (a fixed one in the tests)
 */
function createApp({ broker, getDb, webPassword, now = () => new Date() }) {
  const app = express();
  app.use(express.json());
  app.use(express.static(path.join(__dirname, 'public')));
  // AngularJS served locally, not from Google's CDN (no external services).
  app.use('/lib', express.static(path.join(__dirname, 'node_modules', 'angular')));
  app.use('/lib/chartjs', express.static(path.join(__dirname, 'node_modules', 'chart.js', 'dist')));

  function sendCommand(res, payload) {
    if (!broker.connected) {
      return res.status(UNAVAILABLE).json({ error: 'broker unavailable' });
    }
    broker.publish(WEB_CMD_TOPIC, JSON.stringify(payload), { qos: WEB_CMD_QOS });
    return res.json({ ok: true });
  }

  function checkPassword(req, res) {
    if (!passwordMatches((req.body || {}).password, webPassword)) {
      res.status(UNAUTHORIZED).json({ error: 'wrong password' });
      return false;
    }
    return true;
  }

  app.get('/api/status', async (req, res) => {
    try {
      const db = await getDb();
      const [access, env, fan, lockEvent, door, room, emergencyDoc] = await Promise.all([
        // The person inside is the last 'in' without a later exit of any kind.
        last(db, 'access_log', { type: { $in: ['in', ...EXIT_TYPES] } }),
        last(db, 'env'),
        last(db, 'fan_log'),
        last(db, 'system_log', { event: { $in: ['locked', 'unlocked'] } }),
        last(db, 'system_log', { device: 'door', event: { $in: ['online', 'offline'] } }),
        last(db, 'system_log', { device: 'room', event: { $in: ['online', 'offline'] } }),
        last(db, 'emergencies', { ended_at: null }, 'started_at'),
      ]);
      const emergency = summarizeEmergency(emergencyDoc);
      res.json({
        state: systemState(emergency, lockEvent),
        inside: access && access.type === 'in' ? access.name : null,
        temperature: env ? env.temp : null,
        temperatureTs: env ? env.ts : null,
        fanSpeed: fan ? fan.speed : 0,
        devices: { door: door ? door.event : 'unknown', room: room ? room.event : 'unknown' },
        emergency,
      });
    } catch (err) {
      res.status(SERVER_ERROR).json({ error: err.message });
    }
  });

  app.get('/api/emergencies', async (req, res) => {
    try {
      const db = await getDb();
      const docs = await db
        .collection('emergencies')
        .find({}, { projection: { readings: 0 } })
        .sort({ started_at: -1 })
        .limit(HISTORY_LIMIT)
        .toArray();
      res.json(docs.map(historyEntry));
    } catch (err) {
      res.status(SERVER_ERROR).json({ error: err.message });
    }
  });

  app.get('/api/env', async (req, res) => {
    const hours = parseHours(req.query.hours);
    if (hours === null) {
      return res.status(BAD_REQUEST).json({ error: `hours must be a whole number from ${MIN_HOURS} to ${MAX_HOURS}` });
    }
    try {
      const db = await getDb();
      const since = new Date(now().getTime() - hours * MS_PER_HOUR);
      const points = await temperatureHistory(db, since);
      return res.json(points.map((point) => ({ ts: point._id, temp: Math.round(point.temp * 10) / 10 })));
    } catch (err) {
      return res.status(SERVER_ERROR).json({ error: err.message });
    }
  });

  app.get('/api/users', async (req, res) => {
    try {
      const db = await getDb();
      const users = await db
        .collection('users')
        .find({}, { projection: { _id: 0 } })
        .sort({ name: 1 })
        .toArray();
      res.json(users);
    } catch (err) {
      res.status(SERVER_ERROR).json({ error: err.message });
    }
  });

  app.post('/api/users', (req, res) => {
    const { card_id: cardId, name } = req.body || {};
    if (!isNonEmptyText(cardId) || !isNonEmptyText(name)) {
      return res.status(BAD_REQUEST).json({ error: 'card_id and name are required' });
    }
    return sendCommand(res, { action: 'new_card', card_id: cardId.trim(), name: name.trim() });
  });

  app.post('/api/fan', (req, res) => {
    const { speed } = req.body || {};
    if (!FAN_SPEEDS.includes(speed)) {
      return res.status(BAD_REQUEST).json({ error: `speed must be one of ${FAN_SPEEDS.join(', ')}` });
    }
    return sendCommand(res, { action: 'fan', speed });
  });

  app.post('/api/unlock', (req, res) => sendCommand(res, { action: 'unlock' }));

  app.post('/api/emergency/simulate', (req, res) => {
    if (checkPassword(req, res)) {
      sendCommand(res, { action: 'simulate_emergency' });
    }
  });

  app.post('/api/emergency/end', (req, res) => {
    if (checkPassword(req, res)) {
      sendCommand(res, { action: 'end_emergency' });
    }
  });

  // Broken JSON in a request: answer 400 in JSON instead of an HTML error page.
  // eslint-disable-next-line no-unused-vars
  app.use((err, req, res, next) => {
    const status = err.status || err.statusCode || SERVER_ERROR;
    res.status(status).json({ error: status === BAD_REQUEST ? 'invalid JSON' : 'server error' });
  });

  return app;
}

module.exports = {
  createApp, passwordMatches, WEB_CMD_TOPIC, WEB_CMD_QOS, HISTORY_LIMIT, MAX_HOURS, DEFAULT_HOURS,
};
