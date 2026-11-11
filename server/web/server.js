// Starts the web server: reads the configuration, creates the real MQTT client
// and MongoDB connection, and gives them to the Express app (app.js).
//
// Usage (from server/web):
//   WEB_PASSWORD=... MQTT_HOST=... MONGO_URI=... npm start
//   then open http://localhost:3001

'use strict';

const mqtt = require('mqtt');
const { MongoClient } = require('mongodb');
const { loadConfig, ConfigError } = require('./config');
const { createApp } = require('./app');

const MQTT_RECONNECT_MS = 2000;
const MONGO_TIMEOUT_MS = 3000;

let config;
try {
  config = loadConfig();
} catch (err) {
  if (err instanceof ConfigError) {
    console.error(`[config] ${err.message}`);
    process.exit(1);
  }
  throw err;
}

const mqttUrl = `mqtt://${config.mqttHost}:${config.mqttPort}`;
const broker = mqtt.connect(mqttUrl, { clientId: 'web-server', reconnectPeriod: MQTT_RECONNECT_MS });
broker.on('connect', () => console.log(`[mqtt] connected to ${mqttUrl}`));
broker.on('error', (err) => console.error('[mqtt]', err.message));

// MongoDB may be down or not started yet: (re)connect on demand, so the web
// recovers by itself when the database comes back (test T12).
let mongo = null;
async function getDb() {
  if (!mongo) {
    const client = new MongoClient(config.mongoUri, { serverSelectionTimeoutMS: MONGO_TIMEOUT_MS });
    try {
      await client.connect();
      console.log(`[mongo] connected to ${config.mongoUri}/${config.mongoDb}`);
      mongo = client;
    } catch (err) {
      await client.close().catch(() => {});
      throw new Error(`database not reachable (${config.mongoUri})`);
    }
  }
  return mongo.db(config.mongoDb);
}

getDb().catch((err) => console.error('[mongo]', err.message));

const app = createApp({ broker, getDb, webPassword: config.webPassword });
app.listen(config.port, () => console.log(`[web] http://localhost:${config.port}`));
