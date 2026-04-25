"""Tests for hrkit.employee_fs — per-employee folder layout + migration."""

from __future__ import annotations

from hrkit import employee_fs, frontmatter as fm


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def test_employee_dir_layout(tmp_path):
    base = employee_fs.employee_dir(tmp_path, "EMP-001")
    assert base == tmp_path / "employees" / "EMP-001"
    assert employee_fs.documents_dir(tmp_path, "EMP-001") == base / "documents"
    assert employee_fs.legal_dir(tmp_path, "EMP-001") == base / "legal"
    assert employee_fs.conversations_dir(tmp_path, "EMP-001") == base / "conversations"
    assert employee_fs.memory_dir(tmp_path, "EMP-001") == base / "memory"


def test_ensure_employee_layout_creates_all_subdirs(tmp_path):
    base = employee_fs.ensure_employee_layout(tmp_path, "EMP-001")
    for sub in ("documents", "legal", "conversations", "memory"):
        assert (base / sub).is_dir()


def test_employee_dir_sanitizes_slashes(tmp_path):
    """A code with slashes must not escape the employees/ directory."""
    base = employee_fs.employee_dir(tmp_path, "EMP/../escape")
    # Resolved path stays under <workspace>/employees/...
    assert "escape" in base.name
    assert base.parent == tmp_path / "employees"


# ---------------------------------------------------------------------------
# employee.md mirror
# ---------------------------------------------------------------------------
def test_write_employee_md_writes_frontmatter(tmp_path):
    md = employee_fs.write_employee_md(tmp_path, {
        "employee_code": "EMP-007",
        "full_name": "Bond James",
        "email": "bond@example.com",
        "status": "active",
        "hire_date": "2024-01-01",
    })
    assert md is not None and md.exists()
    fm_dict, body = fm.parse(md.read_text(encoding="utf-8"))
    assert fm_dict["type"] == "employee"
    assert fm_dict["employee_code"] == "EMP-007"
    assert fm_dict["full_name"] == "Bond James"
    assert "Bond James" in body
    # Subdirs were created as a side effect.
    assert (tmp_path / "employees" / "EMP-007" / "documents").is_dir()


def test_write_employee_md_returns_none_without_code(tmp_path):
    assert employee_fs.write_employee_md(tmp_path, {"full_name": "Anon"}) is None


# ---------------------------------------------------------------------------
# Migration: plan + apply
# ---------------------------------------------------------------------------
def _seed_one_legacy_upload(conn, tmp_path):
    """Create an employee + a legacy-path document file on disk."""
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-MIG-1", "Migra Tor", "migra@example.com"),
    ).lastrowid
    legacy = tmp_path / ".getset" / "uploads" / "employee" / str(emp_id)
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "contract.pdf").write_bytes(b"%PDF-fake-1")
    file_path = f".getset/uploads/employee/{emp_id}/contract.pdf"
    doc_id = conn.execute(
        "INSERT INTO document (employee_id, doc_type, filename, file_path)"
        " VALUES (?, ?, ?, ?)",
        (emp_id, "Contract", "contract.pdf", file_path),
    ).lastrowid
    conn.commit()
    return emp_id, doc_id, file_path


def test_plan_migration_lists_documents(conn, tmp_path):
    emp_id, doc_id, _ = _seed_one_legacy_upload(conn, tmp_path)
    plan = employee_fs.plan_migration(conn, tmp_path)
    assert len(plan) == 1
    entry = plan[0]
    assert entry["document_id"] == doc_id
    assert entry["employee_code"] == "EMP-MIG-1"
    assert entry["from"].endswith("contract.pdf")
    assert entry["to"] == "employees/EMP-MIG-1/documents/contract.pdf"
    assert entry["exists"] is True
    assert entry["reason"] is None


def test_plan_migration_skips_when_employee_has_no_code(conn, tmp_path):
    """An employee row with empty employee_code is skipped with a reason."""
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("", "No Code", "nocode@example.com"),
    ).lastrowid
    conn.execute(
        "INSERT INTO document (employee_id, doc_type, filename, file_path)"
        " VALUES (?, ?, ?, ?)",
        (emp_id, "X", "x.pdf", "anything.pdf"),
    )
    conn.commit()
    plan = employee_fs.plan_migration(conn, tmp_path)
    assert plan[0]["reason"] == "employee has no employee_code"


def test_plan_migration_marks_missing_source(conn, tmp_path):
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-GHOST", "Ghost", "ghost@example.com"),
    ).lastrowid
    conn.execute(
        "INSERT INTO document (employee_id, doc_type, filename, file_path)"
        " VALUES (?, ?, ?, ?)",
        (emp_id, "X", "missing.pdf", ".getset/uploads/employee/999/missing.pdf"),
    )
    conn.commit()
    plan = employee_fs.plan_migration(conn, tmp_path)
    assert plan[0]["reason"] == "source file missing on disk"


def test_apply_migration_copies_files_and_updates_paths(conn, tmp_path):
    emp_id, doc_id, old_path = _seed_one_legacy_upload(conn, tmp_path)
    plan = employee_fs.plan_migration(conn, tmp_path)
    result = employee_fs.apply_migration(conn, tmp_path, plan)

    assert result["copied"] == 1
    assert result["updated_rows"] == 1
    assert result["errors"] == []

    # New file exists at the target location.
    new_file = tmp_path / "employees" / "EMP-MIG-1" / "documents" / "contract.pdf"
    assert new_file.exists()
    # Original file is retained as a backup (we copied, not moved).
    old_file = tmp_path / old_path
    assert old_file.exists()
    # document.file_path now points at the new location.
    row = conn.execute("SELECT file_path FROM document WHERE id = ?", (doc_id,)).fetchone()
    assert row["file_path"] == "employees/EMP-MIG-1/documents/contract.pdf"


def test_apply_migration_is_idempotent(conn, tmp_path):
    _seed_one_legacy_upload(conn, tmp_path)
    plan_a = employee_fs.plan_migration(conn, tmp_path)
    employee_fs.apply_migration(conn, tmp_path, plan_a)

    # Re-planning now sees the row already pointing at the new location.
    plan_b = employee_fs.plan_migration(conn, tmp_path)
    assert plan_b[0]["reason"] == "already at new location"
    result = employee_fs.apply_migration(conn, tmp_path, plan_b)
    assert result["copied"] == 0
    assert result["updated_rows"] == 0
