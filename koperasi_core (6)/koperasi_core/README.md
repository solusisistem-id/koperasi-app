# Koperasi Core — Production Hardened & Render Ready System

Sistem Manajemen Inti Koperasi Karyawan (*Employee Cooperative Core System*) yang siap *production* dan *deployment* ke **Render Web Service + Render Managed PostgreSQL**.

Aplikasi dibangun di atas fondasi **FastAPI**, **PostgreSQL** (*source of truth* transaksional), arsitektur modular, otentikasi berbasis sesi aman dengan proteksi CSRF, otorisasi berbasis hak akses (*fine-grained permissions*), integritas finansial (*ledger-based*, *row locking*, idempotensi transaksi), alur persetujuan pinjaman berjenjang (*maker-checker*), serta sistem verifikasi dokumen QR *server-side*.

---

## 1. Arsitektur Produksi (Final Architecture)

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
- **Transactional Source of Truth:** PostgreSQL (dengan presisi `NUMERIC(18,2)` untuk seluruh entitas finansial). SQLite hanya digunakan untuk development dan testing lokal.
- **Runtime Environment:** Render Web Service dengan binding dinamis `0.0.0.0:${PORT:-8000}`.
- **Ephemeral Filesystem Safeguard:** Berkas unggahan dan dokumen diverifikasi dan disimpan ke Object Storage (S3 / Cloudflare R2 / GCS) dengan fallback terisolasi; tidak menjadikan filesystem lokal Render sebagai penyimpanan permanen.

---

## 2. Fitur Keamanan Produksi (Production Hardening)

1. **Secret Management & Fail-Fast:**
   - Variabel rahasia wajib disuplai melalui environment variables Render.
   - Pada `APP_ENV=production`, server akan **gagal mulai (fail-fast)** jika `SECRET_KEY` tidak diatur, menggunakan nilai default tidak aman, atau jika database belum menggunakan PostgreSQL.
2. **Proteksi CSRF (Defense-in-Depth):**
   - Melindungi seluruh operasi pengubah status (*state-changing HTTP methods*: `POST`, `PUT`, `PATCH`, `DELETE`).
   - Validasi ganda: pengecekan *Origin/Referer header* dan verifikasi *CSRF token* terenkripsi yang disinkronkan dengan sesi pengguna.
   - Script injeksi token CSRF otomatis pada template antarmuka pengguna.
3. **Session Security & Session Rotation:**
   - Cookie sesi dikonfigurasi dengan `HttpOnly=True`, `SameSite=Lax`, dan `Secure=True` pada environment produksi.
   - Token sesi dirotasi (*rotated*) setiap kali pengguna berhasil login.
   - Invalidation masal seluruh sesi aktif saat password diubah atau saat akun dinonaktifkan oleh administrator.
4. **Proteksi Brute-Force & Account Lockout:**
   - Penerapan *progressive delay* dan pembatasan percobaan login (maksimal 5 kali berturut-turut).
   - Akun terkunci otomatis selama 15 menit jika batas terlampaui.
   - Pengecekan status kunci dilakukan sebelum proses hashing password untuk mencegah *timing attacks*.
5. **Forgot Password & Anti-Account Enumeration:**
   - Respons reset password selalu bersifat generik: *"Jika akun dengan email tersebut tersedia, instruksi reset telah dikirim."*
   - Database hanya menyimpan *hash* dari token reset (`token_hash` SHA-256), bukan *raw token*.
   - Token kedaluwarsa dalam 2 jam dan sekali pakai (*single-use*).
6. **QR Verification Token Hashing:**
   - QR code tidak memuat data sensitif anggota (NIK, saldo, nomor rekening, dll).
   - Verifikasi dilakukan secara *server-side* pada endpoint `/verify/{token}`.
   - Log audit publik hanya mencatat *token fingerprint* (`token_digest[:8]...`), bukan raw token.
7. **Keamanan Upload Berkas:**
   - Validasi ketat terhadap ukuran berkas (maksimal 10 MB), sanitasi nama berkas (pencegahan *path traversal*), dan whitelist ekstensi (`.pdf`, `.xlsx`, `.xls`, `.csv`, `.png`, `.jpg`, `.jpeg`).
