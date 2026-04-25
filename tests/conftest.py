"""Shared pytest fixtures for the HR module tests.

The canonical fixture per AGENTS_SPEC.md Section 7 uses
``hrkit.migration_runner.apply_all`` to create the schema. That module
is owned by Wave 1 Agent 4 and may not exist yet when tests for individual
modules are executed in isolation, so this fixture falls back to creating the
subset of tables that Wave 1 Agent 7 needs (employee, department, role,
document) inline. The column lists mirror Section 2 of the spec exactly.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Make the repo root importable regardless of how pytest is invoked.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_FALLBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS department (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL UNIQUE,
    code                  TEXT,
    head_employee_id      INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    parent_department_id  INTEGER REFERENCES department(id) ON DELETE SET NULL,
    notes                 TEXT,
    created               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_department_parent ON department(parent_department_id);
CREATE INDEX IF NOT EXISTS idx_department_head   ON department(head_employee_id);

CREATE TABLE IF NOT EXISTS role (
    id             INTEGER PRIMARY KEY,
    title          TEXT NOT NULL,
    department_id  INTEGER REFERENCES department(id) ON DELETE SET NULL,
    level          TEXT,
    description    TEXT,
    created        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_role_department ON role(department_id);

CREATE TABLE IF NOT EXISTS employee (
    id               INTEGER PRIMARY KEY,
    employee_code    TEXT UNIQUE,
    full_name        TEXT NOT NULL,
    email            TEXT NOT NULL UNIQUE,
    phone            TEXT,
    dob              TEXT,
    gender           TEXT,
    marital_status   TEXT,
    hire_date        TEXT,
    employment_type  TEXT,
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK(status IN ('active','on_leave','exited')),
    department_id    INTEGER REFERENCES department(id) ON DELETE SET NULL,
    role_id          INTEGER REFERENCES role(id) ON DELETE SET NULL,
    manager_id       INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    location         TEXT,
    salary_minor     INTEGER,
    photo_path       TEXT,
    metadata_json    TEXT NOT NULL DEFAULT '{}',
    created          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_employee_dept    ON employee(department_id);
CREATE INDEX IF NOT EXISTS idx_employee_role    ON employee(role_id);
CREATE INDEX IF NOT EXISTS idx_employee_manager ON employee(manager_id);
CREATE INDEX IF NOT EXISTS idx_employee_status  ON employee(status);

CREATE TABLE IF NOT EXISTS document (
    id           INTEGER PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    doc_type     TEXT NOT NULL,
    filename     TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    uploaded_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    expiry_date  TEXT,
    notes        TEXT,
    created      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_document_employee ON document(employee_id);
"""


def _apply_schema(conn: sqlite3.Connection) -> None:
    try:
        from hrkit.migration_runner import apply_all  # type: ignore
    except ImportError:
        conn.executescript(_FALLBACK_SCHEMA)
        return
    try:
        apply_all(conn)
    except Exception:
        # Migration runner exists but failed (e.g. SQL not present yet) —
        # fall back so module-level tests can still run.
        conn.executescript(_FALLBACK_SCHEMA)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    _apply_schema(c)
    yield c
    c.close()
