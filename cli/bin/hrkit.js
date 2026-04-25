#!/usr/bin/env node
// Entry point for `npx @thinqmesh/hrkit` and the global `hrkit` binary.
// Bootstraps Python + the hrkit package, then forwards all args to
// `python -m hrkit <args>`. Defaults to `serve` if no args were given.

'use strict';

const { spawn } = require('child_process');
const {
  resolvePythonCommand,
  ensureHrkitInstalled,
  log,
  fail,
} = require('../lib/bootstrap');

(async function main() {
  let py;
  try {
    py = await resolvePythonCommand();
  } catch (err) {
    fail(err.message);
  }

  try {
    await ensureHrkitInstalled(py);
  } catch (err) {
    fail(err.message);
  }

  const userArgs = process.argv.slice(2);
  const finalArgs = userArgs.length === 0 ? ['serve'] : userArgs;

  log(`Running: ${py} -m hrkit ${finalArgs.join(' ')}`);
  const child = spawn(py, ['-m', 'hrkit', ...finalArgs], {
    stdio: 'inherit',
    env: process.env,
  });

  child.on('error', (err) => fail(`failed to start hrkit: ${err.message}`));
  child.on('exit', (code, signal) => {
    if (signal) {
      process.exit(128 + (signal === 'SIGINT' ? 2 : 15));
    }
    process.exit(code === null ? 0 : code);
  });
})();
