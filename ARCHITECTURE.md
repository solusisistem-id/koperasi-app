# Arsitektur & Spesifikasi Desain Koperasi Core V2

Dokumen ini menjelaskan arsitektur perangkat lunak, model domain, relasi basis data, pola keamanan, dan mesin alur kerja (*workflow engine*) aplikasi Koperasi Core.

---

## 1. Model Domain & Struktur Relasi Basis Data (27 Tabel)

Aplikasi dibangun di atas basis data relasional SQLite dengan penegakan *foreign key constraints* (`PRAGMA foreign_keys = ON;`) dan tipe data uang *fixed-decimal numeric string*.

```
[users] ──┬── [user_roles] ── [roles]
          │
          ├── [user_sessions]
          ├── [invitation_tokens]
          ├── [password_reset_tokens]
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
                                                         └── [documents] ── [qr_verification_tokens]

[employees] (hierarchy via manager_id) ── [departments], [positions]
[import_batches] ── [import_rows]
[financial_transactions]
[audit_logs]
```

### Pemisahan Entitas Identitas
- **Employee**: Mencerminkan karyawan perusahaan dengan struktur hirarki atasan bawahan (`manager_id` mengarah kembali ke `employees.id`).
- **Member**: Mencerminkan anggota koperasi (memiliki nomor anggota unik `member_number` sebagai *business key*). Anggota dapat ditautkan ke profil karyawan (`employee_id`) atau pihak eksternal/khusus.
- **User**: Akun otentikasi login (email, hash password, status akun). Import anggota **tidak** otomatis membuat akun login; akun dibuat terpisah melalui mekanisme undangan (*invitation token*).
- **Role & Permission**: Hak akses multi-peran berbasis tabel penghubung `user_roles`. Satu akun dapat memegang beberapa peran (misal: Anggota sekaligus Atasan/Approver).

---

## 2. Mesin Bulk Import Anggota V2

Alur kerja Bulk Import V2 dirancang untuk mencegah kerusakan data pada lingkungan produksi:

1. **Unduh Template:** Format `.xlsx` (multi-sheet lengkap dengan petunjuk pengisian & *allowed values*) dan `.csv`.
2. **Unggah & Staging:** File disimpan di tabel pementasan `import_batches` dan `import_rows`. Data mentah dan data ternormalisasi disimpan dalam bentuk JSON terstruktur.
3. **Validasi Komprehensif:**
   - Kelengkapan header wajib (`member_number`, `name`, `nik`, `email`).
   - Format email (regex) dan validitas 16-digit angka NIK.
   - Deteksi duplikasi intra-file (antar baris dalam satu file).
   - Deteksi duplikasi basis data terhadap anggota yang sudah terdaftar.
   - Pengecekan referensi departemen dan jabatan kerja.
4. **Mode Pemasukan Data:**
   - `ADD_ONLY`: Hanya menyisipkan anggota baru. Baris dengan nomor/NIK terdaftar ditandai sebagai duplikat dan diblokir.
   - `UPDATE_EXISTING`: Hanya memperbarui data anggota yang telah terdaftar di sistem.
   - `UPSERT`: Memperbarui jika sudah ada, atau menyisipkan baris baru jika belum ada.
5. **Mode Dry-Run:** Melakukan pengujian integritas dan menghasilkan ringkasan pratinjau tanpa menyentuh tabel produksi.
6. **Laporan Kesalahan:** Menyediakan unduhan berkas CSV berisikan nomor baris, kolom bermasalah, dan penyebab penolakan.
7. **Komit Transaksional:** Menggunakan batasan transaksi database (*atomic transaction boundary*). Jika anggota berhasil dibuat, rekening Simpanan Pokok, Wajib, dan Sukarela otomatis diinisiasi.

---

## 3. Akuntansi Simpanan Berbasis Buku Besar (Ledger-Based Accounting)

- **Rekonstruksi Saldo:** Saldo rekening simpanan **tidak pernah disimpan secara statis sebagai variabel yang dapat dimanipulasi**. Nilai saldo riil selalu dihitung dengan rumus:
  $$\text{Saldo} = \sum \text{Kredit} - \sum \text{Debit}$$
- **Saldo Awal Migrasi:** Saldo migrasi lama dimasukkan ke tabel `savings_opening_balances` dan dicatat sebagai transaksi kredit awal pada `savings_transactions` bertipe `OPENING_BALANCE` dengan menyertakan nomor batch impor dan referensi audit.

---

## 4. Mesin Persetujuan Pinjaman & Penegakan Maker-Checker

### Diagram Alur Status Pengajuan
```
[SUBMITTED]
    │
    ▼ (Perutean otomatis ke manager_id karyawan)
[ATASAN / MANAGER] ──(REJECT)──► [REJECTED]
    │ (APPROVE)
    ▼
[KETUA KOPERASI]   ──(REJECT)──► [REJECTED]
    │ (APPROVE)
    ▼
[WAITING_DISBURSEMENT]
    │
    ▼ (Pencairan oleh Bendahara)
[DISBURSED] ──► Pinjaman Aktif Dibuat ([loans] & [loan_installments])
```

### Penegakan Maker-Checker
- Sistem memeriksa `loan_applications.member_id.user_id == current_user.id`.
- Jika atasan atau ketua mengajukan pinjaman untuk dirinya sendiri, sistem melempar `MakerCheckerViolation` dan memblokir aksi approval pada pengajuan tersebut.

---

## 5. Token Verifikasi QR Berbasis Server

- Token QR dihasilkan secara kriptografis menggunakan `secrets.token_urlsafe(24)`.
- **Tidak** menyimpan status persetujuan, NIK, atau data pribadi di dalam teks/payload QR.
- Token menunjuk ke URL `/verify/{token}`. Saat diakses, server melakukan verifikasi status aktif dan validitas dokumen pada basis data.
- Pejabat berwenang dapat mencabut token kapan saja (`revoke_token`), sehingga status verifikasi seketika berubah menjadi `REVOKED`.
