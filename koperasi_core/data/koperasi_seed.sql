BEGIN TRANSACTION;
CREATE TABLE audit_logs (
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
INSERT INTO "audit_logs" VALUES(1,1,'SYSTEM_SEED','SYSTEM','USER_CREATED','users','1',NULL,'{"email": "superadmin@koperasi.local", "full_name": "Super Administrator", "status": "ACTIVE"}','SUCCESS',NULL,NULL,'b92eced3cacf5962','2026-10-06 15:49:46');
INSERT INTO "audit_logs" VALUES(2,2,'SYSTEM_SEED','SYSTEM','USER_CREATED','users','2',NULL,'{"email": "admin@koperasi.local", "full_name": "Admin Koperasi", "status": "ACTIVE"}','SUCCESS',NULL,NULL,'8c059f21255fbd90','2026-10-06 15:49:46');
INSERT INTO "audit_logs" VALUES(3,3,'SYSTEM_SEED','SYSTEM','USER_CREATED','users','3',NULL,'{"email": "ketua@koperasi.local", "full_name": "Drs. Hendro Wibowo (Ketua)", "status": "ACTIVE"}','SUCCESS',NULL,NULL,'8811601155acfb93','2026-10-06 15:49:46');
INSERT INTO "audit_logs" VALUES(4,4,'SYSTEM_SEED','SYSTEM','USER_CREATED','users','4',NULL,'{"email": "bendahara@koperasi.local", "full_name": "Siti Rahmawati (Bendahara)", "status": "ACTIVE"}','SUCCESS',NULL,NULL,'41ad740fcb4af20e','2026-10-06 15:49:47');
INSERT INTO "audit_logs" VALUES(5,5,'SYSTEM_SEED','SYSTEM','USER_CREATED','users','5',NULL,'{"email": "manager.budi@koperasi.local", "full_name": "Budi Santoso", "status": "ACTIVE"}','SUCCESS',NULL,NULL,'56cd1fedce8b9b6f','2026-10-06 15:49:47');
INSERT INTO "audit_logs" VALUES(6,6,'SYSTEM_SEED','SYSTEM','USER_CREATED','users','6',NULL,'{"email": "member.andi@koperasi.local", "full_name": "Andi Pratama", "status": "ACTIVE"}','SUCCESS',NULL,NULL,'94d0ea4e2a4f8b37','2026-10-06 15:49:47');
CREATE TABLE departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL COLLATE NOCASE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO "departments" VALUES(1,'IT','Information Technology','2026-10-06 15:49:45');
INSERT INTO "departments" VALUES(2,'HR','Human Resources','2026-10-06 15:49:45');
INSERT INTO "departments" VALUES(3,'FIN','Finance & Accounting','2026-10-06 15:49:45');
INSERT INTO "departments" VALUES(4,'OPS','Operations','2026-10-06 15:49:45');
CREATE TABLE documents (
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
CREATE TABLE employees (
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
INSERT INTO "employees" VALUES(1,'EMP-001','Budi Santoso','3171010101800001','manager.budi@koperasi.local','081234567890',1,2,NULL,'ACTIVE','2026-10-06 15:49:47','2026-10-06 15:49:47');
INSERT INTO "employees" VALUES(2,'EMP-002','Andi Pratama','3171010202900002','member.andi@koperasi.local','081234567891',1,1,1,'ACTIVE','2026-10-06 15:49:47','2026-10-06 15:49:47');
CREATE TABLE financial_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_number TEXT UNIQUE NOT NULL,
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('INFLOW', 'OUTFLOW')),
    category TEXT NOT NULL CHECK(category IN ('SAVINGS_DEPOSIT', 'LOAN_DISBURSEMENT', 'LOAN_INSTALLMENT', 'SAVINGS_WITHDRAWAL', 'OPENING_BALANCE')),
    amount TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    reference_type TEXT,
    reference_id TEXT,
    description TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO "financial_transactions" VALUES(1,'FT-INIT-POKOK-001','INFLOW','OPENING_BALANCE','500000.00','IDEMP-INIT-POKOK-001','SAVINGS_ACCOUNT','1','Setoran Awal Simpanan POKOK Anggota MEM-001',2,'2026-10-06 15:49:47');
INSERT INTO "financial_transactions" VALUES(2,'FT-INIT-WAJIB-001','INFLOW','OPENING_BALANCE','100000.00','IDEMP-INIT-WAJIB-001','SAVINGS_ACCOUNT','2','Setoran Awal Simpanan WAJIB Anggota MEM-001',2,'2026-10-06 15:49:47');
INSERT INTO "financial_transactions" VALUES(3,'FT-INIT-SUKARELA-001','INFLOW','OPENING_BALANCE','250000.00','IDEMP-INIT-SUKARELA-001','SAVINGS_ACCOUNT','3','Setoran Awal Simpanan SUKARELA Anggota MEM-001',2,'2026-10-06 15:49:47');
CREATE TABLE import_batches (
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
CREATE TABLE import_rows (
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
CREATE TABLE invitation_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    token TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE loan_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_number TEXT UNIQUE NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id),
    amount TEXT NOT NULL,
    tenor_months INTEGER NOT NULL,
    interest_rate TEXT NOT NULL DEFAULT '0.01',
    monthly_installment TEXT NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SUBMITTED', 'REVISION_REQUESTED', 'APPROVED_BY_MANAGER', 'APPROVED_BY_KETUA', 'REJECTED', 'WAITING_DISBURSEMENT', 'DISBURSED', 'CANCELLED')) DEFAULT 'SUBMITTED',
    current_step TEXT NOT NULL DEFAULT 'MANAGER',
    assigned_manager_id INTEGER REFERENCES users(id),
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE loan_approval_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES loan_applications(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    approver_role TEXT NOT NULL,
    approver_user_id INTEGER REFERENCES users(id),
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'REQUEST_REVISION', 'SKIPPED')) DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE loan_approvals (
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
CREATE TABLE loan_installments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    installment_number INTEGER NOT NULL,
    due_date TEXT NOT NULL,
    amount TEXT NOT NULL,
    principal_portion TEXT NOT NULL,
    interest_portion TEXT NOT NULL,
    paid_amount TEXT NOT NULL DEFAULT '0',
    paid_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'PAID', 'PARTIAL', 'OVERDUE')) DEFAULT 'PENDING',
    payment_reference TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE loans (
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
CREATE TABLE member_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    mime_type TEXT,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE members (
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
INSERT INTO "members" VALUES(1,'MEM-001',2,6,'Andi Pratama','3171010202900002','member.andi@koperasi.local','081234567891','Jl. Merdeka No. 10, Jakarta Pusat','BCA 1234567890','2024-01-15','ACTIVE','2026-10-06 15:49:47','2026-10-06 15:49:47');
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    link TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    token TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    module TEXT NOT NULL
);
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    code TEXT UNIQUE NOT NULL COLLATE NOCASE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO "positions" VALUES(1,1,'ENG','Software Engineer','2026-10-06 15:49:45');
INSERT INTO "positions" VALUES(2,1,'IT_HEAD','IT Department Head','2026-10-06 15:49:45');
INSERT INTO "positions" VALUES(3,2,'HR_SPEC','HR Specialist','2026-10-06 15:49:45');
INSERT INTO "positions" VALUES(4,2,'HR_HEAD','HR Department Head','2026-10-06 15:49:45');
INSERT INTO "positions" VALUES(5,3,'FIN_OFF','Finance Officer','2026-10-06 15:49:45');
INSERT INTO "positions" VALUES(6,4,'OPS_STAFF','Operations Staff','2026-10-06 15:49:45');
CREATE TABLE qr_verification_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    expires_at TEXT,
    is_revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT,
    revoked_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT
);
INSERT INTO "roles" VALUES(1,'SUPER_ADMIN','Super Admin','Full system administration, security, audit, user management');
INSERT INTO "roles" VALUES(2,'ADMIN_KOPERASI','Admin Koperasi','Member management, imports, verifications, operational transactions');
INSERT INTO "roles" VALUES(3,'ANGGOTA','Anggota','Member self-service: personal profile, savings, loan applications');
INSERT INTO "roles" VALUES(4,'KETUA','Ketua Koperasi','Final executive loan approvals, cooperative policy and reports');
INSERT INTO "roles" VALUES(5,'ATASAN_APPROVER','Atasan / Approver','Direct manager line approval for subordinate loan applications');
INSERT INTO "roles" VALUES(6,'BENDAHARA','Bendahara','Financial disbursement, collections, and cash flow control');
CREATE TABLE savings_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    account_number TEXT UNIQUE NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('POKOK', 'WAJIB', 'SUKARELA')),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'CLOSED')) DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(member_id, account_type)
);
INSERT INTO "savings_accounts" VALUES(1,1,'SA-POK-MEM-001','POKOK','ACTIVE','2026-10-06 15:49:47');
INSERT INTO "savings_accounts" VALUES(2,1,'SA-WAJ-MEM-001','WAJIB','ACTIVE','2026-10-06 15:49:47');
INSERT INTO "savings_accounts" VALUES(3,1,'SA-SUK-MEM-001','SUKARELA','ACTIVE','2026-10-06 15:49:47');
CREATE TABLE savings_opening_balances (
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
INSERT INTO "savings_opening_balances" VALUES(1,1,1,'POKOK','500000.00','2024-01-15',NULL,'INIT-SEED','Opening balance seed data',2,'2026-10-06 15:49:47');
INSERT INTO "savings_opening_balances" VALUES(2,2,1,'WAJIB','100000.00','2024-01-15',NULL,'INIT-SEED','Opening balance seed data',2,'2026-10-06 15:49:47');
INSERT INTO "savings_opening_balances" VALUES(3,3,1,'SUKARELA','250000.00','2024-01-15',NULL,'INIT-SEED','Opening balance seed data',2,'2026-10-06 15:49:47');
CREATE TABLE savings_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES savings_accounts(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id),
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('CREDIT', 'DEBIT')),
    amount TEXT NOT NULL, -- Stored as exact decimal numeric string
    balance_after TEXT NOT NULL,
    reference_type TEXT NOT NULL CHECK(reference_type IN ('OPENING_BALANCE', 'DEPOSIT', 'WITHDRAWAL', 'TRANSFER', 'INTEREST', 'LOAN_INSTALLMENT')),
    reference_id TEXT,
    description TEXT,
    transaction_date TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO "savings_transactions" VALUES(1,1,1,'CREDIT','500000.00','500000.00','OPENING_BALANCE','INIT-SEED','Saldo Awal Simpanan POKOK','2024-01-15',2,'2026-10-06 15:49:47');
