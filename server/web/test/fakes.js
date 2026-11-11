// Test doubles: a broker and a database that need no network.

'use strict';

// Records what the app publishes, like FakeBus in Python.
class FakeBroker {
  constructor({ connected = true } = {}) {
    this.connected = connected;
    this.published = [];
  }

  publish(topic, payload, options) {
    this.published.push({ topic, message: JSON.parse(payload), options });
  }
}

// Just enough of the MongoDB driver for the routes: collection().find().sort()...
function fakeDb(collections = {}) {
  return {
    collection(name) {
      const docs = collections[name] || [];
      const cursor = {
        sort: () => cursor,
        limit: () => cursor,
        next: async () => docs[0] || null,
        toArray: async () => docs,
      };
      return { find: () => cursor };
    },
  };
}

module.exports = { FakeBroker, fakeDb };
