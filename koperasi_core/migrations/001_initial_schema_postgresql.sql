-- PostgreSQL Schema for Koperasi Core (Production Hardened)
-- Target: Render PostgreSQL (pg15/pg16)

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(50) PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL CHECK(status IN ('INVITED', 'PENDING_ACTIVATION', 'ACTIVE', 'SUSPENDED', 'DEACTIVATED')) DEFAULT 'ACTIVE',
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMP WITH TIME ZONE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    csrf_token VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_agent TEXT,
    ip_address VARCHAR(45)
);

CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(150) NOT NULL,
    module VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    id SERIAL PRIMARY KEY,
    role_id INT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INT NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    UNIQUE(role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS user_roles (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, role_id)
);

CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(150) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    department_id INT NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    code VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(150) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    employee_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    nik VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(50),
    department_id INT REFERENCES departments(id),
    position_id INT REFERENCES positions(id),
    manager_id INT REFERENCES employees(id),
    status VARCHAR(50) NOT NULL CHECK(status IN ('ACTIVE', 'INACTIVE')) DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS members (
    id SERIAL PRIMARY KEY,
    member_number VARCHAR(50) UNIQUE NOT NULL,
    employee_id INT UNIQUE REFERENCES employees(id),
    user_id INT UNIQUE REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    nik VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(50),
    address TEXT,
    bank_account VARCHAR(100),
    membership_date DATE NOT NULL,
    membership_status VARCHAR(50) NOT NULL CHECK(membership_status IN ('ACTIVE', 'INACTIVE', 'PENDING')) DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS member_documents (
    id SERIAL PRIMARY KEY,
    member_id INT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    document_type VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT,
    mime_type VARCHAR(100),
    storage_key VARCHAR(255),
    uploaded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS savings_accounts (
    id SERIAL PRIMARY KEY,
    member_id INT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    account_number VARCHAR(100) UNIQUE NOT NULL,
    account_type VARCHAR(50) NOT NULL CHECK(account_type IN ('POKOK', 'WAJIB', 'SUKARELA')),
    status VARCHAR(50) NOT NULL CHECK(status IN ('ACTIVE', 'CLOSED')) DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(member_id, account_type)
);

CREATE TABLE IF NOT EXISTS savings_transactions (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES savings_accounts(id) ON DELETE CASCADE,
    member_id INT NOT NULL REFERENCES members(id),
    transaction_type VARCHAR(20) NOT NULL CHECK(transaction_type IN ('CREDIT', 'DEBIT')),
    amount NUMERIC(18,2) NOT NULL,
    balance_after NUMERIC(18,2) NOT NULL,
    reference_type VARCHAR(50) NOT NULL CHECK(reference_type IN ('OPENING_BALANCE', 'DEPOSIT', 'WITHDRAWAL', 'TRANSFER', 'INTEREST', 'LOAN_INSTALLMENT')),
    reference_id VARCHAR(100),
    description TEXT,
    transaction_date DATE NOT NULL,
    created_by INT REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_batches (
    id SERIAL PRIMARY KEY,
    batch_number VARCHAR(100) UNIQUE NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    import_type VARCHAR(50) NOT NULL CHECK(import_type IN ('MEMBER', 'SAVINGS_OPENING_BALANCE', 'LOAN_HISTORY')),
    mode VARCHAR(50) NOT NULL CHECK(mode IN ('ADD_ONLY', 'UPDATE_EXISTING', 'UPSERT')),
    total_rows INT NOT NULL DEFAULT 0,
    valid_rows INT NOT NULL DEFAULT 0,
    invalid_rows INT NOT NULL DEFAULT 0,
    created_rows INT NOT NULL DEFAULT 0,
    updated_rows INT NOT NULL DEFAULT 0,
    failed_rows INT NOT NULL DEFAULT 0,
    warning_count INT NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL CHECK(status IN ('PENDING_PREVIEW', 'VALIDATED', 'COMMITTED', 'FAILED', 'CANCELLED')) DEFAULT 'PENDING_PREVIEW',
    error_summary TEXT,
    raw_data_path TEXT,
    imported_by INT REFERENCES users(id),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS savings_opening_balances (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES savings_accounts(id),
    member_id INT NOT NULL REFERENCES members(id),
    account_type VARCHAR(50) NOT NULL,
    amount NUMERIC(18,2) NOT NULL,
    effective_date DATE NOT NULL,
    source_batch_id INT REFERENCES import_batches(id),
    reference VARCHAR(100),
    notes TEXT,
    created_by INT REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loan_applications (
    id SERIAL PRIMARY KEY,
    application_number VARCHAR(100) UNIQUE NOT NULL,
    member_id INT NOT NULL REFERENCES members(id),
    amount NUMERIC(18,2) NOT NULL,
    tenor_months INT NOT NULL,
    interest_rate NUMERIC(6,4) NOT NULL DEFAULT 0.0100,
    monthly_installment NUMERIC(18,2) NOT NULL,
    purpose TEXT NOT NULL,
    status VARCHAR(50) NOT NULL CHECK(status IN ('SUBMITTED', 'REVISION_REQUESTED', 'APPROVED_BY_MANAGER', 'APPROVED_BY_KETUA', 'REJECTED', 'WAITING_DISBURSEMENT', 'DISBURSED', 'CANCELLED')) DEFAULT 'SUBMITTED',
    current_step VARCHAR(50) NOT NULL DEFAULT 'MANAGER',
    assigned_manager_id INT REFERENCES users(id),
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loan_approval_steps (
    id SERIAL PRIMARY KEY,
    application_id INT NOT NULL REFERENCES loan_applications(id) ON DELETE CASCADE,
    step_order INT NOT NULL,
    approver_role VARCHAR(50) NOT NULL,
    approver_user_id INT REFERENCES users(id),
    status VARCHAR(50) NOT NULL CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'REQUEST_REVISION', 'SKIPPED')) DEFAULT 'PENDING',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loan_approvals (
    id SERIAL PRIMARY KEY,
    application_id INT NOT NULL REFERENCES loan_applications(id) ON DELETE CASCADE,
    approver_id INT NOT NULL REFERENCES users(id),
    role VARCHAR(50) NOT NULL,
    decision VARCHAR(50) NOT NULL CHECK(decision IN ('APPROVE', 'REJECT', 'REQUEST_REVISION')),
    comment TEXT,
    before_status VARCHAR(50) NOT NULL,
    after_status VARCHAR(50) NOT NULL,
    audit_reference VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loans (
    id SERIAL PRIMARY KEY,
    loan_number VARCHAR(100) UNIQUE NOT NULL,
    application_id INT UNIQUE NOT NULL REFERENCES loan_applications(id),
    member_id INT NOT NULL REFERENCES members(id),
    principal_amount NUMERIC(18,2) NOT NULL,
    total_amount NUMERIC(18,2) NOT NULL,
    outstanding_amount NUMERIC(18,2) NOT NULL,
    tenor_months INT NOT NULL,
    monthly_installment NUMERIC(18,2) NOT NULL,
    start_date DATE NOT NULL,
    due_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL CHECK(status IN ('ACTIVE', 'PAID_OFF', 'DEFAULTED')) DEFAULT 'ACTIVE',
    disbursed_by INT REFERENCES users(id),
    disbursed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loan_installments (
    id SERIAL PRIMARY KEY,
    loan_id INT NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    installment_number INT NOT NULL,
    due_date DATE NOT NULL,
    amount NUMERIC(18,2) NOT NULL,
    principal_portion NUMERIC(18,2) NOT NULL,
    interest_portion NUMERIC(18,2) NOT NULL,
    paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    paid_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) NOT NULL CHECK(status IN ('PENDING', 'PAID', 'PARTIAL', 'OVERDUE')) DEFAULT 'PENDING',
    payment_reference VARCHAR(100),
    idempotency_key VARCHAR(255) UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financial_transactions (
    id SERIAL PRIMARY KEY,
    transaction_number VARCHAR(100) UNIQUE NOT NULL,
    transaction_type VARCHAR(20) NOT NULL CHECK(transaction_type IN ('INFLOW', 'OUTFLOW')),
    category VARCHAR(50) NOT NULL CHECK(category IN ('SAVINGS_DEPOSIT', 'LOAN_DISBURSEMENT', 'LOAN_INSTALLMENT', 'SAVINGS_WITHDRAWAL', 'OPENING_BALANCE', 'UNIT_DEPOSIT')),
    amount NUMERIC(18,2) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    reference_type VARCHAR(50),
    reference_id VARCHAR(100),
    description TEXT,
    created_by INT REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_category_idempotency UNIQUE(category, idempotency_key)
);

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    document_number VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    document_type VARCHAR(100) NOT NULL,
    owner_user_id INT REFERENCES users(id),
    reference_type VARCHAR(50),
    reference_id VARCHAR(100),
    file_path TEXT,
    storage_key VARCHAR(255),
    verification_status VARCHAR(50) NOT NULL CHECK(verification_status IN ('VERIFIED', 'REVOKED', 'PENDING')) DEFAULT 'VERIFIED',
    verified_by INT REFERENCES users(id),
    verified_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    link VARCHAR(255),
    is_read INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qr_verification_tokens (
    id SERIAL PRIMARY KEY,
    token_hash VARCHAR(64) UNIQUE NOT NULL,
    token_display VARCHAR(32) NOT NULL,
    document_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    expires_at TIMESTAMP WITH TIME ZONE,
    is_revoked INT NOT NULL DEFAULT 0,
    revoked_at TIMESTAMP WITH TIME ZONE,
    revoked_by INT REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_rows (
    id SERIAL PRIMARY KEY,
    batch_id INT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    row_number INT NOT NULL,
    raw_data_json TEXT NOT NULL,
    normalized_data_json TEXT,
    status VARCHAR(50) NOT NULL CHECK(status IN ('VALID', 'INVALID', 'WARNING', 'SKIPPED', 'COMMITTED', 'FAILED')),
    action_type VARCHAR(50) NOT NULL CHECK(action_type IN ('NEW', 'UPDATE', 'DUPLICATE', 'NONE')),
    errors_json TEXT,
    warnings_json TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    actor_id INT REFERENCES users(id),
    actor_name VARCHAR(255),
    actor_role VARCHAR(100),
    action VARCHAR(100) NOT NULL,
    entity VARCHAR(100) NOT NULL,
    entity_id VARCHAR(100),
    before_state_json TEXT,
    after_state_json TEXT,
    result VARCHAR(50) NOT NULL CHECK(result IN ('SUCCESS', 'FAILURE')) DEFAULT 'SUCCESS',
    ip_address VARCHAR(45),
    user_agent TEXT,
    correlation_id VARCHAR(100),
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invitation_tokens (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    token_hash VARCHAR(64) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_by INT REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    token_hash VARCHAR(64) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS business_units (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    manager_name VARCHAR(255),
    description TEXT,
    is_active INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS unit_financial_reports (
    id SERIAL PRIMARY KEY,
    unit_id INT NOT NULL REFERENCES business_units(id) ON DELETE CASCADE,
    period_type VARCHAR(20) NOT NULL CHECK(period_type IN ('MONTHLY', 'ANNUAL')) DEFAULT 'MONTHLY',
    period_year INT NOT NULL,
    period_month INT,
    cash_and_bank NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    inventory_value NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    receivables NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    fixed_assets NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    other_assets NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    total_assets NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    payables NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    unit_capital NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    gross_revenue NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    cogs NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    gross_profit NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    operational_expenses NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    net_profit NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    cash_deposit_to_parent NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    deposit_date DATE,
    notes TEXT,
    status VARCHAR(50) NOT NULL CHECK(status IN ('DRAFT', 'SUBMITTED', 'VERIFIED')) DEFAULT 'SUBMITTED',
    reported_by INT REFERENCES users(id),
    verified_by INT REFERENCES users(id),
    verified_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(unit_id, period_type, period_year, period_month)
);

CREATE TABLE IF NOT EXISTS system_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value TEXT NOT NULL,
    category VARCHAR(50) NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
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
CREATE INDEX IF NOT EXISTS idx_qr_token_hash ON qr_verification_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_unit_reports ON unit_financial_reports(unit_id, period_year);


-- Seed Core Roles
INSERT INTO roles (code, name, description) VALUES
    ('SUPER_ADMIN', 'Super Admin', 'Sistem & keamanan tertinggi'),
    ('ADMIN_KOPERASI', 'Admin Koperasi', 'Operasional & keanggotaan'),
    ('KETUA', 'Ketua Koperasi', 'Persetujuan kebijakan & pinjaman'),
    ('BENDAHARA', 'Bendahara', 'Pencairan kas & keuangan'),
    ('ATASAN_APPROVER', 'Atasan Approver', 'Persetujuan bawahan'),
    ('ANGGOTA', 'Anggota', 'Layanan mandiri anggota')
ON CONFLICT (code) DO NOTHING;

-- Seed Core Permissions
INSERT INTO permissions (code, name, module) VALUES
    ('member.read_all', 'Lihat Semua Anggota', 'MEMBER'),
    ('member.read_own', 'Lihat Data Sendiri', 'MEMBER'),
    ('member.create', 'Daftar Anggota Baru', 'MEMBER'),
    ('member.update', 'Ubah Data Anggota', 'MEMBER'),
    ('member.import', 'Bulk Import Anggota', 'MEMBER'),
    ('savings.read_all', 'Lihat Semua Simpanan', 'SAVINGS'),
    ('savings.read_own', 'Lihat Simpanan Sendiri', 'SAVINGS'),
    ('savings.create', 'Setoran Simpanan', 'SAVINGS'),
    ('savings.opening_balance', 'Catat Saldo Awal', 'SAVINGS'),
    ('loan.read_all', 'Lihat Semua Pinjaman', 'LOAN'),
    ('loan.read_own', 'Lihat Pinjaman Sendiri', 'LOAN'),
    ('loan.apply', 'Pengajuan Pinjaman', 'LOAN'),
    ('loan.approve', 'Persetujuan Pinjaman', 'LOAN'),
    ('loan.approve_manager', 'Persetujuan Atasan Langsung', 'LOAN'),
    ('loan.approve_chairman', 'Persetujuan Ketua Koperasi', 'LOAN'),
    ('loan.disburse', 'Pencairan Pinjaman', 'LOAN'),
    ('installment.create', 'Pembayaran Angsuran', 'LOAN'),
    ('document.read_all', 'Lihat Semua Dokumen', 'DOCUMENT'),
    ('document.read_own', 'Lihat Dokumen Sendiri', 'DOCUMENT'),
    ('document.verify', 'Verifikasi Dokumen', 'DOCUMENT'),
    ('document.revoke', 'Cabut Dokumen', 'DOCUMENT'),
    ('report.read', 'Lihat Laporan', 'REPORT'),
    ('settings.manage', 'Kelola Pengaturan', 'SETTINGS'),
    ('audit.read', 'Lihat Audit Trail', 'AUDIT'),
    ('user.manage', 'Kelola Pengguna', 'USER')
ON CONFLICT (code) DO NOTHING;

-- Link Standard Permissions to Roles
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.code = 'ADMIN_KOPERASI' AND p.code IN (
    'member.read_all', 'member.create', 'member.update', 'member.import',
    'savings.read_all', 'savings.create', 'savings.opening_balance',
    'loan.read_all', 'loan.create', 'document.read_all', 'document.verify',
    'document.revoke', 'report.read', 'settings.manage', 'audit.read', 'user.manage'
)
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.code = 'KETUA' AND p.code IN (
    'member.read_all', 'savings.read_all', 'loan.read_all',
    'loan.approve', 'loan.approve_chairman', 'report.read', 'audit.read'
)
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.code = 'BENDAHARA' AND p.code IN (
    'member.read_all', 'savings.read_all', 'loan.read_all',
    'loan.disburse', 'installment.create', 'savings.create', 'report.read'
)
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.code = 'ATASAN_APPROVER' AND p.code IN (
    'loan.approve', 'loan.approve_manager'
)
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.code = 'ANGGOTA' AND p.code IN (
    'member.read_own', 'savings.read_own', 'loan.read_own', 'loan.apply',
    'document.read_own'
)
ON CONFLICT (role_id, permission_id) DO NOTHING;
