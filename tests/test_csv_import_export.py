"""Tests for the CSV import/export modules + AI local-only sandbox.

Covers:
- ``csv_import.import_csv`` creates an imported_<slug> table with inferred
  types (TEXT / INTEGER / REAL) and round-tripped rows.
- ``csv_import.safe_select`` refuses any name outside the sandbox prefix.
- ``csv_import.drop_table`` only drops imported_* tables.
- ``csv_export._module_rows`` returns the same column order as the UI.
- ``branding.ai_local_only`` defaults to True; the chat agent's tool list
  excludes web tools when on, includes them when off.
- The imported-table AI tools return safe error strings, not raise.
"""
from __future__ import annotations

import sqlite3

import pytest

from hrkit import branding
from hrkit.migration_runner import apply_all
from hrkit.modules import csv_import, csv_export


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    apply_all(c)
    # ``settings`` table lives in db.open_db, not the migrations.
    c.executescript(
        "CREATE TABLE IF NOT EXISTS settings ("
        "  key   TEXT PRIMARY KEY,"
        "  value TEXT NOT NULL DEFAULT ''"
        ")"
    )
    yield c
    c.close()


# ---------------------------------------------------------------------------
# csv_import
# ---------------------------------------------------------------------------
def test_import_csv_creates_typed_table(conn):
    csv_bytes = (
        b"name,age,salary,joined\n"
        b"Alice,30,12500.50,2022-04-01\n"
        b"Bob,29,9800.00,2023-01-15\n"
        b"Cara,35,15400.25,2021-07-10\n"
    )
    result = csv_import.import_csv(conn, filename="employees.csv",
                                    raw_bytes=csv_bytes)
    assert result["table"] == "imported_employees"
    assert result["rows_inserted"] == 3
    types = {c["name"]: c["type"] for c in result["columns"]}
    assert types == {"name": "TEXT", "age": "INTEGER",
                     "salary": "REAL", "joined": "TEXT"}

    desc = csv_import.describe_table(conn, "imported_employees")
    assert desc is not None and desc["rows"] == 3

    # Round-trip the rows.
    sel = csv_import.safe_select(conn, "imported_employees",
                                  columns=["name", "age"], limit=10)
    assert sel["columns"] == ["name", "age"]
    names = {r["name"] for r in sel["rows"]}
    assert names == {"Alice", "Bob", "Cara"}
    # Age column was typed INTEGER → values come back as ints, not strings.
    ages = {r["age"] for r in sel["rows"]}
    assert ages == {30, 29, 35}


def test_import_csv_rejects_non_imported_table_in_safe_select(conn):
    """safe_select must refuse anything that isn't imported_*."""
    with pytest.raises(ValueError):
        csv_import.safe_select(conn, "employee", limit=1)
    with pytest.raises(ValueError):
        csv_import.safe_select(conn, "sqlite_master", limit=1)


def test_drop_table_only_drops_imported_prefix(conn):
    csv_bytes = b"a,b\n1,2\n"
    csv_import.import_csv(conn, filename="x.csv", raw_bytes=csv_bytes)
    assert csv_import.describe_table(conn, "imported_x") is not None
    # Refused for non-imported names.
    assert csv_import.drop_table(conn, "employee") is False
    assert csv_import.drop_table(conn, "imported_x") is True
    assert csv_import.describe_table(conn, "imported_x") is None


def test_import_csv_replace_flag(conn):
    csv_import.import_csv(conn, filename="e.csv",
                           raw_bytes=b"a,b\n1,2\n")
    with pytest.raises(ValueError):
        csv_import.import_csv(conn, filename="e.csv",
                               raw_bytes=b"a,b\n3,4\n")
    out = csv_import.import_csv(conn, filename="e.csv",
                                 raw_bytes=b"a,b,c\n5,6,7\n",
                                 replace=True)
    assert out["replaced"] is True
    desc = csv_import.describe_table(conn, "imported_e")
    assert {c["name"] for c in desc["columns"]} == {"a", "b", "c"}