8. **Maker-Checker & Approver Snapshot:**
   - Snapshot approver disimpan saat pengajuan pinjaman dibuat sehingga perubahan atasan di masa depan tidak memengaruhi riwayat pengajuan berjalan.
   - Atasan atau pengurus dilarang menyetujui pengajuan pinjaman miliknya sendiri (*maker-checker enforcement*).
9. **Integritas Finansial & Idempotensi:**
   - Seluruh mutasi simpanan, pencairan pinjaman, dan pembayaran angsuran menggunakan kunci idempotensi (`idempotency_key`) dengan konstrain unik di database untuk mencegah *double payment* / *double submit*.
   - Saldo simpanan anggota selalu direkonstruksi dari buku besar (*ledger-based accounting*).

---

## 3. Variabel Lingkungan (Environment Variables)

Salin template konfigurasi dari `.env.example`:

| Nama Variabel | Wajib di Prod? | Deskripsi & Nilai Contoh |
| :--- | :---: | :--- |
| `APP_ENV` | Ya | `production` (atau `development` untuk pengujian lokal) |
| `PORT` | Otomatis | Disediakan secara otomatis oleh Render (default fallback: `8000`) |
| `SECRET_KEY` | Ya | String acak berkekuatan tinggi (min 32 karakter, e.g. `openssl rand -hex 32`) |
| `DATABASE_URL` | Ya | PostgreSQL Connection URL dari Render, e.g. `postgresql://user:pass@host:5432/db` |
| `SESSION_COOKIE_SECURE` | Rekomendasi | `true` pada Render (HTTPS) |
| `STORAGE_BACKEND` | Opsional | `local` atau `s3` (S3, Cloudflare R2, MinIO, GCS) |
| `STORAGE_BUCKET` | Jika S3 | Nama bucket penyimpanan dokumen |
| `STORAGE_ENDPOINT` | Jika S3 | Endpoint URL S3/R2 |
| `STORAGE_ACCESS_KEY` | Jika S3 | Access Key Object Storage |
| `STORAGE_SECRET_KEY` | Jika S3 | Secret Key Object Storage |
| `SMTP_HOST` | Opsional | Host SMTP pengiriman email (e.g. `smtp.gmail.com` atau SendGrid) |
| `SMTP_PORT` | Opsional | Port SMTP (e.g. `587`) |
| `SMTP_USER` | Opsional | Username / email pengirim |
| `SMTP_PASSWORD` | Opsional | Password aplikasi SMTP |
| `SMTP_FROM_EMAIL` | Opsional | Alamat email pengirim (e.g. `noreply@koperasi.com`) |
| `INITIAL_ADMIN_EMAIL` | Bootstrap | Email Super Admin pertama saat inisialisasi awal |
| `INITIAL_ADMIN_NAME` | Bootstrap | Nama lengkap Super Admin pertama |

---

## 4. Panduan Deployment ke Render (Step-by-Step)

### Langkah 1: Push Repositori ke GitHub
Pastikan branch `main` telah memuat seluruh codebase terbaru:
```bash
git add .
git commit -m "feat: production hardening and Render readiness"
git push origin main
```

