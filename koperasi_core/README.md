# Koperasi Core — Aplikasi Koperasi Employee Management V2

Aplikasi sistem inti koperasi pegawai (*employee cooperative core management system*) yang dirancang *runnable end-to-end* dengan arsitektur modular, RBAC ketat, audit trail finansial, mesin *bulk import* anggota V2, buku besar (*ledger-based*) simpanan, alur persetujuan pinjaman berjenjang (*maker-checker*), dan verifikasi keabsahan dokumen berbasis token QR *server-side*.

---

## 1. Fitur Utama

- **Pemisahan Identitas (Identity Segregation):**
  `Employee ≠ User Account ≠ Membership`. Atasan / Approver tidak wajib menjadi anggota. Pengguna dapat memiliki beberapa peran.
- **Bulk Import Anggota V2 (Fitur Unggulan):**
  - Alur aman: Unduh Template → Unggah File (Excel/CSV) → Parse & Normalisasi → Validasi Multilevel → Pratinjau (Preview) Terperinci → Konfirmasi & Commit Transaksional.
  - Mode Import: `ADD_ONLY`, `UPDATE_EXISTING`, `UPSERT`.
  - Deteksi duplikasi intra-file & database (Nomor Anggota, NIK, Email).
  - Mode *Dry-run* (uji validasi tanpa mutasi data).
  - Laporan Error baris-per-baris dapat diunduh dalam format CSV.
  - Riwayat Import Batch lengkap dengan *audit metadata*.
- **Otentikasi & Manajemen Akun:**
  - Login berbasis Email + Password (tanpa dropdown peran di antarmuka).
  - *Password Hashing* standar industri: PBKDF2-HMAC-SHA256 (260.000 iterasi).
  - Alur Undangan Akun (*Account Invitation*): Import anggota tidak otomatis membuat akun atau password default masal. Pengguna mengaktifkan akun via tautan undangan aman dan menentukan password sendiri.
  - *Forgot Password* dengan token acak berkadaluarsa sekali pakai (*single-use expiring token*).
- **Simpanan & Saldo Awal (Ledger-Based Accounting):**
  - Simpanan Pokok, Wajib, dan Sukarela.
  - Saldo riil **selalu direkonstruksi secara matematis** dari jumlahan mutasi debit/kredit pada buku besar (*ledger transactions*), bukan kolom statis yang dapat dimanipulasi.
  - Perekaman Saldo Awal (*Opening Balance*) terikat pada identitas batch migrasi untuk transparansi audit.
- **Pinjaman & Alur Persetujuan Bertingkat:**
  - Pemisahan entitas antara *Loan Application* (pengajuan) dan *Active Loan* (pinjaman berjalan).
  - Perutean otomatis ke atasan langsung (*manager*) berdasarkan struktur organisasi kepegawaian.
  - Penegakan aturan **Maker-Checker**: Atasan/pengurus dilarang keras menyetujui pengajuannya sendiri.
  - Tahapan persetujuan: `SUBMITTED` → `APPROVED_BY_MANAGER` → `WAITING_DISBURSEMENT` (Ketua) → `DISBURSED` (Bendahara) → `ACTIVE`.
- **Pencairan & Pembayaran Angsuran Idempotent:**
  - Pencairan oleh Bendahara mengaktifkan pinjaman, membentuk jadwal angsuran, mencatat mutasi kas keluar (*OUTFLOW*), serta menerbitkan Surat Keputusan Pinjaman.
  - Pembayaran angsuran dilindungi *idempotency key* unik untuk mencegah pembukuan ganda saat koneksi lambat atau penekanan tombol berulang.
- **Dokumen & Verifikasi QR:**
  - Token verifikasi QR berupa string acak URL-safe yang menunjuk ke endpoint publik `/verify/{token}`.
  - Server bertindak sebagai *source of truth* tunggal (tidak menyimpan status kelulusan di payload QR statis).
  - Mendukung pencabutan token (*revocation*).
- **Dasbor Berbasis Peran & Laporan Operasional:**
  - Antarmuka responsif berbahasa Indonesia untuk peran: Super Admin, Admin Koperasi, Anggota, Ketua, Atasan/Approver, dan Bendahara.
  - Laporan Arus Kas (*Inflow/Outflow*), Laporan Posisi Simpanan & Pinjaman Anggota, serta Jejak Audit (*Audit Trail*).

---

## 2. Akun Demo Bawaan (Seed Data)

Database awal telah dilengkapi dengan struktur organisasi, jabatan, anggota percontohan, dan akun dengan peran masing-masing:

| Peran | Alamat Email | Password | Keterangan |
| :--- | :--- | :--- | :--- |
| **Super Admin** | `superadmin@koperasi.local` | `SuperAdmin123!` | Akses penuh sistem, kelola user & audit |
| **Admin Koperasi** | `admin@koperasi.local` | `Admin123!` | Kelola anggota, bulk import, operasional |
| **Ketua Koperasi** | `ketua@koperasi.local` | `Ketua123!` | Persetujuan final pinjaman, ringkasan eksekutif |
| **Bendahara** | `bendahara@koperasi.local` | `Bendahara123!` | Pencairan dana pinjaman, kontrol arus kas |
| **Atasan / Manager** | `manager.budi@koperasi.local` | `Manager123!` | Budi Santoso (Head of IT), atasan langsung Andi |
| **Anggota** | `member.andi@koperasi.local` | `Member123!` | Andi Pratama (Software Engineer, MEM-001) |

---

## 3. Cara Menjalankan Aplikasi

### Prasyarat
- Python 3.11+
- Modul standar terpasang: `fastapi`, `uvicorn`, `openpyxl`, `jinja2`, `sqlite3`

### Menjalankan Server
Cukup jalankan skrip runner:
```bash
./run.sh
```
Atau secara manual:
```bash
# Inisialisasi dan seeding database
python3 scripts/seed_data.py
python3 scripts/generate_templates.py

# Menjalankan FastAPI server
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Buka peramban (*browser*) pada alamat: `http://localhost:8000`

---

## 4. Menjalankan Pengujian Otomatis

### A. Menjalankan Seluruh 20 Kriteria Penerimaan (Acceptance Criteria)
```bash
python3 tests/test_all_criteria.py
```
*Menguji valid import, header error, duplikat, mode upsert/update, isolasi dry-run, rekonstruksi ledger saldo simpanan, isolasi data anggota, perutean atasan, maker-checker, siklus pinjaman, idempotensi angsuran, pencabutan QR, dan manajemen password.*

### B. Menjalankan Skenario End-to-End Lengkap (Halaman 7)
```bash
python3 scripts/run_scenario.py
```
*Mengeksekusi 17 langkah otomatis mulai dari login admin, import anggota lama, aktivasi akun mandiri, pencatatan saldo awal, pengajuan pinjaman, approval berjenjang, pencairan bendahara, angsuran ke-1, hingga verifikasi QR dan audit trail.*
