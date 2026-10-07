# Batasan & Panduan Pengerasan Produksi (Known Limitations)

Dokumen ini mendokumentasikan batasan cakupan rilis V2 (*Scope Guardrails*) serta rekomendasi pengerasan untuk penerapan skala korporasi di masa depan.

---

## 1. Batasan Ruang Lingkup V2 (Sesuai Guardrail Dokumen)

Sesuai ketentuan Bagian 1 Dokumen Master Prompt, fitur-fitur berikut ini sengaja **tidak disertakan** pada rilis V2 untuk menjaga fokus sistem inti koperasi:

1. **Bukan Akuntansi Penuh / General Ledger Kompleks:**
   Sistem berfokus pada buku besar kas dan mutasi simpanan/pinjaman anggota (Anggota → Simpanan → Pinjaman → Transaksi → Approval → Laporan), tanpa grafik akun akuntansi perusahaan (*COA double-entry ERP*).
2. **Tidak Ada Integrasi Payment Gateway / Bank Host-to-Host Langsung:**
   Pencairan dan pembayaran menggunakan sistem konfirmasi kasir/bendahara berbasis *idempotency key* internal.
3. **Tidak Ada Otomasi WhatsApp Bot / AI Scoring / Payroll HR:**
   Semua keputusan kredit didasarkan pada alur persetujuan manusia (*human-in-the-loop maker-checker*) oleh atasan langsung dan ketua koperasi.

---

## 2. Rekomendasi Pengerasan Produksi (Production Hardening)

Untuk penerapan di lingkungan dengan beban transaksi tinggi atau kebutuhan kepatuhan perbankan:

- **Mesin Basis Data:** Untuk klaster multi-server berskala jutaan baris, SQLite dapat dimigrasikan ke PostgreSQL dengan tetap mempertahankan skema DDL dan relasi kunci asing yang telah dibentuk.
- **Kunci Distribusi (Distributed Locks):** Pengendalian *idempotency key* saat ini menggunakan indeks unik basis data ACID. Pada arsitektur *microservices*, disarankan menambahkan Redis Distributed Lock (Redlock).
- **MFA (Multi-Factor Authentication):** Arsitektur sesi dan otentikasi telah dipersiapkan agar dapat ditambahkan TOTP/WebAuthn untuk peran istimewa (Super Admin, Ketua, Bendahara).
- **Layanan Pengiriman Email:** Endpoint pengiriman email saat ini mencatat tautan token ke log audit dan tampilan antarmuka. Pada produksi langsung, sambungkan ke relay SMTP korporat (Postmark, Sendgrid, atau Amazon SES).
