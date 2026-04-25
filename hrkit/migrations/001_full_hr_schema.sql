-- 001_full_hr_schema.sql
-- Full HR schema: 13 module tables + schema_migrations bookkeeping table.
-- Conventions (see AGENTS_SPEC.md Section 2):
--   * id INTEGER PRIMARY KEY everywhere
--   * created/updated TEXT, default IST ISO-8601
--   * money fields stored as INTEGER minor units (paise/cents)
--   * dates TEXT YYYY-MM-DD, datetimes TEXT ISO-8601 with +05:30
--   * booleans INTEGER 0/1
--   * JSON blobs TEXT NOT NULL DEFAULT '{}'
--   * FK columns indexed; CHECK constraints for status enums
--   * does NOT touch existing folders/activity/watches/settings tables

-- ---------------------------------------------------------------------------
-- Migration bookkeeping
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);

-- ---------------------------------------------------------------------------
-- 1. department
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS department (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT NOT NULL UNIQUE,
    code                 TEXT NOT NULL DEFAULT '',
    head_employee_id     INTEGER,
    parent_department_id INTEGER REFERENCES department(id) ON DELETE SET NULL,
    notes                TEXT NOT NULL DEFAULT '',
    created              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_department_parent ON department(parent_department_id);
CREATE INDEX IF NOT EXISTS idx_department_head   ON department(head_employee_id);
CREATE INDEX IF NOT EXISTS idx_department_code   ON department(code);

-- ---------------------------------------------------------------------------
-- 2. role
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS role (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    department_id INTEGER REFERENCES department(id) ON DELETE SET NULL,
    level         TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    created       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_role_department ON role(department_id);
CREATE INDEX IF NOT EXISTS idx_role_title      ON role(title);

-- ---------------------------------------------------------------------------
-- 3. employee
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employee (
    id              INTEGER PRIMARY KEY,
    employee_code   TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT NOT NULL DEFAULT '',
    dob             TEXT NOT NULL DEFAULT '',
    gender          TEXT NOT NULL DEFAULT '',
    marital_status  TEXT NOT NULL DEFAULT '',
    hire_date       TEXT NOT NULL DEFAULT '',
    employment_type TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','on_leave','exited')),
    department_id   INTEGER REFERENCES department(id) ON DELETE SET NULL,
    role_id         INTEGER REFERENCES role(id) ON DELETE SET NULL,
    manager_id      INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    location        TEXT NOT NULL DEFAULT '',
    salary_minor    INTEGER NOT NULL DEFAULT 0,
    photo_path      TEXT NOT NULL DEFAULT '',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    created         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_employee_department ON employee(department_id);
CREATE INDEX IF NOT EXISTS idx_employee_role       ON employee(role_id);
CREATE INDEX IF NOT EXISTS idx_employee_manager    ON employee(manager_id);
CREATE INDEX IF NOT EXISTS idx_employee_status     ON employee(status);
CREATE INDEX IF NOT EXISTS idx_employee_full_name  ON employee(full_name);
CREATE INDEX IF NOT EXISTS idx_employee_hire_date  ON employee(hire_date);

-- ---------------------------------------------------------------------------
-- 4. document
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document (
    id           INTEGER PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    doc_type     TEXT NOT NULL DEFAULT '',
    filename     TEXT NOT NULL DEFAULT '',
    file_path    TEXT NOT NULL DEFAULT '',
    uploaded_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    expiry_date  TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    created      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_document_employee    ON document(employee_id);
CREATE INDEX IF NOT EXISTS idx_document_doc_type    ON document(doc_type);
CREATE INDEX IF NOT EXISTS idx_document_expiry_date ON document(expiry_date);

-- ---------------------------------------------------------------------------
-- 5. leave_type
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leave_type (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    code              TEXT NOT NULL DEFAULT '',
    max_days_per_year INTEGER NOT NULL DEFAULT 0,
    carry_forward     INTEGER NOT NULL DEFAULT 0,
    paid              INTEGER NOT NULL DEFAULT 1,
    created           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_leave_type_code ON leave_type(code);

-- ---------------------------------------------------------------------------
-- 6. leave_balance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leave_balance (
    id            INTEGER PRIMARY KEY,
    employee_id   INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    leave_type_id INTEGER NOT NULL REFERENCES leave_type(id) ON DELETE CASCADE,
    year          INTEGER NOT NULL,
    allotted      INTEGER NOT NULL DEFAULT 0,
    used          INTEGER NOT NULL DEFAULT 0,
    pending       INTEGER NOT NULL DEFAULT 0,
    UNIQUE(employee_id, leave_type_id, year)
);
CREATE INDEX IF NOT EXISTS idx_leave_balance_employee   ON leave_balance(employee_id);
CREATE INDEX IF NOT EXISTS idx_leave_balance_leave_type ON leave_balance(leave_type_id);
CREATE INDEX IF NOT EXISTS idx_leave_balance_year       ON leave_balance(year);

-- ---------------------------------------------------------------------------
-- 7. leave_request
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leave_request (
    id            INTEGER PRIMARY KEY,
    employee_id   INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    leave_type_id INTEGER NOT NULL REFERENCES leave_type(id) ON DELETE SET NULL,
    start_date    TEXT NOT NULL,
    end_date      TEXT NOT NULL,
    days          INTEGER NOT NULL DEFAULT 0,
    reason        TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK(status IN ('pending','approved','rejected','cancelled')),
    approver_id   INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    applied_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    decided_at    TEXT NOT NULL DEFAULT '',
    created       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_leave_request_employee   ON leave_request(employee_id);
CREATE INDEX IF NOT EXISTS idx_leave_request_leave_type ON leave_request(leave_type_id);
CREATE INDEX IF NOT EXISTS idx_leave_request_approver   ON leave_request(approver_id);
CREATE INDEX IF NOT EXISTS idx_leave_request_status     ON leave_request(status);
CREATE INDEX IF NOT EXISTS idx_leave_request_start_date ON leave_request(start_date);
CREATE INDEX IF NOT EXISTS idx_leave_request_end_date   ON leave_request(end_date);

-- ---------------------------------------------------------------------------
-- 8. attendance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    date        TEXT NOT NULL,
    check_in    TEXT NOT NULL DEFAULT '',
    check_out   TEXT NOT NULL DEFAULT '',
    hours_minor INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'present'
                CHECK(status IN ('present','absent','half_day','leave','holiday')),
    notes       TEXT NOT NULL DEFAULT '',
    UNIQUE(employee_id, date)
);
CREATE INDEX IF NOT EXISTS idx_attendance_employee ON attendance(employee_id);
CREATE INDEX IF NOT EXISTS idx_attendance_date     ON attendance(date);
CREATE INDEX IF NOT EXISTS idx_attendance_status   ON attendance(status);

-- ---------------------------------------------------------------------------
-- 9. payroll_run
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payroll_run (
    id           INTEGER PRIMARY KEY,
    period       TEXT NOT NULL UNIQUE,
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK(status IN ('draft','processed','paid')),
    processed_at TEXT NOT NULL DEFAULT '',
    processed_by INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    notes        TEXT NOT NULL DEFAULT '',
    created      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_payroll_run_status       ON payroll_run(status);
CREATE INDEX IF NOT EXISTS idx_payroll_run_processed_by ON payroll_run(processed_by);

-- ---------------------------------------------------------------------------
-- 10. payslip
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payslip (
    id               INTEGER PRIMARY KEY,
    payroll_run_id   INTEGER NOT NULL REFERENCES payroll_run(id) ON DELETE CASCADE,
    employee_id      INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    gross_minor      INTEGER NOT NULL DEFAULT 0,
    deductions_minor INTEGER NOT NULL DEFAULT 0,
    net_minor        INTEGER NOT NULL DEFAULT 0,
    components_json  TEXT NOT NULL DEFAULT '{}',
    generated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    file_path        TEXT NOT NULL DEFAULT '',
    UNIQUE(payroll_run_id, employee_id)
);
CREATE INDEX IF NOT EXISTS idx_payslip_payroll_run ON payslip(payroll_run_id);
CREATE INDEX IF NOT EXISTS idx_payslip_employee    ON payslip(employee_id);

-- ---------------------------------------------------------------------------
-- 11. performance_review
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS performance_review (
    id           INTEGER PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    cycle        TEXT NOT NULL DEFAULT '',
    reviewer_id  INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK(status IN ('draft','submitted','acknowledged')),
    score        REAL NOT NULL DEFAULT 0,
    rubric_json  TEXT NOT NULL DEFAULT '{}',
    comments     TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL DEFAULT '',
    created      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_performance_review_employee ON performance_review(employee_id);
CREATE INDEX IF NOT EXISTS idx_performance_review_reviewer ON performance_review(reviewer_id);
CREATE INDEX IF NOT EXISTS idx_performance_review_status   ON performance_review(status);
CREATE INDEX IF NOT EXISTS idx_performance_review_cycle    ON performance_review(cycle);

-- ---------------------------------------------------------------------------
-- 12. onboarding_task
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS onboarding_task (
    id           INTEGER PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    owner_id     INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    due_date     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK(status IN ('pending','in_progress','done')),
    notes        TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    created      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_onboarding_task_employee ON onboarding_task(employee_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_task_owner    ON onboarding_task(owner_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_task_status   ON onboarding_task(status);
CREATE INDEX IF NOT EXISTS idx_onboarding_task_due_date ON onboarding_task(due_date);

-- ---------------------------------------------------------------------------
-- 13. exit_record
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exit_record (
    id                        INTEGER PRIMARY KEY,
    employee_id               INTEGER NOT NULL UNIQUE REFERENCES employee(id) ON DELETE CASCADE,
    last_working_day          TEXT NOT NULL DEFAULT '',
    reason                    TEXT NOT NULL DEFAULT '',
    exit_type                 TEXT NOT NULL DEFAULT '',
    notice_period_days        INTEGER NOT NULL DEFAULT 0,
    knowledge_transfer_status TEXT NOT NULL DEFAULT '',
    asset_returned            INTEGER NOT NULL DEFAULT 0,
    exit_interview_done       INTEGER NOT NULL DEFAULT 0,
    processed_at              TEXT NOT NULL DEFAULT '',
    created                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_exit_record_last_working_day ON exit_record(last_working_day);
CREATE INDEX IF NOT EXISTS idx_exit_record_exit_type        ON exit_record(exit_type);

-- ---------------------------------------------------------------------------
-- 14. recruitment_candidate
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recruitment_candidate (
    id                  INTEGER PRIMARY KEY,
    position_folder_id  INTEGER,
    name                TEXT NOT NULL,
    email               TEXT NOT NULL DEFAULT '',
    phone               TEXT NOT NULL DEFAULT '',
    source              TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'applied'
                        CHECK(status IN ('applied','screening','interview','offer','hired','rejected')),
    score               REAL NOT NULL DEFAULT 0,
    recommendation      TEXT NOT NULL DEFAULT '',
    applied_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    evaluated_at        TEXT NOT NULL DEFAULT '',
    resume_path         TEXT NOT NULL DEFAULT '',
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    created             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_recruitment_candidate_position ON recruitment_candidate(position_folder_id);
CREATE INDEX IF NOT EXISTS idx_recruitment_candidate_status   ON recruitment_candidate(status);
CREATE INDEX IF NOT EXISTS idx_recruitment_candidate_email    ON recruitment_candidate(email);
CREATE INDEX IF NOT EXISTS idx_recruitment_candidate_name     ON recruitment_candidate(name);
CREATE INDEX IF NOT EXISTS idx_recruitment_candidate_applied  ON recruitment_candidate(applied_at);
