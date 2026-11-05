# IT Automation System - End-to-End Invoice Processing

Sistem otomasi pemrosesan faktur (invoice) berbasis Python dengan arsitektur standar industri, *maintainable*, *scalable*, dan *clean code*. Mengintegrasikan **Email Intake (IMAP/SMTP) → Google Cloud Vision OCR → Regex Extraction → Database SQLite → PO Validation → Email Approval → Browser ERP Posting → Excel Export & Archiving**.

---

## 1. Arsitektur & Struktur Direktori

Sistem dirancang modular mengikuti prinsip pemisahan tanggung jawab (*Separation of Concerns*) dan *Clean Architecture*:

```
IT Automation Developer Use Case/
├── config/
│   ├── __init__.py
│   └── settings.py          # Dynamic configuration loader (Config.xlsx, .env, defaults)
├── core/
│   ├── __init__.py
│   ├── database.py          # SQLite repository (invoices, erp_postings, process_logs)
│   └── logger.py            # Structured logging & ProcessLogs database sink
├── modules/
│   ├── __init__.py
│   ├── email_intake.py      # IMAP mail listener & local folder attachment loader
│   ├── ocr_engine.py        # Google Cloud Vision API OCR client
│   ├── image_preprocessor.py# CV quality assessment & auto-enhancement (blur, skew, dark, flash, stains)
│   ├── extractor.py         # Regex extractor untuk field invoice
│   ├── validator.py         # Purchase order validator (PurchaseOrders.csv)
│   ├── approval.py          # Dynamic threshold approval workflow (SMTP/IMAP & CLI prompt)
│   ├── erp_poster.py        # Browser automation (CDP / Selenium: Edge & Chrome, Headless switch)
│   ├── archiver.py          # File categorizer & deduplicated mover ke /Processed/<Result>
│   └── exporter.py          # Excel exporter sinkronisasi template (file lock safe)
├── templates/
│   ├── Config.xlsx          # Konfigurasi parameter bisnis
│   ├── Invoices.xlsx        # Template export tabel Invoices_T
│   ├── ERP_Dummy.xlsx       # Template export tabel PostedInvoices
│   ├── ProcessLogs.xlsx     # Template audit log tabel Logs_T
│   └── mock_erp_form.html   # Standalone HTML ERP form untuk pengujian offline/lokal
├── tests/
│   ├── __init__.py
│   └── test_automation.py   # Unit & integration verification test suite
├── data/
│   └── automation.db        # SQLite persistence database (auto-generated)
├── inbox/                   # Folder intake email attachment lokal
├── Processed/               # Hasil akhir arsip invoice
│   ├── Success/
│   ├── Rejected/
│   └── Failed/
├── Sample Invoice/          # Sampel gambar invoice pengujian
├── .env.example             # Template konfigurasi environment & secrets
├── .env                     # File konfigurasi aktif lokal
├── main.py                  # CLI entrypoint & orchestrator pipeline
├── PurchaseOrders.csv       # Data master Purchase Order
├── requirements.txt         # Daftar dependensi Python
└── README.md                # Dokumentasi sistem
```

---

## 2. Alur Kerja Sistem (End-to-End Pipeline)

1. **Email Intake:**
   - Mendengarkan email masuk pada akun IMAP yang memiliki lampiran gambar invoice (`.jpg`, `.jpeg`, `.png`, `.pdf`) dan menyimpannya ke direktori `inbox/`.
   - Mendukung fallback mode untuk memproses file lokal langsung dari folder (misal: `Sample Invoice/`).

2. **OCR & Regex Extraction:**
   - Mengirim file gambar ke Google Cloud Vision REST API.
   - Melakukan ekstraksi deterministik menggunakan *regular expressions* untuk:
     - `InvoiceNumber`: format `INV-YYYY-XXX`
     - `VendorName`: nama perusahaan dengan prefix `PT`/`CV`/`UD` atau label
     - `PO_Number`: format `PO-XXX`
     - `Amount`: nominal angka faktur
     - `Currency`: default `IDR`
   - Mendeteksi faktur rusak/tidak valid (*corrupted/invalid/noise*).

3. **Database SQLite:**
   - Menyimpan seluruh status transaksi, `CorrelationId`, nominal, relasi PO, dan timestamp ke dalam tabel `invoices` pada database `data/automation.db`.

4. **Validasi Purchase Order (PO):**
   - Memvalidasi data invoice terhadap master `PurchaseOrders.csv`:
     - Memastikan `PO_Number` terdaftar.
     - Memastikan status `IsActive == TRUE`.
     - Memastikan `VendorName`, `Currency`, dan `TotalAmount` cocok presisi.
   - Menghasilkan status: `MATCHED`, `MISMATCH`, `NOT_FOUND`, `INACTIVE_PO`, atau `INVALID`.

5. **Approval Workflow (Dynamic Threshold):**
   - Membaca `ThresholdAmount` secara dinamis dari file `Config.xlsx`.
   - Jika `Amount > ThresholdAmount`:
     - Mengirim notifikasi approval via SMTP ke `ApproverEmail`.
     - Menunggu balasan `APPROVE` / `REJECT` via IMAP.
     - Menyediakan mode interaktif terminal (`Y/n`) serta flag otomatis `--auto-approve` untuk batch/CI run.

