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
function matchesCondition(value, condition) {
  if (condition === null) {
    return value === null || value === undefined;
  }
  if (condition && typeof condition === 'object' && !(condition instanceof Date)) {
    return Object.entries(condition).every(([op, arg]) => {
      if (op === '$in') return arg.includes(value);
      if (op === '$gte') return value >= arg;
      if (op === '$lt') return value < arg;
      throw new Error(`fakeDb does not know ${op}`);
    });
  }
  return value === condition;
}

function matches(doc, filter) {
  return Object.entries(filter).every(([field, condition]) => matchesCondition(doc[field], condition));
}

// The aggregation stages used by the routes: $match, $group (by minute with
// $dateToString, or everything together with _id null) with $avg, $max and
// $sum, and $sort.
function groupKey(doc, id) {
  if (id === null) {
    return null;
  }
  const field = id.$dateToString.date.slice(1);
  return doc[field].toISOString().slice(0, 16) + ':00Z';
}

function accumulate(docs, spec) {
  const [op, arg] = Object.entries(spec)[0];
  const values = typeof arg === 'string' ? docs.map((doc) => doc[arg.slice(1)]) : docs.map(() => arg);
  if (op === '$avg') return values.reduce((a, b) => a + b, 0) / values.length;
  if (op === '$max') return Math.max(...values);
  if (op === '$sum') return values.reduce((a, b) => a + b, 0);
  throw new Error(`fakeDb does not know ${op}`);
}

function runPipeline(docs, pipeline) {
  let rows = docs;
  for (const stage of pipeline) {
    if (stage.$match) {
      rows = rows.filter((doc) => matches(doc, stage.$match));
    } else if (stage.$group) {
      const { _id: id, ...fields } = stage.$group;
      const groups = new Map();
      for (const doc of rows) {
        const key = groupKey(doc, id);
        groups.set(key, [...(groups.get(key) || []), doc]);
      }
      rows = [...groups].map(([key, members]) => {
        const row = { _id: key };
        for (const [name, spec] of Object.entries(fields)) {
          row[name] = accumulate(members, spec);
        }
        return row;
      });
    } else if (stage.$sort) {
      const [field, direction] = Object.entries(stage.$sort)[0];
      rows = [...rows].sort((a, b) => (a[field] < b[field] ? -direction : a[field] > b[field] ? direction : 0));
    } else {
      throw new Error(`fakeDb does not know the stage ${Object.keys(stage)[0]}`);
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
