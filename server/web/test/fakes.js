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

// The three aggregation stages used by GET /api/env: $match with $gte,
// $group by minute ($dateToString) with $avg, and $sort.
function runPipeline(docs, pipeline) {
  let rows = docs;
  for (const stage of pipeline) {
    if (stage.$match) {
      const [field, { $gte }] = Object.entries(stage.$match)[0];
      rows = rows.filter((doc) => doc[field] >= $gte);
    } else if (stage.$group) {
      const field = stage.$group._id.$dateToString.date.slice(1);
      const valueField = stage.$group.temp.$avg.slice(1);
      const groups = new Map();
      for (const doc of rows) {
        const minute = doc[field].toISOString().slice(0, 16) + ':00Z';
        groups.set(minute, [...(groups.get(minute) || []), doc[valueField]]);
      }
      rows = [...groups].map(([id, values]) => ({
        _id: id,
        temp: values.reduce((a, b) => a + b, 0) / values.length,
      }));
    } else if (stage.$sort) {
      const [field, direction] = Object.entries(stage.$sort)[0];
      rows = [...rows].sort((a, b) => (a[field] < b[field] ? -direction : a[field] > b[field] ? direction : 0));
    }
  }
  return rows;
}

function fakeDb(collections = {}) {
  return {
    collection(name) {
      return {
        aggregate(pipeline) {
          return { toArray: async () => runPipeline(collections[name] || [], pipeline) };
        },
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
