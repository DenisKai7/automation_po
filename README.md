# IT Automation System - End-to-End Invoice Processing

Sistem otomasi pemrosesan faktur (invoice) berbasis Python. Menangani alur kerja lengkap: ekstraksi dokumen, validasi master data, alur persetujuan, entri data ERP via browser, hingga audit logging dan pengarsipan.

---

## 1. Ringkasan Sistem Otomasi

Sistem memproses faktur masuk secara sekuensial dengan tahapan:
1. **Intake**: Membaca file faktur (`.jpg`, `.jpeg`, `.png`, `.pdf`) dari folder lokal (`inbox/`, `Sample Invoice/`) atau mailbox IMAP email.
2. **Preprocessing & OCR**: Inspeksi kualitas gambar (blur, pencahayaan, kemiringan, noda) dengan OpenCV, dilanjutkan ekstraksi teks via Google Cloud Vision API.
3. **Ekstraksi Data**: Parser berbasis RegEx deterministik untuk mengambil `InvoiceNumber`, `VendorName`, `PO_Number`, `Amount`, dan `Currency`.
4. **Validasi Master PO**: Verifikasi silang data faktur terhadap `PurchaseOrders.csv` (kecocokan vendor, status aktif PO, mata uang, dan nominal).
5. **Approval Workflow**: Evaluasi batas nominal (`ThresholdAmount` dari `Config.xlsx`). Faktur melebihi batas memerlukan persetujuan via email approver (`aldidadenis@gmail.com`) atau prompt terminal interaktif.
6. **Posting ERP Form**: Otomasi browser (Microsoft Edge / Google Chrome) untuk mengisi form ERP (Google Forms / Microsoft Forms / mock HTML offline) dan menghasilkan `PostingRef`.
7. **Export & Archiving**: Sinkronisasi data transaksi ke file Excel (`Invoices.xlsx`, `ERP_Dummy.xlsx`, `ProcessLogs.xlsx`) serta pemindahan fisik dokumen ke `Processed/Success/`, `Processed/Rejected/`, atau `Processed/Failed/`.

---

## 2. Prasyarat & Persiapan

Siapkan komponen berikut sebelum instalasi:
- **Python**: Versi `3.10` atau lebih baru.
- **Web Browser**: Microsoft Edge atau Google Chrome terpasang di sistem.
- **Google Cloud Vision API Key**: Kunci API aktif (sudah disertakan default di `.env.example`).
- **Form ERP URL**: Tautan Google Form dengan 6 field (Invoice Number, Vendor Name, PO Number, Amount, Currency, Posting Reference). Jika tidak diisi, sistem otomatis beralih ke form lokal `templates/mock_erp_form.html`.
- **Kredensial Mailbox (Opsional)**: Akun Gmail + App Password jika menggunakan fitur intake email IMAP atau pengiriman email persetujuan SMTP live.

---

## 3. Instalasi & Setup Awal

Panduan setup untuk pengguna atau developer baru:

### 1. Clone Repository
```bash
git clone <repository_url>
cd "IT Automation Developer Use Case"
```

### 2. Buat & Aktifkan Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependensi
```bash
pip install -r requirements.txt
```

### 4. Konfigurasi Environment (`.env`)
Salin file `.env.example` ke `.env`:
```bash
# Windows PowerShell
Copy-Item .env.example .env

# Bash
cp .env.example .env
```
Sesuaikan isi `.env` sesuai kebutuhan:
```ini
# Google Cloud Vision API Key
VISION_API_KEY=AIzaSyD9bQ80NIXZyQYz_PclqLKYTlUUusrV6iA

# Mailbox (Opsional - IMAP/SMTP)
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
IMAP_USER=your_email@gmail.com
IMAP_PASSWORD=your_app_password

SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password

# Pengaturan Browser & Form ERP
HEADLESS=false
BROWSER_TYPE=edge
FORMS_URL=https://docs.google.com/forms/d/e/YOUR_FORM_ID/viewform
```