INSERT INTO "savings_transactions" VALUES(2,2,1,'CREDIT','100000.00','100000.00','OPENING_BALANCE','INIT-SEED','Saldo Awal Simpanan WAJIB','2024-01-15',2,'2026-10-06 15:49:47');
INSERT INTO "savings_transactions" VALUES(3,3,1,'CREDIT','250000.00','250000.00','OPENING_BALANCE','INIT-SEED','Saldo Awal Simpanan SUKARELA','2024-01-15',2,'2026-10-06 15:49:47');
CREATE TABLE user_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, role_id)
);
INSERT INTO "user_roles" VALUES(1,1,1,'2026-10-06 15:49:46');
INSERT INTO "user_roles" VALUES(2,2,2,'2026-10-06 15:49:46');
INSERT INTO "user_roles" VALUES(3,3,4,'2026-10-06 15:49:46');
INSERT INTO "user_roles" VALUES(4,3,5,'2026-10-06 15:49:46');
INSERT INTO "user_roles" VALUES(5,4,6,'2026-10-06 15:49:47');
INSERT INTO "user_roles" VALUES(6,5,5,'2026-10-06 15:49:47');
INSERT INTO "user_roles" VALUES(7,6,3,'2026-10-06 15:49:47');
CREATE TABLE user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_agent TEXT,
    ip_address TEXT
);
CREATE TABLE users (
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
INSERT INTO "users" VALUES(1,'superadmin@koperasi.local','pbkdf2_sha256$260000$465edc92789e34521423b21a19d48416$3da37f7e40bebd50812e2bdbaf293d0217f0bd49addebd410094ca731bc34c90','Super Administrator','ACTIVE',0,NULL,NULL,'2026-10-06 15:49:46','2026-10-06 15:49:46');
INSERT INTO "users" VALUES(2,'admin@koperasi.local','pbkdf2_sha256$260000$539aa7a4921adeec5cb9303d62a772b4$f87a7404cd7f98625c0b2aa78f92a60fe74e4daf8db8829a9f5bc94b253da51c','Admin Koperasi','ACTIVE',0,NULL,NULL,'2026-10-06 15:49:46','2026-10-06 15:49:46');
INSERT INTO "users" VALUES(3,'ketua@koperasi.local','pbkdf2_sha256$260000$a52491288b0e1ec836fbea71a77905ef$9d8c1236110cc1c069ea8143ff8f358ed855f64190b3e1034a36a239d168897b','Drs. Hendro Wibowo (Ketua)','ACTIVE',0,NULL,NULL,'2026-10-06 15:49:46','2026-10-06 15:49:46');
INSERT INTO "users" VALUES(4,'bendahara@koperasi.local','pbkdf2_sha256$260000$cad330c147cff42da376602f24de4d03$939f3acd255aad6bd2e2738b91bfee9aa3f09217819d975b4e068e98a7f850d0','Siti Rahmawati (Bendahara)','ACTIVE',0,NULL,NULL,'2026-10-06 15:49:47','2026-10-06 15:49:47');
INSERT INTO "users" VALUES(5,'manager.budi@koperasi.local','pbkdf2_sha256$260000$638f8ef6d26eda762308fba4099f8d31$4a099a3c32fe07ace3289c72ceb3cd7e7d3a445f6c8dba7c6f5426ac9ed443c2','Budi Santoso','ACTIVE',0,NULL,NULL,'2026-10-06 15:49:47','2026-10-06 15:49:47');
INSERT INTO "users" VALUES(6,'member.andi@koperasi.local','pbkdf2_sha256$260000$72e2e50282c9270bbe01dac49aff1980$4cfa50cea9a218f406c464e244146e2eceb655929bf47eccb8b04d6875e2b2d1','Andi Pratama','ACTIVE',0,NULL,NULL,'2026-10-06 15:49:47','2026-10-06 15:49:47');
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_sessions_token ON user_sessions(session_token);
CREATE INDEX idx_members_number ON members(member_number);
CREATE INDEX idx_members_nik ON members(nik);
CREATE INDEX idx_members_user_id ON members(user_id);
CREATE INDEX idx_members_emp_id ON members(employee_id);
CREATE INDEX idx_employees_emp_id ON employees(employee_id);
CREATE INDEX idx_savings_account ON savings_transactions(account_id);
CREATE INDEX idx_savings_member ON savings_transactions(member_id);
CREATE INDEX idx_loan_apps_member ON loan_applications(member_id);
CREATE INDEX idx_loans_member ON loans(member_id);
CREATE INDEX idx_installments_loan ON loan_installments(loan_id);
CREATE INDEX idx_import_rows_batch ON import_rows(batch_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_timestamp ON audit_logs(timestamp);
CREATE INDEX idx_qr_token ON qr_verification_tokens(token);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('roles',6);
INSERT INTO "sqlite_sequence" VALUES('departments',4);
INSERT INTO "sqlite_sequence" VALUES('positions',6);
INSERT INTO "sqlite_sequence" VALUES('users',6);
INSERT INTO "sqlite_sequence" VALUES('audit_logs',6);
INSERT INTO "sqlite_sequence" VALUES('user_roles',7);
INSERT INTO "sqlite_sequence" VALUES('employees',2);
INSERT INTO "sqlite_sequence" VALUES('members',1);
INSERT INTO "sqlite_sequence" VALUES('savings_accounts',3);
INSERT INTO "sqlite_sequence" VALUES('savings_transactions',3);
INSERT INTO "sqlite_sequence" VALUES('savings_opening_balances',3);
INSERT INTO "sqlite_sequence" VALUES('financial_transactions',3);
COMMIT;
