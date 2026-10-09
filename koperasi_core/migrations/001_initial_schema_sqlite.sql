-- SQLite Schema for Koperasi Core (Development & Test Hardened)

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('INVITED', 'PENDING_ACTIVATION', 'ACTIVE', 'SUSPENDED', 'DEACTIVATED')) DEFAULT 'ACTIVE',
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token TEXT UNIQUE NOT NULL,
    csrf_token TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_agent TEXT,
    ip_address TEXT
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    module TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    UNIQUE(role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS user_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, role_id)
);

CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL COLLATE NOCASE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    code TEXT UNIQUE NOT NULL COLLATE NOCASE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT UNIQUE NOT NULL COLLATE NOCASE,
    name TEXT NOT NULL,
    nik TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL COLLATE NOCASE,
    phone TEXT,
    department_id INTEGER REFERENCES departments(id),
    position_id INTEGER REFERENCES positions(id),
    manager_id INTEGER REFERENCES employees(id),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'INACTIVE')) DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_number TEXT UNIQUE NOT NULL COLLATE NOCASE,
    employee_id INTEGER UNIQUE REFERENCES employees(id),
    user_id INTEGER UNIQUE REFERENCES users(id),
    name TEXT NOT NULL,
    nik TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL COLLATE NOCASE,
    phone TEXT,
    address TEXT,
    bank_account TEXT,
    membership_date TEXT NOT NULL,
    membership_status TEXT NOT NULL CHECK(membership_status IN ('ACTIVE', 'INACTIVE', 'PENDING')) DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS member_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    mime_type TEXT,
    storage_key TEXT,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS savings_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    account_number TEXT UNIQUE NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('POKOK', 'WAJIB', 'SUKARELA')),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'CLOSED')) DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(member_id, account_type)
);