### 5. Konfigurasi Bisnis (`Config.xlsx`)
File `Config.xlsx` (sheet `Config_T`) memuat parameter operasional:
- `ThresholdAmount`: Ambang batas nominal untuk approval (default: `1000000`).
- `ApproverEmail`: Email tujuan approval request & notifikasi (default: `aldidadenis@gmail.com`).
- `FormsUrl`: URL Google Form ERP (kosongkan untuk menggunakan mock HTML offline).
- `ExcelERPPath`: Lokasi file export ERP (`ERP_Dummy.xlsx`).

---

## 4. Cara Menjalankan Sistem

### Mode Eksekusi Utama

1. **Jalankan Uji Verifikasi Mandiri (Self-Check Tests)**
   ```bash
   python tests/test_automation.py
   ```

2. **Proses Batch Faktur Contoh (Auto-Approve + Visible Browser)**
   ```bash
   python main.py --source "Sample Invoice" --auto-approve
   ```

3. **Proses Mode Headless (Browser di Latar Belakang)**
   ```bash
   python main.py --source "Sample Invoice" --auto-approve --headless
   ```

4. **Proses dengan Approval Manual Interaktif (Terminal Prompt)**
   ```bash
   python main.py --source "Sample Invoice"
   ```

5. **Proses dari Email Inbox (IMAP Live)**
   ```bash
   python main.py --source email
   ```

6. **Memindahkan File Asli (Bukan Copy)**
   ```bash
   python main.py --source inbox --move
   ```

### Ringkasan Argumen CLI

| Argumen | Tipe | Deskripsi |
| :--- | :--- | :--- |
| `--source` | `str` | Sumber file faktur (`"Sample Invoice"`, `inbox`, `email`, atau path folder) |
| `--auto-approve` | `flag` | Otomatis menyetujui faktur di atas ambang batas tanpa konfirmasi |
| `--headless` | `flag` | Menjalankan browser posting ERP tanpa menampilkan antarmuka visual |
| `--move` | `flag` | Memindahkan file sumber ke direktori `Processed/` alih-alih menyalin |
| `--keep-history` | `flag` | Mempertahankan data SQLite lama tanpa reset sinkronisasi batch |
| `--limit` | `int` | Membatasi jumlah faktur yang diproses dalam satu sesi |

---

## 5. Arsitektur & Struktur Kode

### Arsitektur Perangkat Lunak

Sistem dibangun berdasarkan prinsip **Modular Clean Architecture** dan **Separation of Concerns (SoC)**:

```
                  ┌────────────────────────┐
                  │        main.py         │ (Pipeline Orchestrator)
                  └───────────┬────────────┘
                              │
     ┌────────────────────────┼────────────────────────┐
     ▼                        ▼                        ▼
┌─────────────┐        ┌─────────────┐          ┌─────────────┐
│   config/   │        │    core/    │          │  modules/   │
│ settings.py │        │ database.py │          │ (Domain Svc)│
└─────────────┘        │  logger.py  │          └─────────────┘
                       └─────────────┘                 │
     ┌─────────────────────────────────────────────────┼────────────────────────┐
     ▼                   ▼              ▼              ▼                        ▼
email_intake     image_preprocessor  ocr_engine    extractor                validator
     ▼                   ▼              ▼              ▼                        ▼
approval            erp_poster       exporter      archiver             (OpenCV/RegEx)
```

1. **Orchestrator Layer (`main.py`)**: Mengendalikan siklus hidup eksekusi, penanganan error per item faktur, deduplikasi file, dan sinkronisasi sesi database.
2. **Configuration Layer (`config/settings.py`)**: Penggabung hierarkis konfigurasi antara file Excel (`Config.xlsx`), environment variables (`.env`), dan nilai *fallback default*.
3. **Core & Persistence Layer (`core/`)**:
   - `database.py`: Mengelola koneksi SQLite, skema tabel (`invoices`, `erp_postings`, `process_logs`), status transaksi, dan mekanisme *fresh batch synchronization*.
   - `logger.py`: Pencatatan log terstruktur dua arah (terminal output dan sinkronisasi tabel audit log database).
