# Panduan Eksekusi & Troubleshooting IT Automation

## 1. Perintah Eksekusi Utama

### Menjalankan Seluruh Faktur Sampel (Mode Otomatis & Cepat)
```bash
python main.py --source "Sample Invoice" --auto-approve --headless
```

### Menjalankan dengan Tampilan Browser Visible (Untuk Perekaman Layar / Reviewer)
```bash
python main.py --source "Sample Invoice" --auto-approve
```

### Menjalankan dengan Konfirmasi Interaktif Approval
Setiap invoice dengan nominal di atas `ThresholdAmount` (1.000.000 IDR) akan meminta konfirmasi `(Y/n)` di terminal:
```bash
python main.py --source "Sample Invoice"
```

### Menjalankan Unit & Integration Tests
```bash
python tests/test_automation.py
```

---

## 2. Penanganan Duplikasi (Deduplication Mechanism)

Sistem telah dilengkapi dengan mekanisme anti-duplikasi idempotensial:
1. **Pencegahan Double Posting ERP:**
   - Sistem mencatat nilai hash SHA-256 dari setiap file invoice dan status `COMPLETED`.
   - Jika file atau nomor faktur yang sama diproses ulang, sistem otomatis memberikan status `[DEDUPLICATION] [SKIPPED]` dan tidak melakukan submit ganda ke form ERP.
2. **Arsip File Bersih Tanpa Suffix `_1`, `_2`:**
   - Modul `FileArchiver` menimpa (overwrite) file yang identik di dalam folder target `/Processed/<Category>` dan menghapus salinan lama di kategori lain.
   - Fungsi pembersih otomatis dijalankan saat pipeline mulai untuk menghapus sisa file `_1`, `_2` dari eksekusi sebelumnya.
3. **Penyimpanan Excel Aman (File Lock Resilient):**
   - Jika file `Invoices.xlsx`, `ERP_Dummy.xlsx`, atau `ProcessLogs.xlsx` sedang dibuka di aplikasi Microsoft Excel saat eksekusi, sistem otomatis menyimpan ke `*_exported.xlsx` agar program tidak crash karena `PermissionError`.

---

## 3. Penanganan Masalah Kualitas Gambar (Computer Vision Preprocessor)

Modul `modules/image_preprocessor.py` secara otomatis memeriksa 5 jenis anomali kualitas gambar pada setiap sampel faktur:

| Jenis Masalah | Metode Deteksi Otomatis | Filter Auto-Enhancement | Panduan Tindakan untuk Operator / Pengirim |
| :--- | :--- | :--- | :--- |
| **Gambar Blur / Buram** | Laplacian Variance < 90.0 (`report.blur_score`) | Unsharp Masking filter (`cv2.addWeighted` + Gaussian Blur) | **Aktifkan auto-focus**, stabilkan posisi kamera/tangan saat memotret, atau gunakan scanner fisik dengan resolusi minimal 300 DPI. |
| **Orientasi Miring (Skewed)** | Probabilistic Hough Line Transform (`cv2.HoughLinesP`) | Affine Transformation rotation matrix (`cv2.warpAffine`) | Posisikan smartphone / scanner **sejajar tegak lurus (90°)** terhadap batas dokumen, bukan dari sudut miring (oblique). |
| **Gambar Gelap (Underexposed)** | Rata-rata intensitas piksel abu-abu < 75.0 (`report.brightness`) | Gamma Correction (γ=1.8) + CLAHE (Contrast Limited Adaptive Histogram Equalization) | **Tingkatkan pencahayaan ruangan**, hindari bayangan tangan yang menutupi dokumen, atau aktifkan kompensasi eksposur kamera (+1 EV). |
| **Terkena Flash / Glare** | Rasio piksel jenuh (> 245) terpusat atau standar deviasi tinggi | Background Illumination Division (`cv2.divide` dengan Gaussian illumination map) | **Matikan lampu flash kamera**. Hindari memotret dokumen di bawah lampu sorot langsung atau di dalam map plastik yang memantulkan cahaya. |
| **Noda / Kotoran / Noise** | Residual intensitas setelah Bilateral Filter > 6.0 | Bilateral Denoising + Morphological Opening | **Bersihkan permukaan fisik dokumen** dari noda cairan, debu, atau coretan tinta yang menutupi informasi penting sebelum dipindai. |

---

## 4. Analisis Hasil Sampel Invoice (Mengapa Berstatus Rejected / Failed)

Dari 18 sampel faktur yang disediakan:

1. **Berstatus SUCCESS (Diposting ke ERP & Masuk `/Processed/Success`):**
   - `sample_invoice_1.jpg`: PO-001 (PT Maju Jaya, 1.200.000 IDR) -> Cocok dengan baris 1 `PurchaseOrders.csv`.
   - `sample_invoice_2.jpg`: PO-002 (PT Sukses Makmur, 2.500.000 IDR) -> Cocok dengan baris 2 `PurchaseOrders.csv`.

2. **Berstatus REJECTED (Masuk `/Processed/Rejected`):**
   - `sample_invoice_3.jpg`: PO-999 (`PT Tidak Ada`) -> PO tidak ada di `PurchaseOrders.csv`.
   - `sample_invoice_4.jpg` s/d `14.jpg` & `16.jpg`: Nomor PO seperti `PO-010`, `PO-011`, `PO-012`, `PO-015`, `PO-016`, `PO-017`, `PO-019`, `PO-021` tidak terdaftar di file master `PurchaseOrders.csv`.
   - *Solusi:* Tambahkan baris PO terkait ke dalam `PurchaseOrders.csv` jika invoice tersebut sah dan ingin diproses.

3. **Berstatus FAILED (Masuk `/Processed/Failed`):**
   - `sample_invoice_15.jpg`: Teks nomor PO terpotong hanya menjadi `PO-` tanpa angka. Sistem mendeteksi `PO_Number is missing or incomplete`.
   - `sample_invoice_17.jpg` & `18.jpg`: Teks OCR mengandung karakter korup dan marker `INVALID` / `ERROR`. Sistem mendeteksi `Corrupted or invalid invoice data detected`.
   - *Solusi:* Minta pihak vendor untuk mengirimkan ulang dokumen faktur yang tidak terpotong dan tidak korup.
