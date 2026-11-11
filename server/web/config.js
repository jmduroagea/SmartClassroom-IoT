// Web server settings, read from environment variables (never written in the code).
// Same names as .env.example and common/config.py. A missing or wrong value stops
// the server at start-up with a message that names the setting.

'use strict';

const DEFAULTS = {
  PORT: 3001,
  MQTT_HOST: 'localhost',
  MQTT_PORT: 1883,
  MONGO_URI: 'mongodb://localhost:27017',
  MONGO_DB: 'smartroom',
};

const MIN_PORT = 1;
const MAX_PORT = 65535;

class ConfigError extends Error {}

function readText(env, name, fallback) {
  const value = String(env[name] === undefined ? fallback : env[name]).trim();
  if (!value) {
    throw new ConfigError(`${name} must not be empty`);
  }
  return value;
}

function readPort(env, name, fallback) {
  if (env[name] === undefined) {
    return fallback;
  }
  const raw = String(env[name]).trim();
  const port = Number(raw);
  if (!/^\d+$/.test(raw) || port < MIN_PORT || port > MAX_PORT) {
    throw new ConfigError(`${name}=${env[name]} must be a number between ${MIN_PORT} and ${MAX_PORT}`);
  }
  return port;
}

function loadConfig(env = process.env) {
  // No default password: the server refuses to start without one.
  const webPassword = String(env.WEB_PASSWORD || '').trim();
  if (!webPassword) {
    throw new ConfigError('WEB_PASSWORD is not set: choose a password in your .env file');
  }
  return {
    port: readPort(env, 'PORT', DEFAULTS.PORT),
    mqttHost: readText(env, 'MQTT_HOST', DEFAULTS.MQTT_HOST),
    mqttPort: readPort(env, 'MQTT_PORT', DEFAULTS.MQTT_PORT),
    mongoUri: readText(env, 'MONGO_URI', DEFAULTS.MONGO_URI),
    mongoDb: readText(env, 'MONGO_DB', DEFAULTS.MONGO_DB),
    webPassword,
  };
}

module.exports = { loadConfig, ConfigError, DEFAULTS };