### Langkah 2: Buat PostgreSQL Database di Render
1. Buka [Dashboard Render](https://dashboard.render.com).
2. Klik **New +** → **PostgreSQL**.
3. Beri nama database, misalnya: `koperasi-db`.
4. Pilih region yang terdekat (misal: Singapore) dan tier yang diinginkan.
5. Setelah database aktif, salin **Internal Database URL** (digunakan untuk komunikasi cepat antar-layanan Render).

### Langkah 3: Deploy Web Service di Render
1. Klik **New +** → **Web Service**.
2. Hubungkan repositori GitHub `koperasi-core`.
3. Konfigurasikan layanan:
   - **Name:** `koperasi-core`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path:** `/healthz`
4. Di bagian **Environment Variables**, tambahkan:
   - `APP_ENV` = `production`
   - `DATABASE_URL` = *[Paste Internal Database URL dari Langkah 2]*
   - `SECRET_KEY` = *[Generate string acak 64 karakter]*
   - `SESSION_COOKIE_SECURE` = `true`
5. Klik **Create Web Service**. Render akan secara otomatis menjalankan build, mengecek `/healthz`, dan mengaktifkan layanan.

### Langkah 4: Jalankan Bootstrap Admin Perdana
Aplikasi di lingkungan produksi **tidak pernah menjalankan seeding demo secara otomatis**.
Untuk membuat akun Super Admin perdana dengan alur undangan aman (tanpa password default bawaan):
1. Buka tab **Shell** pada Web Service di dashboard Render.
2. Jalankan perintah:
   ```bash
   python scripts/bootstrap_admin.py
   ```
3. Skrip akan mencetak tautan aktivasi mandiri:
   ```text
   Admin invited successfully. Activation token: <TOKEN_RAHASIA>
   ```
4. Buka URL: `https://<app-name>.onrender.com/invite/<TOKEN_RAHASIA>` pada browser untuk membuat password Super Admin pertama kali.

---

## 5. Prosedur Backup & Disaster Recovery Database

### Metrik Kebijakan Koperasi:
- **Recovery Point Objective (RPO):** Maksimal 1 jam (data loss toleransi < 1 jam).
- **Recovery Time Objective (RTO):** Maksimal 30 menit untuk pemulihan operasional penuh.
- **Backup Retention:**
  - Harian: Disimpan selama 30 hari.
  - Mingguan: Disimpan selama 12 minggu.
  - Bulanan: Disimpan selama 12 bulan untuk audit tahunan (RAT).

### A. Otomatisasi Backup (Render Managed PostgreSQL)
Render Managed PostgreSQL menyediakan *automated daily backups* secara default. Untuk tingkat kepatuhan tinggi, gunakan *scheduled job* harian yang mengekspor dump ke Object Storage:
```bash
pg_dump "$DATABASE_URL" -Fc -f "/tmp/koperasi_backup_$(date +%Y%m%d_%H%M%S).dump"
```

### B. Prosedur Pemulihan Bencana (Restore Procedure)
1. Siapkan database target baru atau kosongkan skema bermasalah.
2. Jalankan perintah pemulihan:
   ```bash
   pg_restore --clean --no-acl --no-owner -d "$DATABASE_URL" /path/to/backup.dump
   ```
3. Verifikasi konsistensi data dan buku besar melalui endpoint pengujian atau audit skrip:
   ```bash
   python3 -c "from app.reports.service import generate_executive_financial_report; print(generate_executive_financial_report())"
   ```

---

## 6. Observabilitas & Pemantauan (Observability)

- **Health Check Endpoint:** `GET /healthz`
  Mengembalikan status layanan, versi aplikasi, dan konektivitas database tanpa mengekspos informasi sensitif:
  ```json
  {
    "status": "ok",
    "app": "Koperasi Core",
    "version": "2.2.0",
    "environment": "production",
    "database": "connected"
  }
  ```
- **Request Correlation ID:** Setiap request HTTP diberi header `X-Correlation-ID` untuk melacak alur transaksi dari web sampai ke baris log audit database.
- **Log Sanitasi:** Sistem secara otomatis menyensor kata kunci sensitif (`password`, `token`, `nik`, `bank_account`, `cookie`) dari seluruh output log aplikasi.

---

## 7. Eksekusi Pengujian Otomatis

Semua pengujian otomatis dapat dijalankan secara lokal sebelum melakukan merge atau deployment:

```bash
# 1. Menjalankan 20/20 Acceptance Criteria Tests
python3 tests/test_all_criteria.py

# 2. Menjalankan 10/10 Production Hardening & Security Tests
python3 tests/test_production_hardening.py

# 3. Menjalankan 17-Langkah Simulasi Skenario End-to-End
python3 scripts/run_scenario.py
```

Seluruh pengujian dirancang untuk lulus (**100% PASS**) secara deterministik dan idempotent.
