# Arsitektur & Spesifikasi Desain Koperasi Core V3 (Production Ready)

Dokumen ini menjelaskan arsitektur perangkat lunak, model domain, relasi basis data, pola keamanan, dan mesin alur kerja (*workflow engine*) aplikasi Koperasi Core versi produksi siap deploy ke **Render Web Service + Render Managed PostgreSQL**.

---

## 1. Arsitektur Produksi & Target Deployment

```
                    GITHUB REPOSITORY
                           │
                           ▼
                  ┌─────────────────┐
                  │ RENDER SERVICE  │
                  │ FastAPI Backend │
                  └────────┬────────┘
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
          ▼                ▼                 ▼
   Render PostgreSQL  Object Storage   Email Provider
   (Transactional DB) (S3/R2/Docs)     (SMTP/Gmail)
          │
          ▼
   ┌──────┴──────────┬──────────────┐
   │                 │              │
Members           Savings         Loans
   │                 │              │
   └──────┬──────────┴──────────────┘
          │
    Multi-Approval
          │
      Audit Log
```

- **Target Deployment:** GitHub → Render Web Service → FastAPI → PostgreSQL → Object Storage.
- **Transactional Source of Truth:** PostgreSQL (dengan presisi `NUMERIC(18,2)` untuk seluruh entitas finansial). SQLite didukung transparan hanya untuk local unit testing.
- **Runtime Environment:** Render Web Service dengan binding dinamis `0.0.0.0:${PORT:-8000}`.
- **Persistent Storage:** `StorageService` abstraction yang mendukung S3-compatible object storage (AWS S3, Cloudflare R2, MinIO, GCS) untuk berkas dokumen anggota dan bukti transaksi, menjaga integritas di atas filesystem Render yang bersifat ephemeral.

---

## 2. Model Domain & Struktur Relasi Basis Data (22 Tabel)

```
[users] ──┬── [user_roles] ── [roles] ── [role_permissions] ── [permissions]
          │
          ├── [user_sessions]
          ├── [invitation_tokens] (token_hash only)
          ├── [password_reset_tokens] (token_hash only)
          │
          └── [members] ──┬── [savings_accounts] ──┬── [savings_transactions]
                          │                         └── [savings_opening_balances]
                          ├── [member_documents]
                          │
                          └── [loan_applications] ──┬── [loan_approval_steps]
                                                    ├── [loan_approvals]
                                                    │
                                                    └── [loans] ── [loan_installments]
                                                         │
                                                         └── [documents] ── [qr_verification_tokens] (token_hash only)

[employees] (hierarchy via manager_id) ── [departments], [positions]
[import_batches] ── [import_rows]
[financial_transactions]
[audit_logs] (append-only)
```

### Pemisahan Entitas Identitas (Identity Segregation)
- **Employee**: Mencerminkan karyawan perusahaan dengan struktur hirarki atasan bawahan (`manager_id` mengarah kembali ke `employees.id`).
- **Member**: Mencerminkan anggota koperasi (memiliki nomor anggota unik `member_number` sebagai *business key*). Anggota dapat ditautkan ke profil karyawan (`employee_id`) atau pihak eksternal/khusus.
- **User**: Akun otentikasi login (email, hash password, status akun). Import anggota **tidak** otomatis membuat akun login; akun dibuat terpisah melalui mekanisme undangan (*invitation token*).
- **Role & Permission Engine**: Otorisasi berbasis hak akses terpusat (`require_permission(user, permission_code)`). Role hanya menjadi grouping permission. Mendukung multi-peran dengan union permissions yang efektif.

---

## 3. Integritas Finansial & Konkurensi Transaksi

1. **Exact Decimal Math:** Seluruh nominal uang disimpan dalam tipe data `NUMERIC(18,2)` dan dikalkulasi menggunakan `Decimal` Python tanpa floating-point drift.
2. **Row-Level Locking:** Operasi sensitif saldo simpanan, pencairan pinjaman, dan pembayaran angsuran menggunakan `SELECT ... FOR UPDATE` di dalam transaksi database ACID untuk mencegah *race conditions* saat dua request tiba bersamaan.
3. **Financial Idempotency:** Seluruh pencatatan kas keluar/masuk, pembayaran angsuran, dan pembukuan saldo awal diverifikasi menggunakan `idempotency_key` dengan konstrain unik. Pengiriman berulang (*retry/double-click*) menghasilkan respons idempotent tanpa duplikasi transaksi.
4. **Ledger-Based Accounting:** Saldo simpanan tidak disimpan sebagai nilai statis melainkan direkonstruksi secara dinamis dari mutasi kredit dan debit pada buku besar (*savings_transactions*).

---

## 4. Keamanan & Token Hashing

1. **Zero Raw Token in DB:** Token reset password, token undangan akun, dan token QR dokumen hanya disimpan dalam bentuk hash SHA-256 (`token_hash`) di database. Lookup verifikasi selalu mencocokkan `WHERE token_hash = ?`.
2. **Zero Raw Token in Production Responses:** Pada `APP_ENV=production`, raw token dikirimkan secara privat via email dan tidak pernah diekspos dalam respons URL atau payload JSON.
3. **Session Hardening & Rotation:** Sesi dirotasi saat login sukses. Cookie menggunakan `HttpOnly`, `SameSite=Lax`, dan `Secure`. Seluruh sesi aktif otomatis diinaktivasi saat password diubah atau akun dinonaktifkan.
4. **Brute-Force & Lockout:** Pembatasan maksimal 5 kali percobaan login gagal dengan penguncian sementara akun selama 15 menit. Pengecekan kunci dilakukan sebelum hashing password untuk memitigasi serangan DoS timing.
5. **CSRF Defense-in-Depth:** Seluruh metode HTTP state-changing (`POST`, `PUT`, `PATCH`, `DELETE`) divalidasi ganda menggunakan Origin/Referer check dan sinkronisasi token CSRF kriptografis.
6. **Maker-Checker & Approver Snapshot:** Approver pinjaman dibekukan (*snapshotted*) saat pengajuan dibuat, dan pemohon dilarang menyetujui pengajuannya sendiri.
