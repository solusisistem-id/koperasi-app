# Batasan & Panduan Operasional Produksi (Known Limitations)

Dokumen ini mendokumentasikan batasan cakupan rilis (*Scope Guardrails*) serta rekomendasi mitigasi operasional untuk penerapan produksi Koperasi Core.

---

## 1. Batasan Ruang Lingkup (Scope Guardrails)

Sesuai ketentuan Bagian 28 Dokumen Master Prompt, fitur-fitur berikut sengaja **tidak disertakan** untuk menjaga fokus dan keandalan sistem inti koperasi:

1. **Bukan Akuntansi Penuh / General Ledger Perusahaan Kompleks:**
   Sistem berfokus pada buku besar kas dan mutasi simpanan/pinjaman anggota (Anggota → Simpanan → Pinjaman → Transaksi → Approval → Laporan), tanpa grafik akun akuntansi perusahaan multinasional (*COA double-entry ERP*).
2. **Tidak Ada Integrasi Payment Gateway / Bank Host-to-Host Langsung:**
   Pencairan dan pembayaran menggunakan sistem konfirmasi bendahara berbasis *idempotency key* internal dan jurnal transaksi kas.
3. **Tidak Ada Otomasi WhatsApp Bot / AI Credit Scoring / Payroll HR:**
   Semua keputusan kredit didasarkan pada alur persetujuan manusia (*human-in-the-loop maker-checker*) oleh atasan langsung dan ketua koperasi.

---

## 2. Mitigasi Risiko Operasional Produksi

1. **Penyimpanan Berkas (Ephemeral Disk Render):**
   - *Konteks:* Container Web Service pada platform Render memiliki filesystem lokal yang bersifat ephemeral (direset setiap deploy/restart).
   - *Mitigasi:* Konfigurasikan Object Storage eksternal (AWS S3, Cloudflare R2, MinIO, atau GCS) dengan menyetel `STORAGE_BACKEND=s3`, `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, dan `S3_SECRET_ACCESS_KEY` pada Render Dashboard.
2. **Layanan Pengiriman Email (SMTP):**
   - *Konteks:* Pengiriman email aktivasi dan reset password memerlukan provider SMTP. Akun email gratisan memiliki batas kuota harian.
   - *Mitigasi:* Gunakan layanan transactional email profesional seperti SendGrid, Postmark, Mailgun, atau Amazon SES untuk volume produksi.
3. **Backup & Disaster Recovery:**
   - *Konteks:* Database PostgreSQL adalah single source of truth untuk seluruh transaksi finansial koperasi.
   - *Mitigasi:* Aktifkan fitur *automated daily backups* pada Render Managed PostgreSQL dan jalankan dump terjadwal berkala ke Object Storage (kebijakan RPO < 1 jam, RTO < 30 menit).
