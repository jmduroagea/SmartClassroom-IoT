// Tests of the web server configuration (config.js).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { loadConfig, ConfigError, DEFAULTS } = require('../config');

test('defaults are used when only the password is set', () => {
  const config = loadConfig({ WEB_PASSWORD: 'secret' });
  assert.equal(config.port, DEFAULTS.PORT);
  assert.equal(config.mqttHost, DEFAULTS.MQTT_HOST);
  assert.equal(config.mqttPort, DEFAULTS.MQTT_PORT);
  assert.equal(config.mongoUri, DEFAULTS.MONGO_URI);
  assert.equal(config.webPassword, 'secret');
});

test('values come from the environment', () => {
  const config = loadConfig({ WEB_PASSWORD: 'secret', MQTT_HOST: '10.12.220.20', PORT: '8080' });
  assert.equal(config.mqttHost, '10.12.220.20');
  assert.equal(config.port, 8080);
});

test('the server refuses to start without a password', () => {
  assert.throws(() => loadConfig({}), ConfigError);
  assert.throws(() => loadConfig({ WEB_PASSWORD: '   ' }), ConfigError);
});

for (const port of ['abc', '0', '70000', '-1', '1.5']) {
  test(`port ${port} is rejected`, () => {
    assert.throws(() => loadConfig({ WEB_PASSWORD: 'secret', MQTT_PORT: port }), ConfigError);
  });
}

test('an empty host is rejected', () => {
  assert.throws(() => loadConfig({ WEB_PASSWORD: 'secret', MQTT_HOST: ' ' }), ConfigError);
});
