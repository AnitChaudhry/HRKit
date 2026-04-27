-- 002_phase2_modules.sql
-- Phase-2 expansion: Tier A new modules + Tier B extensions + Tier C integrations.
-- Conventions: see 001 header (id INTEGER PK; created/updated TEXT IST;
-- money in minor units; JSON in TEXT NOT NULL DEFAULT '{}'; FKs indexed;
-- CHECK constraints for status enums; everything IF NOT EXISTS).

-- ---------------------------------------------------------------------------
-- helpdesk_ticket
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ticket (
    id              INTEGER PRIMARY KEY,
    ticket_code     TEXT NOT NULL UNIQUE,
    subject         TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    requester_id    INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    assignee_id     INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    category        TEXT NOT NULL DEFAULT 'general',
    priority        TEXT NOT NULL DEFAULT 'normal'
                    CHECK(priority IN ('low','normal','high','urgent')),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open','in_progress','resolved','closed','reopened')),
    resolution      TEXT NOT NULL DEFAULT '',
    opened_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    resolved_at     TEXT NOT NULL DEFAULT '',
    created         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_helpdesk_ticket_requester ON helpdesk_ticket(requester_id);
CREATE INDEX IF NOT EXISTS idx_helpdesk_ticket_assignee  ON helpdesk_ticket(assignee_id);
CREATE INDEX IF NOT EXISTS idx_helpdesk_ticket_status    ON helpdesk_ticket(status);

-- ---------------------------------------------------------------------------
-- asset + asset_assignment
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS asset (
    id                   INTEGER PRIMARY KEY,
    asset_code           TEXT NOT NULL UNIQUE,
    name                 TEXT NOT NULL,
    category             TEXT NOT NULL DEFAULT 'general',
    serial_number        TEXT NOT NULL DEFAULT '',
    purchase_date        TEXT NOT NULL DEFAULT '',
    purchase_cost_minor  INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'available'
                         CHECK(status IN ('available','assigned','maintenance','retired','lost')),
    notes                TEXT NOT NULL DEFAULT '',
    created              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_asset_status   ON asset(status);
CREATE INDEX IF NOT EXISTS idx_asset_category ON asset(category);

CREATE TABLE IF NOT EXISTS asset_assignment (
    id            INTEGER PRIMARY KEY,
    asset_id      INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    employee_id   INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    assigned_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    returned_at   TEXT NOT NULL DEFAULT '',
    condition_in  TEXT NOT NULL DEFAULT '',
    condition_out TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_asset_assignment_asset    ON asset_assignment(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_assignment_employee ON asset_assignment(employee_id);

-- ---------------------------------------------------------------------------
-- skill + employee_skill
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS skill (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_skill_category ON skill(category);

CREATE TABLE IF NOT EXISTS employee_skill (
    id            INTEGER PRIMARY KEY,
    employee_id   INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    skill_id      INTEGER NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
    level         TEXT NOT NULL DEFAULT 'intermediate'
                  CHECK(level IN ('beginner','intermediate','advanced','expert')),
    endorsed_by   INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    endorsed_at   TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    created       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    UNIQUE(employee_id, skill_id)
);
CREATE INDEX IF NOT EXISTS idx_employee_skill_employee ON employee_skill(employee_id);
CREATE INDEX IF NOT EXISTS idx_employee_skill_skill    ON employee_skill(skill_id);

-- ---------------------------------------------------------------------------
-- referral
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS referral (
    id                  INTEGER PRIMARY KEY,
    referrer_id         INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    candidate_name      TEXT NOT NULL,
    candidate_email     TEXT NOT NULL DEFAULT '',
    candidate_phone     TEXT NOT NULL DEFAULT '',
    position_applied    TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'submitted'
                        CHECK(status IN ('submitted','screened','interviewed','offered','hired','rejected','withdrawn')),
    bonus_minor         INTEGER NOT NULL DEFAULT 0,
    bonus_paid          INTEGER NOT NULL DEFAULT 0,
    bonus_paid_at       TEXT NOT NULL DEFAULT '',
    submitted_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    notes               TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_referral_referrer ON referral(referrer_id);
CREATE INDEX IF NOT EXISTS idx_referral_status   ON referral(status);

-- ---------------------------------------------------------------------------
-- expense_category + expense
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expense_category (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    code             TEXT NOT NULL DEFAULT '',
    max_amount_minor INTEGER NOT NULL DEFAULT 0,
    notes            TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS expense (
    id                  INTEGER PRIMARY KEY,
    expense_code        TEXT NOT NULL UNIQUE,
    employee_id         INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    category_id         INTEGER REFERENCES expense_category(id) ON DELETE SET NULL,
    amount_minor        INTEGER NOT NULL DEFAULT 0,
    currency            TEXT NOT NULL DEFAULT 'INR',
    expense_date        TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    receipt_path        TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK(status IN ('draft','submitted','approved','reimbursed','rejected')),
    submitted_at        TEXT NOT NULL DEFAULT '',
    approved_by         INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    approved_at         TEXT NOT NULL DEFAULT '',
    reimbursement_date  TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT '',
    created             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_expense_employee ON expense(employee_id);
CREATE INDEX IF NOT EXISTS idx_expense_status   ON expense(status);
CREATE INDEX IF NOT EXISTS idx_expense_category ON expense(category_id);

-- ---------------------------------------------------------------------------
-- survey + survey_question + survey_response
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS survey (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK(status IN ('draft','active','closed','archived')),
    anonymous    INTEGER NOT NULL DEFAULT 0,
    created_by   INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    created      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    closes_at    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_survey_status ON survey(status);

CREATE TABLE IF NOT EXISTS survey_question (
    id            INTEGER PRIMARY KEY,
    survey_id     INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT 'text'
                  CHECK(question_type IN ('text','scale','single_choice','multiple_choice','yes_no')),
    options_json  TEXT NOT NULL DEFAULT '[]',
    required      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_survey_question_survey ON survey_question(survey_id);

CREATE TABLE IF NOT EXISTS survey_response (
    id           INTEGER PRIMARY KEY,
    survey_id    INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    employee_id  INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    submitted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    answers_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_survey_response_survey   ON survey_response(survey_id);
CREATE INDEX IF NOT EXISTS idx_survey_response_employee ON survey_response(employee_id);

-- ---------------------------------------------------------------------------
-- course + course_enrollment   (e-learning / training)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS course (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    instructor      TEXT NOT NULL DEFAULT '',
    duration_hours  REAL NOT NULL DEFAULT 0,
    category        TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('draft','active','archived')),
    created         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);

CREATE TABLE IF NOT EXISTS course_enrollment (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER NOT NULL REFERENCES course(id) ON DELETE CASCADE,
    employee_id   INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    enrolled_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    completed_at  TEXT NOT NULL DEFAULT '',
    score         REAL NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'enrolled'
                  CHECK(status IN ('enrolled','in_progress','completed','dropped')),
    feedback      TEXT NOT NULL DEFAULT '',
    UNIQUE(course_id, employee_id)
);
CREATE INDEX IF NOT EXISTS idx_course_enrollment_course   ON course_enrollment(course_id);
CREATE INDEX IF NOT EXISTS idx_course_enrollment_employee ON course_enrollment(employee_id);

-- ---------------------------------------------------------------------------
-- coaching_session
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coaching_session (
    id               INTEGER PRIMARY KEY,
    mentor_id        INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    mentee_id        INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    scheduled_at     TEXT NOT NULL DEFAULT '',
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    status           TEXT NOT NULL DEFAULT 'scheduled'
                     CHECK(status IN ('scheduled','completed','cancelled','no_show')),
    agenda           TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    action_items     TEXT NOT NULL DEFAULT '',
    created          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_coaching_session_mentor ON coaching_session(mentor_id);
CREATE INDEX IF NOT EXISTS idx_coaching_session_mentee ON coaching_session(mentee_id);

-- ---------------------------------------------------------------------------
-- vehicle + vehicle_assignment   (fleet)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vehicle (
    id                  INTEGER PRIMARY KEY,
    vehicle_code        TEXT NOT NULL UNIQUE,
    registration_number TEXT NOT NULL DEFAULT '',
    make                TEXT NOT NULL DEFAULT '',
    model               TEXT NOT NULL DEFAULT '',
    year                INTEGER NOT NULL DEFAULT 0,
    type                TEXT NOT NULL DEFAULT 'car'
                        CHECK(type IN ('car','bike','van','truck','bus','other')),
    seating_capacity    INTEGER NOT NULL DEFAULT 0,
    fuel_type           TEXT NOT NULL DEFAULT '',
    purchase_date       TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'available'
                        CHECK(status IN ('available','assigned','maintenance','retired')),
    notes               TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vehicle_status ON vehicle(status);

CREATE TABLE IF NOT EXISTS vehicle_assignment (
    id            INTEGER PRIMARY KEY,
    vehicle_id    INTEGER NOT NULL REFERENCES vehicle(id) ON DELETE CASCADE,
    employee_id   INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    assigned_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    returned_at   TEXT NOT NULL DEFAULT '',
    mileage_start INTEGER NOT NULL DEFAULT 0,
    mileage_end   INTEGER NOT NULL DEFAULT 0,
    notes         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vehicle_assignment_vehicle  ON vehicle_assignment(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_assignment_employee ON vehicle_assignment(employee_id);

-- ---------------------------------------------------------------------------
-- meal + meal_order   (lunch / cafeteria)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meal (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT 'veg'
                    CHECK(category IN ('veg','non_veg','vegan','jain')),
    price_minor     INTEGER NOT NULL DEFAULT 0,
    available_days  TEXT NOT NULL DEFAULT '[1,2,3,4,5]',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','discontinued'))
);

CREATE TABLE IF NOT EXISTS meal_order (
    id           INTEGER PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    meal_id      INTEGER NOT NULL REFERENCES meal(id) ON DELETE CASCADE,
    order_date   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d','now','+05:30')),
    quantity     INTEGER NOT NULL DEFAULT 1,
    total_minor  INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'ordered'
                 CHECK(status IN ('ordered','served','cancelled')),
    notes        TEXT NOT NULL DEFAULT '',
    created      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_meal_order_employee ON meal_order(employee_id);
CREATE INDEX IF NOT EXISTS idx_meal_order_date     ON meal_order(order_date);

-- ---------------------------------------------------------------------------
-- shift + shift_assignment
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shift (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    start_time      TEXT NOT NULL DEFAULT '09:00',
    end_time        TEXT NOT NULL DEFAULT '18:00',
    break_minutes   INTEGER NOT NULL DEFAULT 60,
    days_of_week    TEXT NOT NULL DEFAULT '[1,2,3,4,5]',
    is_active       INTEGER NOT NULL DEFAULT 1,
    notes           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS shift_assignment (
    id           INTEGER PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    shift_id     INTEGER NOT NULL REFERENCES shift(id) ON DELETE CASCADE,
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_shift_assignment_employee ON shift_assignment(employee_id);
CREATE INDEX IF NOT EXISTS idx_shift_assignment_shift    ON shift_assignment(shift_id);
CREATE INDEX IF NOT EXISTS idx_shift_assignment_dates    ON shift_assignment(start_date, end_date);

-- ---------------------------------------------------------------------------
-- holiday_calendar + holiday + holiday_calendar_assignment
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS holiday_calendar (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    region      TEXT NOT NULL DEFAULT '',
    year        INTEGER NOT NULL DEFAULT 0,
    is_default  INTEGER NOT NULL DEFAULT 0,
    notes       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS holiday (
    id          INTEGER PRIMARY KEY,
    calendar_id INTEGER NOT NULL REFERENCES holiday_calendar(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    date        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'public'
                CHECK(type IN ('public','optional','restricted','company')),
    description TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_holiday_calendar ON holiday(calendar_id);
CREATE INDEX IF NOT EXISTS idx_holiday_date     ON holiday(date);

CREATE TABLE IF NOT EXISTS holiday_calendar_assignment (
    id            INTEGER PRIMARY KEY,
    calendar_id   INTEGER NOT NULL REFERENCES holiday_calendar(id) ON DELETE CASCADE,
    employee_id   INTEGER REFERENCES employee(id) ON DELETE CASCADE,
    department_id INTEGER REFERENCES department(id) ON DELETE CASCADE,
    location      TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_holiday_assignment_calendar   ON holiday_calendar_assignment(calendar_id);
CREATE INDEX IF NOT EXISTS idx_holiday_assignment_employee   ON holiday_calendar_assignment(employee_id);
CREATE INDEX IF NOT EXISTS idx_holiday_assignment_department ON holiday_calendar_assignment(department_id);

-- ---------------------------------------------------------------------------
-- audit_log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY,
    actor         TEXT NOT NULL DEFAULT 'system',
    action        TEXT NOT NULL,
    entity_type   TEXT NOT NULL DEFAULT '',
    entity_id     INTEGER,
    changes_json  TEXT NOT NULL DEFAULT '{}',
    ip_address    TEXT NOT NULL DEFAULT '',
    user_agent    TEXT NOT NULL DEFAULT '',
    occurred_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor  ON audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_log_when   ON audit_log(occurred_at);

-- ---------------------------------------------------------------------------
-- goal   (OKR / performance goals)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS goal (
    id               INTEGER PRIMARY KEY,
    employee_id      INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    parent_goal_id   INTEGER REFERENCES goal(id) ON DELETE SET NULL,
    title            TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL DEFAULT 'performance'
                     CHECK(category IN ('performance','development','business','behavioural')),
    kra              TEXT NOT NULL DEFAULT '',
    target_date      TEXT NOT NULL DEFAULT '',
    weight           REAL NOT NULL DEFAULT 1.0,
    progress_percent INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK(status IN ('draft','active','at_risk','completed','cancelled')),
    created          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')),
    updated          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_goal_employee ON goal(employee_id);
CREATE INDEX IF NOT EXISTS idx_goal_parent   ON goal(parent_goal_id);
CREATE INDEX IF NOT EXISTS idx_goal_status   ON goal(status);

-- ---------------------------------------------------------------------------
-- self_evaluation   (employee fills own review)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS self_evaluation (
    id                       INTEGER PRIMARY KEY,
    employee_id              INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    review_id                INTEGER REFERENCES performance_review(id) ON DELETE SET NULL,
    period                   TEXT NOT NULL DEFAULT '',
    strengths                TEXT NOT NULL DEFAULT '',
    areas_to_improve         TEXT NOT NULL DEFAULT '',
    achievements             TEXT NOT NULL DEFAULT '',
    goals_for_next_period    TEXT NOT NULL DEFAULT '',
    rating_self              INTEGER NOT NULL DEFAULT 0,
    submitted_at             TEXT NOT NULL DEFAULT '',
    created                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_self_evaluation_employee ON self_evaluation(employee_id);
CREATE INDEX IF NOT EXISTS idx_self_evaluation_review   ON self_evaluation(review_id);

-- ---------------------------------------------------------------------------
-- promotion   (promotions / transfers / lateral moves)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS promotion (
    id                  INTEGER PRIMARY KEY,
    employee_id         INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    type                TEXT NOT NULL DEFAULT 'promotion'
                        CHECK(type IN ('promotion','transfer','lateral','demotion')),
    from_role_id        INTEGER REFERENCES role(id) ON DELETE SET NULL,
    to_role_id          INTEGER REFERENCES role(id) ON DELETE SET NULL,
    from_department_id  INTEGER REFERENCES department(id) ON DELETE SET NULL,
    to_department_id    INTEGER REFERENCES department(id) ON DELETE SET NULL,
    from_salary_minor   INTEGER NOT NULL DEFAULT 0,
    to_salary_minor     INTEGER NOT NULL DEFAULT 0,
    effective_date      TEXT NOT NULL DEFAULT '',
    reason              TEXT NOT NULL DEFAULT '',
    approved_by         INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'proposed'
                        CHECK(status IN ('proposed','approved','effective','rejected','cancelled')),
    notes               TEXT NOT NULL DEFAULT '',
    created             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_promotion_employee ON promotion(employee_id);
CREATE INDEX IF NOT EXISTS idx_promotion_status   ON promotion(status);

-- ---------------------------------------------------------------------------
-- project + timesheet_entry   (HR-adjacent, project time tracking)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    code                TEXT NOT NULL DEFAULT '',
    client              TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('planning','active','on_hold','completed','cancelled')),
    start_date          TEXT NOT NULL DEFAULT '',
    end_date            TEXT NOT NULL DEFAULT '',
    budget_minor        INTEGER NOT NULL DEFAULT 0,
    manager_id          INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    description         TEXT NOT NULL DEFAULT '',
    created             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_project_status  ON project(status);
CREATE INDEX IF NOT EXISTS idx_project_manager ON project(manager_id);

CREATE TABLE IF NOT EXISTS timesheet_entry (
    id           INTEGER PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    project_id   INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    hours        REAL NOT NULL DEFAULT 0,
    billable     INTEGER NOT NULL DEFAULT 1,
    description  TEXT NOT NULL DEFAULT '',
    approved     INTEGER NOT NULL DEFAULT 0,
    approved_by  INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    approved_at  TEXT NOT NULL DEFAULT '',
    created      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_timesheet_entry_employee ON timesheet_entry(employee_id);
CREATE INDEX IF NOT EXISTS idx_timesheet_entry_project  ON timesheet_entry(project_id);
CREATE INDEX IF NOT EXISTS idx_timesheet_entry_date     ON timesheet_entry(date);

-- ---------------------------------------------------------------------------
-- TIER B: salary_advance + approval + tax_slab + payroll_component
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS salary_advance (
    id                  INTEGER PRIMARY KEY,
    employee_id         INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    amount_minor        INTEGER NOT NULL DEFAULT 0,
    request_date        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d','now','+05:30')),
    reason              TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'requested'
                        CHECK(status IN ('requested','approved','disbursed','rejected','repaid','cancelled')),
    approved_by         INTEGER REFERENCES employee(id) ON DELETE SET NULL,
    approved_at         TEXT NOT NULL DEFAULT '',
    disbursed_at        TEXT NOT NULL DEFAULT '',
    repayment_schedule  TEXT NOT NULL DEFAULT '{}',
    notes               TEXT NOT NULL DEFAULT '',
    created             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_salary_advance_employee ON salary_advance(employee_id);
CREATE INDEX IF NOT EXISTS idx_salary_advance_status   ON salary_advance(status);

CREATE TABLE IF NOT EXISTS approval (
    id              INTEGER PRIMARY KEY,
    request_type    TEXT NOT NULL,
    request_id      INTEGER NOT NULL,
    level           INTEGER NOT NULL DEFAULT 1,
    approver_id     INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected','skipped')),
    responded_at    TEXT NOT NULL DEFAULT '',
    comments        TEXT NOT NULL DEFAULT '',
    created         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_approval_request  ON approval(request_type, request_id);
CREATE INDEX IF NOT EXISTS idx_approval_approver ON approval(approver_id);
CREATE INDEX IF NOT EXISTS idx_approval_status   ON approval(status);

CREATE TABLE IF NOT EXISTS tax_slab (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    country             TEXT NOT NULL DEFAULT 'IN',
    regime              TEXT NOT NULL DEFAULT 'new'
                        CHECK(regime IN ('old','new','flat','custom')),
    fy_start            TEXT NOT NULL DEFAULT '',
    slab_min_minor      INTEGER NOT NULL DEFAULT 0,
    slab_max_minor      INTEGER NOT NULL DEFAULT 0,
    rate_percent        REAL NOT NULL DEFAULT 0,
    surcharge_percent   REAL NOT NULL DEFAULT 0,
    notes               TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tax_slab_country_regime ON tax_slab(country, regime, fy_start);

CREATE TABLE IF NOT EXISTS payroll_component (
    id              INTEGER PRIMARY KEY,
    payslip_id      INTEGER NOT NULL REFERENCES payslip(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL DEFAULT 'earning'
                    CHECK(type IN ('earning','deduction','reimbursement','employer_contribution','tax')),
    amount_minor    INTEGER NOT NULL DEFAULT 0,
    calculation     TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_payroll_component_payslip ON payroll_component(payslip_id);

-- Extend payroll_run with off-cycle flag (additional/ad-hoc payouts).
-- NOTE: SQLite ALTER TABLE ADD COLUMN is non-destructive and idempotent only
-- when the column doesn't exist. The migration runner records this file once,
-- so re-running is naturally avoided.
ALTER TABLE payroll_run ADD COLUMN is_off_cycle INTEGER NOT NULL DEFAULT 0;
ALTER TABLE payroll_run ADD COLUMN run_type TEXT NOT NULL DEFAULT 'monthly';

-- Extend exit_record with F&F + gratuity.
ALTER TABLE exit_record ADD COLUMN gratuity_minor INTEGER NOT NULL DEFAULT 0;
ALTER TABLE exit_record ADD COLUMN f_and_f_amount_minor INTEGER NOT NULL DEFAULT 0;
ALTER TABLE exit_record ADD COLUMN f_and_f_settled_at TEXT NOT NULL DEFAULT '';
ALTER TABLE exit_record ADD COLUMN f_and_f_breakdown_json TEXT NOT NULL DEFAULT '{}';

-- ---------------------------------------------------------------------------
-- TIER C: signature_request   (e-Sign via Composio / DocuSign / HelloSign)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signature_request (
    id                  INTEGER PRIMARY KEY,
    employee_id         INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    document_type       TEXT NOT NULL DEFAULT 'contract',
    document_path       TEXT NOT NULL DEFAULT '',
    provider            TEXT NOT NULL DEFAULT 'composio'
                        CHECK(provider IN ('composio','docusign','hellosign','dropbox_sign','manual')),
    provider_request_id TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','sent','viewed','signed','declined','expired','cancelled')),
    signed_at           TEXT NOT NULL DEFAULT '',
    signed_pdf_path     TEXT NOT NULL DEFAULT '',
    expires_at          TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT '',
    created             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))
);
CREATE INDEX IF NOT EXISTS idx_signature_request_employee ON signature_request(employee_id);
CREATE INDEX IF NOT EXISTS idx_signature_request_status   ON signature_request(status);
