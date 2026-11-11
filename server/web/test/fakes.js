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

// Just enough of the MongoDB driver for the routes: find(filter).sort().limit()
// with equality, null (missing or null) and $in, like the real queries.
function matches(doc, filter) {
  return Object.entries(filter).every(([field, condition]) => {
    const value = doc[field];
    if (condition === null) {
      return value === null || value === undefined;
    }
    if (condition && typeof condition === 'object' && Array.isArray(condition.$in)) {
      return condition.$in.includes(value);
    }
    return value === condition;
  });
}

function fakeDb(collections = {}) {
  return {
    collection(name) {
      return {
        find(filter = {}) {
          let docs = (collections[name] || []).filter((doc) => matches(doc, filter));
          const cursor = {
            sort(spec) {
              const [field, direction] = Object.entries(spec)[0];
              docs = [...docs].sort((a, b) => (a[field] < b[field] ? -direction : a[field] > b[field] ? direction : 0));
              return cursor;
            },
            limit(n) {
              docs = docs.slice(0, n);
              return cursor;
            },
            next: async () => docs[0] || null,
            toArray: async () => docs,
          };
          return cursor;
        },
      };
    },
  };
}

module.exports = { FakeBroker, fakeDb };
