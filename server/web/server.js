// SmartClassroom IoT - web server (Express), runs on the Server Pi.
// Reads MongoDB directly (approved by Mr Gaudou) and sends every command
// through the broker on glo/web/cmd: the brain decides, never the web.
//
// Usage:
//   MQTT_HOST=localhost MONGO_URI=mongodb://localhost:27017 node server.js
//   then open http://localhost:3001

const path = require('path');
const express = require('express');
const mqtt = require('mqtt');
const { MongoClient } = require('mongodb');

const PORT = Number(process.env.PORT || 3001);
const MQTT_URL = `mqtt://${process.env.MQTT_HOST || 'localhost'}:${process.env.MQTT_PORT || 1883}`;
const MONGO_URI = process.env.MONGO_URI || 'mongodb://localhost:27017';
const DB_NAME = process.env.MONGO_DB || 'smartroom';

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
// AngularJS served locally, not from Google's CDN (no external services).
app.use('/lib', express.static(path.join(__dirname, 'node_modules', 'angular')));

const broker = mqtt.connect(MQTT_URL, { clientId: 'web-server', reconnectPeriod: 2000 });
broker.on('connect', () => console.log(`[mqtt] connected to ${MQTT_URL}`));
broker.on('error', (err) => console.error('[mqtt]', err.message));

const mongo = new MongoClient(MONGO_URI, { serverSelectionTimeoutMS: 3000 });
const db = mongo.db(DB_NAME);

function sendCommand(payload, res) {
  if (!broker.connected) return res.status(503).json({ error: 'broker unavailable' });
  broker.publish('glo/web/cmd', JSON.stringify(payload), { qos: 1 });
  res.json({ ok: true });
}

// Last document of a collection matching a filter.
const last = (collection, filter = {}) =>
  db.collection(collection).find(filter).sort({ ts: -1 }).limit(1).next();

app.get('/api/status', async (req, res) => {
  try {
    const [access, env, fan, lockEvent, door, room] = await Promise.all([
      last('access_log', { type: { $in: ['in', 'out'] } }),
      last('env'),
      last('fan_log'),
      last('system_log', { event: { $in: ['locked', 'unlocked'] } }),
      last('system_log', { device: 'door', event: { $in: ['online', 'offline'] } }),
      last('system_log', { device: 'room', event: { $in: ['online', 'offline'] } }),
    ]);
    res.json({
      inside: access && access.type === 'in' ? access.name : null,
      temperature: env ? env.temp : null,
      temperatureTs: env ? env.ts : null,
      fanSpeed: fan ? fan.speed : 0,
      locked: !!lockEvent && lockEvent.event === 'locked',
      devices: { door: door ? door.event : 'unknown', room: room ? room.event : 'unknown' },
      // TODO(E): current emergency
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/users', async (req, res) => {
  try {
    res.json(await db.collection('users').find({}, { projection: { _id: 0 } }).sort({ name: 1 }).toArray());
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/users', (req, res) => {
  const { card_id, name } = req.body || {};
  if (typeof card_id !== 'string' || !card_id.trim() || typeof name !== 'string' || !name.trim()) {
    return res.status(400).json({ error: 'card_id and name are required' });
  }
  sendCommand({ action: 'new_card', card_id: card_id.trim(), name: name.trim() }, res);
});

app.post('/api/fan', (req, res) => {
  const speed = (req.body || {}).speed;
  if (![0, 1, 2, 3].includes(speed)) {
    return res.status(400).json({ error: 'speed must be 0, 1, 2 or 3' }); // test T8
  }
  sendCommand({ action: 'fan', speed }, res);
});

app.post('/api/unlock', (req, res) => sendCommand({ action: 'unlock' }, res));

// TODO(E): POST /api/emergency/simulate, POST /api/emergency/end, GET /api/emergencies

mongo.connect()
  .then(() => console.log(`[mongo] connected to ${MONGO_URI}/${DB_NAME}`))
  .catch((err) => console.error('[mongo]', err.message));

app.listen(PORT, () => console.log(`[web] http://localhost:${PORT}`));