4. **Domain Services Layer (`modules/`)**:
   - `email_intake.py`: Menangani koneksi IMAP, unduh lampiran, dan pembacaan folder lokal.
   - `image_preprocessor.py`: Deteksi kualitas citra (Laplacian blur, kontras gelap/terang, refleksi flash, noda) dan koreksi otomatis skew/kemiringan.
   - `ocr_engine.py`: Klien REST API Google Cloud Vision untuk ekstraksi raw text.
   - `extractor.py`: RegEx engine deterministik untuk ekstraksi metadata invoice tanpa ketergantungan model NLP berat.
   - `validator.py`: Business rule validator terhadap master `PurchaseOrders.csv`.
   - `approval.py`: Evaluasi batas persetujuan serta pengiriman notifikasi/konfirmasi via SMTP ke `aldidadenis@gmail.com`.
   - `erp_poster.py`: Automasi web form berbasis native Chrome DevTools Protocol (CDP) dengan fallback Selenium.
   - `exporter.py`: Pengekspor data SQLite ke template Excel secara konsisten dan aman dari *file lock*.
   - `archiver.py`: Pengarsip file faktur dengan hashing SHA-256 untuk mencegah duplikasi file.

### Struktur Direktori

```
IT Automation Developer Use Case/
├── config/
│   ├── __init__.py
│   └── settings.py              # Loader konfigurasi dinamis (Config.xlsx + .env)
├── core/
│   ├── __init__.py
│   ├── database.py              # Repository SQLite & skema tabel transaksi
│   └── logger.py                # Logger audit terstruktur & sink database
├── modules/
│   ├── __init__.py
│   ├── approval.py              # Logika approval threshold & notifikasi email
│   ├── archiver.py              # Pengarsip & deduplikasi file ke folder Processed
│   ├── email_intake.py          # Listener IMAP & loader attachment lokal
│   ├── erp_poster.py            # Otomasi pengisian form browser (Edge / Chrome)
│   ├── exporter.py              # Sinkronisasi export SQLite ke format Excel
│   ├── extractor.py             # Parser RegEx deterministik bidang faktur
│   ├── image_preprocessor.py    # Asesmen kualitas gambar & koreksi citra OpenCV
│   ├── ocr_engine.py            # Klien Google Cloud Vision OCR
│   └── validator.py             # Validasi kecocokan master PurchaseOrders.csv
├── templates/
│   ├── Config.xlsx              # Template file konfigurasi operasional bisnis
│   ├── ERP_Dummy.xlsx           # Template data luaran PostedInvoices
│   ├── Invoices.xlsx            # Template data luaran Invoices_T
│   ├── ProcessLogs.xlsx         # Template data luaran Logs_T audit trail
│   └── mock_erp_form.html       # Form ERP HTML mandiri untuk pengujian luring
├── tests/
│   ├── __init__.py
│   └── test_automation.py       # Test suite verifikasi mandiri logika modul
├── data/
│   └── automation.db            # Database SQLite transaksi (dibuat otomatis)
├── inbox/                       # Direktori penampung faktur masuk lokal
├── Processed/                   # Direktori arsip hasil akhir faktur
│   ├── Failed/                  # Faktur gagal baca/ekstraksi
│   ├── Rejected/                # Faktur ditolak PO / ditolak approver
│   └── Success/                 # Faktur tervalidasi & berhasil diposting
├── Sample Invoice/              # Sampel gambar faktur untuk pengujian
├── .env.example                 # Contoh template konfigurasi kredensial
├── .env                         # Konfigurasi aktif lokal (diabaikan oleh git)
├── .gitignore                   # Konfigurasi ignore file cache/database/secrets
├── Config.xlsx                  # File aktif konfigurasi operasional
├── ERP_Dummy.xlsx               # Output sinkronisasi posted ERP records
├── Invoices.xlsx                # Output sinkronisasi seluruh record faktur
├── ProcessLogs.xlsx             # Output sinkronisasi riwayat audit trail log
├── PurchaseOrders.csv           # Master data Purchase Order aktif
├── main.py                      # CLI entrypoint & orchestrator pipeline
├── requirements.txt             # Daftar dependensi modul Python
└── README.md                    # Dokumentasi teknis sistem
```