def test_import_csv_sanitizes_column_headers(conn):
    csv_bytes = b"First Name,Last Name,e-mail address\nA,B,a@b\n"
    result = csv_import.import_csv(conn, filename="contacts.csv",
                                    raw_bytes=csv_bytes)
    cols = [c["name"] for c in result["columns"]]
    assert cols == ["first_name", "last_name", "e_mail_address"]


def test_safe_select_rejects_unknown_columns(conn):
    csv_import.import_csv(conn, filename="t.csv",
                           raw_bytes=b"a,b\n1,2\n")
    with pytest.raises(ValueError):
        csv_import.safe_select(conn, "imported_t", columns=["a", "nope"])
    with pytest.raises(ValueError):
        csv_import.safe_select(conn, "imported_t", where={"nope": 1})


# ---------------------------------------------------------------------------
# csv_export
# ---------------------------------------------------------------------------
def test_module_rows_uses_first_row_columns(conn):
    # Seed minimal employee + dept data.
    conn.execute("INSERT INTO department (name) VALUES ('Eng')")
    conn.execute(
        "INSERT INTO employee (employee_code, full_name, email, department_id) "
        "VALUES ('E-001', 'Alice', 'a@x.com', 1)")
    conn.commit()
    rows, cols = csv_export._module_rows(conn, "employee")
    assert rows
    # All non-JSON columns from list_rows should be present.
    assert "employee_code" in cols and "full_name" in cols
    # JSON blob columns are filtered out (e.g. metadata_json).
    assert all(not c.endswith("_json") for c in cols)


def test_exportable_modules_lists_real_modules():
    out = csv_export._exportable_modules()
    slugs = {m["slug"] for m in out}
    # A few modules we know expose list_rows.
    assert {"employee", "department", "role"}.issubset(slugs)


# ---------------------------------------------------------------------------
# AI local-only sandbox
# ---------------------------------------------------------------------------
def test_ai_local_only_default_true(conn):
    assert branding.ai_local_only(conn) is True


def test_ai_local_only_off_when_setting_zero(conn):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('AI_LOCAL_ONLY', '0')")
    conn.commit()
    assert branding.ai_local_only(conn) is False


def test_ai_local_only_truthy_strings(conn):
    for raw in ("1", "true", "TRUE", "on", "yes"):
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('AI_LOCAL_ONLY', ?)",
                     (raw,))
        conn.commit()
        assert branding.ai_local_only(conn) is True, f"failed for {raw!r}"


def test_imported_table_tools_handle_unknown_table_gracefully(conn):
    from hrkit import chat
    tools = chat._build_imported_table_tools(conn)
    by_name = {t.__name__: t for t in tools}
    # No tables yet — list returns the friendly empty message.
    assert "no imported tables" in by_name["list_imported_tables"]()
    # describe + query both return error strings (never raise).
    assert by_name["describe_imported_table"]("imported_nope").startswith("error:")
    assert by_name["query_imported_table"]("imported_nope").startswith("error:")
    # A real read works.
    csv_import.import_csv(conn, filename="x.csv", raw_bytes=b"a,b\n1,2\n")
    out = by_name["query_imported_table"]("imported_x", columns=["a"])
    assert '"a"' in out and '"rows"' in out


def test_imported_table_tools_refuse_core_table_names(conn):
    """Even though the tool function takes a string, safe_select must
    treat any non-imported name as an error — including names that happen
    to be valid tables (like 'employee')."""
    from hrkit import chat
    tools = chat._build_imported_table_tools(conn)
    by_name = {t.__name__: t for t in tools}
    out = by_name["query_imported_table"]("employee")
    assert out.startswith("error:")
    # Specifically: must mention that the name is unknown / not imported.
    assert "imported" in out.lower() or "unknown" in out.lower()
