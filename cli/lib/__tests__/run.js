// Minimal smoke tests for the wrapper. Pure Node.js — no test runner.
// Run with: node lib/__tests__/run.js

'use strict';

const assert = require('assert');
const {
  parsePythonVersion,
  meetsPythonMin,
} = require('../bootstrap');

let pass = 0;
let fail = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ok  ${name}`);
    pass += 1;
  } catch (err) {
    console.error(`  FAIL ${name}`);
    console.error(`       ${err.message}`);
    fail += 1;
  }
}

console.log('@thinqmesh/hrkit smoke tests');

test('parsePythonVersion handles "Python 3.12.4"', () => {
  const v = parsePythonVersion('Python 3.12.4');
  assert.deepStrictEqual({ major: v.major, minor: v.minor, patch: v.patch }, {
    major: 3, minor: 12, patch: 4,
  });
});

test('parsePythonVersion handles "Python 3.10"', () => {
  const v = parsePythonVersion('Python 3.10');
  assert.strictEqual(v.major, 3);
  assert.strictEqual(v.minor, 10);
  assert.strictEqual(v.patch, 0);
});

test('parsePythonVersion returns null on garbage', () => {
  assert.strictEqual(parsePythonVersion('not a version'), null);
});

test('meetsPythonMin: 3.10 passes', () => {
  assert.strictEqual(meetsPythonMin({ major: 3, minor: 10, patch: 0 }), true);
});

test('meetsPythonMin: 3.9 fails', () => {
  assert.strictEqual(meetsPythonMin({ major: 3, minor: 9, patch: 18 }), false);
});

test('meetsPythonMin: 4.0 passes', () => {
  assert.strictEqual(meetsPythonMin({ major: 4, minor: 0, patch: 0 }), true);
});

test('meetsPythonMin: null fails', () => {
  assert.strictEqual(meetsPythonMin(null), false);
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