CREATE TABLE IF NOT EXISTS savings_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES savings_accounts(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id),
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('CREDIT', 'DEBIT')),
    amount TEXT NOT NULL,
    balance_after TEXT NOT NULL,
    reference_type TEXT NOT NULL CHECK(reference_type IN ('OPENING_BALANCE', 'DEPOSIT', 'WITHDRAWAL', 'TRANSFER', 'INTEREST', 'LOAN_INSTALLMENT')),
    reference_id TEXT,
    description TEXT,
    transaction_date TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_number TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    import_type TEXT NOT NULL CHECK(import_type IN ('MEMBER', 'SAVINGS_OPENING_BALANCE', 'LOAN_HISTORY')),
    mode TEXT NOT NULL CHECK(mode IN ('ADD_ONLY', 'UPDATE_EXISTING', 'UPSERT')),
    total_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    invalid_rows INTEGER NOT NULL DEFAULT 0,
    created_rows INTEGER NOT NULL DEFAULT 0,
    updated_rows INTEGER NOT NULL DEFAULT 0,
    failed_rows INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN ('PENDING_PREVIEW', 'VALIDATED', 'COMMITTED', 'FAILED', 'CANCELLED')) DEFAULT 'PENDING_PREVIEW',
    error_summary TEXT,
    raw_data_path TEXT,
    imported_by INTEGER REFERENCES users(id),
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS savings_opening_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES savings_accounts(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    account_type TEXT NOT NULL,
    amount TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    source_batch_id INTEGER REFERENCES import_batches(id),
    reference TEXT,
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loan_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_number TEXT UNIQUE NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id),
    amount TEXT NOT NULL,
    tenor_months INTEGER NOT NULL,
    interest_rate TEXT NOT NULL DEFAULT '0.0100',
    monthly_installment TEXT NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SUBMITTED', 'REVISION_REQUESTED', 'APPROVED_BY_MANAGER', 'APPROVED_BY_KETUA', 'REJECTED', 'WAITING_DISBURSEMENT', 'DISBURSED', 'CANCELLED')) DEFAULT 'SUBMITTED',
    current_step TEXT NOT NULL DEFAULT 'MANAGER',
    assigned_manager_id INTEGER REFERENCES users(id),
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loan_approval_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES loan_applications(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    approver_role TEXT NOT NULL,
    approver_user_id INTEGER REFERENCES users(id),
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'REQUEST_REVISION', 'SKIPPED')) DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loan_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES loan_applications(id) ON DELETE CASCADE,
    approver_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('APPROVE', 'REJECT', 'REQUEST_REVISION')),
    comment TEXT,
    before_status TEXT NOT NULL,
    after_status TEXT NOT NULL,
    audit_reference TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_number TEXT UNIQUE NOT NULL,
    application_id INTEGER UNIQUE NOT NULL REFERENCES loan_applications(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    principal_amount TEXT NOT NULL,
    total_amount TEXT NOT NULL,
    outstanding_amount TEXT NOT NULL,
    tenor_months INTEGER NOT NULL,
    monthly_installment TEXT NOT NULL,
    start_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'PAID_OFF', 'DEFAULTED')) DEFAULT 'ACTIVE',
    disbursed_by INTEGER REFERENCES users(id),
    disbursed_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loan_installments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    installment_number INTEGER NOT NULL,
    due_date TEXT NOT NULL,
    amount TEXT NOT NULL,
    principal_portion TEXT NOT NULL,
    interest_portion TEXT NOT NULL,
    paid_amount TEXT NOT NULL DEFAULT '0.00',
    paid_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'PAID', 'PARTIAL', 'OVERDUE')) DEFAULT 'PENDING',
    payment_reference TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS financial_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_number TEXT UNIQUE NOT NULL,
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('INFLOW', 'OUTFLOW')),
    category TEXT NOT NULL CHECK(category IN ('SAVINGS_DEPOSIT', 'LOAN_DISBURSEMENT', 'LOAN_INSTALLMENT', 'SAVINGS_WITHDRAWAL', 'OPENING_BALANCE', 'UNIT_DEPOSIT')),
    amount TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    reference_type TEXT,
    reference_id TEXT,
    description TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(category, idempotency_key)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_number TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    owner_user_id INTEGER REFERENCES users(id),
    reference_type TEXT,
    reference_id TEXT,
    file_path TEXT,
    storage_key TEXT,
    verification_status TEXT NOT NULL CHECK(verification_status IN ('VERIFIED', 'REVOKED', 'PENDING')) DEFAULT 'VERIFIED',
    verified_by INTEGER REFERENCES users(id),
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    link TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS qr_verification_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT UNIQUE NOT NULL,
    token_display TEXT NOT NULL,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    expires_at TEXT,
    is_revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT,
    revoked_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS import_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    raw_data_json TEXT NOT NULL,
    normalized_data_json TEXT,
    status TEXT NOT NULL CHECK(status IN ('VALID', 'INVALID', 'WARNING', 'SKIPPED', 'COMMITTED', 'FAILED')),
    action_type TEXT NOT NULL CHECK(action_type IN ('NEW', 'UPDATE', 'DUPLICATE', 'NONE')),
    errors_json TEXT,
    warnings_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER REFERENCES users(id),
    actor_name TEXT,
    actor_role TEXT,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT,
    before_state_json TEXT,
    after_state_json TEXT,
    result TEXT NOT NULL CHECK(result IN ('SUCCESS', 'FAILURE')) DEFAULT 'SUCCESS',
    ip_address TEXT,
    user_agent TEXT,
    correlation_id TEXT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invitation_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS business_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    manager_name TEXT,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS unit_financial_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL REFERENCES business_units(id) ON DELETE CASCADE,
    period_type TEXT NOT NULL CHECK(period_type IN ('MONTHLY', 'ANNUAL')) DEFAULT 'MONTHLY',
    period_year INTEGER NOT NULL,
    period_month INTEGER,
    cash_and_bank TEXT NOT NULL DEFAULT '0.00',
    inventory_value TEXT NOT NULL DEFAULT '0.00',
    receivables TEXT NOT NULL DEFAULT '0.00',
    fixed_assets TEXT NOT NULL DEFAULT '0.00',
    other_assets TEXT NOT NULL DEFAULT '0.00',
    total_assets TEXT NOT NULL DEFAULT '0.00',
    payables TEXT NOT NULL DEFAULT '0.00',
    unit_capital TEXT NOT NULL DEFAULT '0.00',
    gross_revenue TEXT NOT NULL DEFAULT '0.00',
    cogs TEXT NOT NULL DEFAULT '0.00',
    gross_profit TEXT NOT NULL DEFAULT '0.00',
    operational_expenses TEXT NOT NULL DEFAULT '0.00',
    net_profit TEXT NOT NULL DEFAULT '0.00',
    cash_deposit_to_parent TEXT NOT NULL DEFAULT '0.00',
    deposit_date TEXT,
    notes TEXT,
    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'SUBMITTED', 'VERIFIED')) DEFAULT 'SUBMITTED',
    reported_by INTEGER REFERENCES users(id),
    verified_by INTEGER REFERENCES users(id),
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(unit_id, period_type, period_year, period_month)
);

CREATE TABLE IF NOT EXISTS system_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key TEXT UNIQUE NOT NULL,
    setting_value TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_members_number ON members(member_number);
CREATE INDEX IF NOT EXISTS idx_members_nik ON members(nik);
CREATE INDEX IF NOT EXISTS idx_members_user_id ON members(user_id);
CREATE INDEX IF NOT EXISTS idx_members_emp_id ON members(employee_id);
CREATE INDEX IF NOT EXISTS idx_employees_emp_id ON employees(employee_id);
CREATE INDEX IF NOT EXISTS idx_savings_account ON savings_transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_savings_member ON savings_transactions(member_id);
CREATE INDEX IF NOT EXISTS idx_loan_apps_member ON loan_applications(member_id);
CREATE INDEX IF NOT EXISTS idx_loans_member ON loans(member_id);
CREATE INDEX IF NOT EXISTS idx_installments_loan ON loan_installments(loan_id);
CREATE INDEX IF NOT EXISTS idx_import_rows_batch ON import_rows(batch_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_unit_reports ON unit_financial_reports(unit_id, period_year);