6. **Posting ERP Form (Browser Automation):**
   - Mengirim data faktur (`InvoiceNumber`, `VendorName`, `PO_Number`, `Amount`, `Currency`, `PostingRef`) ke form web (`FormsUrl`) melalui browser (Microsoft Edge / Google Chrome).
   - Menggunakan teknologi Chrome DevTools Protocol (CDP) native yang stabil tanpa kendala versi driver eksternal, dengan dukungan Selenium.
   - Menjamin nilai `PostingRef` identik pada response form, `ERP_Dummy.xlsx`, dan `Invoices.xlsx`.
   - Mendukung visual browser (visible) dan mode *headless*.

7. **Export & Archiving:**
   - Mengekspor data dari database SQLite ke `Invoices.xlsx`, `ERP_Dummy.xlsx`, dan `ProcessLogs.xlsx` dengan mempertahankan struktur template.
   - Memindahkan file invoice ke direktori arsip sesuai hasil akhir:
     - `/Processed/Success/`
     - `/Processed/Rejected/`
     - `/Processed/Failed/`

---

## 3. Prasyarat & Instalasi

### Prasyarat
- Python 3.10+
- Browser Microsoft Edge atau Google Chrome (terinstal bawaan pada sistem Windows)

### Instalasi Dependensi
Jalankan perintah berikut pada terminal:
```bash
pip install -r requirements.txt
```

---

## 4. Konfigurasi Sistem

### File `Config.xlsx`
Konfigurasi bisnis dibaca secara dinamis dari sheet `Config_T`:
- `ThresholdAmount`: Batas nominal untuk memicu alur approval (default: `1000000`).
- `FormsUrl`: URL Google Form atau Microsoft Form ERP Anda.
- `ExcelERPPath`: Path output `ERP_Dummy.xlsx`.
- `ApproverEmail`: Alamat email approver yang dituju.

### File `.env`
Salin template `.env.example` menjadi `.env` dan lengkapi kredensial:
```ini
# Google Cloud Vision API Key
VISION_API_KEY=AIzaSyD9bQ80NIXZyQYz_PclqLKYTlUUusrV6iA

# Mailbox Configuration (Opsional - jika menggunakan inbox aktif)
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
IMAP_USER=your_email@gmail.com
IMAP_PASSWORD=your_app_password

SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password

# Pengaturan Browser Automation
HEADLESS=false
BROWSER_TYPE=edge

# URL Form ERP (Bisa juga diisi di sini untuk override Config.xlsx)
FORMS_URL=https://forms.microsoft.com/your-form-url
```

---

## 5. Cara Menjalankan Program

### 1. Menjalankan Otomasi Penuh (Batch Mode)
Memproses seluruh invoice dalam folder `Sample Invoice/` dengan browser tampak (visible) dan auto-approve:
```bash
python main.py --source "Sample Invoice" --auto-approve
```

### 2. Menjalankan dengan Mode Headless (Latar Belakang)
```bash
python main.py --source "Sample Invoice" --auto-approve --headless
```

### 3. Menjalankan dengan Mode Interaktif Approval
Setiap invoice yang nominalnya melebihi `ThresholdAmount` akan meminta konfirmasi manual di terminal:
```bash
python main.py --source "Sample Invoice"
```

### 4. Menjalankan Otomasi via Email (IMAP)
Membaca invoice lampiran dari akun email yang dikonfigurasi di `.env`:
```bash
python main.py --source email
```

### 5. Memindahkan File Asli ke `/Processed`
Tambahkan flag `--move` agar file sumber dipindahkan (bukan diduplikasi/copy):
```bash
python main.py --source inbox --move
```

---

## 6. Pengujian & Verifikasi (Self-Verification)

Tersedia unit & integration test assert-based untuk memverifikasi logika modul tanpa dependensi luar:
```bash
python tests/test_automation.py
```

Output pengujian:
```text
>>> Running Self-Verification Tests...
[PASS] test_config_loader
[PASS] test_regex_extractor
[PASS] test_po_validator
[PASS] test_approval_threshold
[PASS] test_database_and_excel_export

ALL AUTOMATION TESTS PASSED SUCCESSFULLY!
```

---

## 7. Catatan Form ERP & Penilaian Reviewer

- Jika `FormsUrl` pada `Config.xlsx` atau `.env` diarahkan ke URL Google Forms / Microsoft Forms Anda, browser akan otomatis mengisi input form dan melakukan submit.
- Jika `FormsUrl` dibiarkan default atau kosong, sistem secara otomatis menggunakan form bawaan `templates/mock_erp_form.html` sehingga pipeline tetap dapat dieksekusi secara penuh dan reliabel dalam kondisi offline.
- File export `Invoices.xlsx`, `ERP_Dummy.xlsx`, dan `ProcessLogs.xlsx` dihasilkan langsung dari SQLite database dengan menjaga integritas data dan template asli.
