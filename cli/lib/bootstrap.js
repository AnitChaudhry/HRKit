// Bootstrap helpers for the @thinqmesh/hrkit npm wrapper.
//
// Responsibilities:
//   - Find a usable Python interpreter (>= 3.10).
//   - Check whether the `hrkit` Python package is already installed.
//   - Install it (from PyPI or the GitHub source) if missing.
//
// Stdlib only (no npm runtime deps) — keeps the install surface tiny.

'use strict';

const { spawn, spawnSync } = require('child_process');
const readline = require('readline');

const HRKIT_PIP_NAME = process.env.HRKIT_PIP_NAME || 'hrkit';
const HRKIT_GIT_URL =
  process.env.HRKIT_GIT_URL ||
  'git+https://github.com/AnitChaudhry/hrkit.git';
// Until hrkit is published to PyPI, install straight from GitHub by default.
// Set HRKIT_INSTALL_SOURCE=pypi to use `pip install hrkit` instead.
const HRKIT_INSTALL_SOURCE = process.env.HRKIT_INSTALL_SOURCE || 'git';
const MIN_PYTHON_MAJOR = 3;
const MIN_PYTHON_MINOR = 10;

const PREFIX = 'hrkit';
const COLOR = process.stdout.isTTY ? true : false;
const CYAN = COLOR ? '[36m' : '';
const RED = COLOR ? '[31m' : '';
const DIM = COLOR ? '[2m' : '';
const RESET = COLOR ? '[0m' : '';

function log(msg) {
  process.stderr.write(`${CYAN}${PREFIX}${RESET} ${DIM}${msg}${RESET}\n`);
}

function fail(msg) {
  process.stderr.write(`${RED}${PREFIX} error${RESET} ${msg}\n`);
  process.exit(1);
}

/**
 * Run a command synchronously, return { ok, stdout, stderr, code }.
 */
function run(cmd, args, opts) {
  const r = spawnSync(cmd, args, { encoding: 'utf-8', ...(opts || {}) });
  return {
    ok: r.status === 0 && !r.error,
    stdout: (r.stdout || '').trim(),
    stderr: (r.stderr || '').trim(),
    code: r.status,
    error: r.error,
  };
}

/**
 * Parse `Python X.Y.Z` -> { major, minor, patch }, or null on failure.
 */
function parsePythonVersion(text) {
  const m = /(\d+)\.(\d+)(?:\.(\d+))?/.exec(text);
  if (!m) return null;
  return {
    major: parseInt(m[1], 10),
    minor: parseInt(m[2], 10),
    patch: m[3] ? parseInt(m[3], 10) : 0,
    raw: m[0],
  };
}

function meetsPythonMin(v) {
  if (!v) return false;
  if (v.major > MIN_PYTHON_MAJOR) return true;
  if (v.major < MIN_PYTHON_MAJOR) return false;
  return v.minor >= MIN_PYTHON_MINOR;
}

/**
 * Try a list of likely python commands and return the first one that runs
 * with version >= 3.10. Throws if none found.
 */
async function resolvePythonCommand() {
  // Honor explicit override.
  if (process.env.HRKIT_PYTHON) {
    const r = run(process.env.HRKIT_PYTHON, ['--version']);
    const v = parsePythonVersion(r.stdout || r.stderr);
    if (r.ok && meetsPythonMin(v)) return process.env.HRKIT_PYTHON;
    throw new Error(
      `HRKIT_PYTHON=${process.env.HRKIT_PYTHON} did not return a usable Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ interpreter.`,
    );
  }

  const candidates =
    process.platform === 'win32'
      ? ['py -3', 'python', 'python3']
      : ['python3', 'python'];

  for (const candidate of candidates) {
    const [cmd, ...args] = candidate.split(' ');
    const r = run(cmd, [...args, '--version']);
    if (!r.ok) continue;
    const v = parsePythonVersion(r.stdout || r.stderr);
    if (meetsPythonMin(v)) {
      log(`found Python ${v.raw} via "${candidate}"`);
      // For `py -3`, return as a single token by setting env? Easier: if there
      // are extra args, return the joined string and let the caller split it.
      return args.length > 0 ? candidate : cmd;
    }
  }

  throw new Error(
    `No Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ interpreter found.\n` +
      `  Install from https://www.python.org/downloads/ and try again.\n` +
      `  Or set HRKIT_PYTHON=/path/to/python in your environment.`,
  );
}

/**
 * Split a python command back into [cmd, ...args] for spawn().
 */
function splitPython(py) {
  const parts = py.split(' ');
  return { cmd: parts[0], args: parts.slice(1) };
}

/**
 * Returns true if `python -c "import hrkit"` succeeds.
 */
function isHrkitInstalled(py) {
  const { cmd, args } = splitPython(py);
  const r = run(cmd, [...args, '-c', 'import hrkit, sys; print(hrkit.__version__)']);
  return r.ok;
}

/**
 * Prompt yes/no on stdin. Returns true if user assents (default yes).
 */
function confirm(question) {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    // Non-interactive — assume yes so CI can install non-interactively.
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(`${question} [Y/n] `, (answer) => {
      rl.close();
      const a = (answer || '').trim().toLowerCase();
      resolve(a === '' || a === 'y' || a === 'yes');
    });
  });
}

/**
 * Install hrkit via pip. Defaults to the GitHub source until hrkit is on
 * PyPI; switch with HRKIT_INSTALL_SOURCE=pypi.
 */
function pipInstall(py) {
  const target =
    HRKIT_INSTALL_SOURCE === 'pypi' ? HRKIT_PIP_NAME : HRKIT_GIT_URL;
  log(`installing hrkit via pip from ${target} ...`);
  const { cmd, args } = splitPython(py);
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, [...args, '-m', 'pip', 'install', '--user', target], {
      stdio: 'inherit',
    });
    child.on('exit', (code) => {
      if (code === 0) resolve();
      else
        reject(
          new Error(
            `pip install exited with code ${code}.\n` +
              `  Try running it yourself:  ${cmd} ${args.concat(['-m', 'pip', 'install', target]).join(' ')}\n` +
              `  If pip is missing:        ${cmd} ${args.concat(['-m', 'ensurepip']).join(' ')}`,
          ),
        );
    });
  });
}

/**
 * Top-level: confirm hrkit is importable; install it if not.
 */
async function ensureHrkitInstalled(py) {
  if (isHrkitInstalled(py)) {
    return;
  }
  log('hrkit Python package is not installed yet.');
  const ok = await confirm('Install it now via pip?');
  if (!ok) {
    throw new Error(
      'install declined. Run `pip install hrkit` (or set HRKIT_INSTALL_SOURCE=git for the GitHub build) and try again.',
    );
  }
  await pipInstall(py);
  if (!isHrkitInstalled(py)) {
    throw new Error(
      'pip install reported success but hrkit is still not importable. Check your Python environment and try again.',
    );
  }
  log('hrkit installed.');
}

module.exports = {
  resolvePythonCommand,
  ensureHrkitInstalled,
  isHrkitInstalled,
  parsePythonVersion,
  meetsPythonMin,
  log,
  fail,
};
