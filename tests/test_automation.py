import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import shutil
import tempfile
import cv2
import numpy as np

from config.settings import AppConfig
from core.database import Database
from modules.approval import ApprovalService
from modules.archiver import FileArchiver
from modules.extractor import InvoiceExtractor
from modules.image_preprocessor import ImageQualityPreprocessor
from modules.validator import POValidator


def test_config_loader():
    cfg = AppConfig.load()
    assert cfg.threshold_amount == 1000000.0, f"Expected 1000000.0, got {cfg.threshold_amount}"
    assert cfg.approver_email == "aldidadenis@gmail.com", f"Expected aldidadenis@gmail.com, got {cfg.approver_email}"
    print("[PASS] test_config_loader")


def test_regex_extractor():
    # 1. Standard valid invoice
    t1 = """
    INVOICE INV-2025-001
    Vendor Name: PT Maju Jaya
    PO Number: PO-001
    Amount: 1200000 IDR
    Thank you for your business.
    """
    res1 = InvoiceExtractor.extract(t1)
    assert res1.is_valid is True
    assert res1.invoice_number == "INV-2025-001"
    assert res1.vendor_name == "PT Maju Jaya"
    assert res1.po_number == "PO-001"
    assert res1.amount == 1200000.0
    assert res1.currency == "IDR"

    # 2. Standalone lines without labels
    t2 = """
    Invoice
    INV-2026-011
    PT Connect Tech Dev
    PO-011
    3500000 IDR
    """
    res2 = InvoiceExtractor.extract(t2)
    assert res2.is_valid is True
    assert res2.invoice_number == "INV-2026-011"
    assert res2.vendor_name == "PT Connect Tech Dev"
    assert res2.po_number == "PO-011"
    assert res2.amount == 3500000.0

    # 3. Incomplete PO
    t3 = """
    Invoice INV-2026-021
    Vendor Name: PT Como Football
    PO Number: PO-
    Amount: 7500000 IDR
    """
    res3 = InvoiceExtractor.extract(t3)
    assert res3.is_valid is False
    assert res3.po_number is None

    # 4. Corrupt / invalid invoice
    t4 = """
    INvoic# INV-202X-02!
    Vendor Name: PT Como Footb@ll_Err
    INVALID
    PO Numbe# PO-021-ERROR
    Amount: $%*()_#!!! IDR ERROR
    """
    res4 = InvoiceExtractor.extract(t4)
    assert res4.is_valid is False
    print("[PASS] test_regex_extractor")


def test_po_validator():
    cfg = AppConfig.load()
    validator = POValidator(cfg.purchase_orders_csv)

    # Matched PO
    v1 = validator.validate("PO-001", "PT Maju Jaya", 1200000.0, "IDR")
    assert v1.is_valid is True
    assert v1.match_status == "MATCHED"

    # Not Found PO
    v2 = validator.validate("PO-999", "PT Tidak Ada", 950000.0, "IDR")
    assert v2.is_valid is False
    assert v2.match_status == "NOT_FOUND"

    # Vendor Mismatch
    v3 = validator.validate("PO-001", "PT Wrong Vendor", 1200000.0, "IDR")
    assert v3.is_valid is False
    assert v3.match_status == "MISMATCH"

    # Amount Mismatch
    v4 = validator.validate("PO-001", "PT Maju Jaya", 9999999.0, "IDR")
    assert v4.is_valid is False
    assert v4.match_status == "MISMATCH"

    print("[PASS] test_po_validator")


def test_approval_threshold():
    cfg = AppConfig.load()
    appr = ApprovalService(cfg, auto_approve=True)

    # Under threshold (1,000,000)
    d1 = appr.evaluate("CORR-01", "INV-001", "Vendor", 800000.0, "IDR")
    assert d1.needs_approval is False
    assert d1.status == "NOT_REQUIRED"
    assert d1.approved is True

    # Over threshold (auto-approve mode)
    d2 = appr.evaluate("CORR-02", "INV-002", "Vendor", 1500000.0, "IDR")
    assert d2.needs_approval is True
    assert d2.status == "APPROVED"
    assert d2.approved is True

    print("[PASS] test_approval_threshold")


def test_image_preprocessor_and_guidance():
    # 1. Test blur detection on blurry image
    cfg = AppConfig.load()
    sample_blurry = cfg.base_dir / "Sample Invoice" / "sample_invoice_4.jpg"
    if sample_blurry.exists():
        report, img = ImageQualityPreprocessor.assess_quality(sample_blurry)
        assert report.is_blurry is True, f"Expected blurry, got lap_var={report.blur_score}"
        assert any("BLUR" in g for g in report.guidelines)

        # Test enhancement
        enhanced = ImageQualityPreprocessor.enhance_image(img, report)
        assert enhanced is not None
        assert enhanced.shape == img.shape

    # 2. Test dark detection on sample_invoice_12.jpg
    sample_dark = cfg.base_dir / "Sample Invoice" / "sample_invoice_12.jpg"
    if sample_dark.exists():
        report_dark, img_dark = ImageQualityPreprocessor.assess_quality(sample_dark)
        assert report_dark.is_dark is True, f"Expected dark, got brightness={report_dark.brightness}"
        assert any("GELAP" in g for g in report_dark.guidelines)

    print("[PASS] test_image_preprocessor_and_guidance")


def test_archiver_deduplication():
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        proc_dir = tmp_dir / "Processed"
        archiver = FileArchiver(proc_dir)

        # Create dummy invoice file
        dummy_file = tmp_dir / "invoice_test.jpg"
        dummy_file.write_bytes(b"dummy image data")

        # Archive once
        p1 = archiver.archive(dummy_file, "Success", move=False, overwrite=True)
        assert p1.exists()
        assert p1.name == "invoice_test.jpg"

        # Archive second time (should overwrite, NOT create invoice_test_1.jpg)
        p2 = archiver.archive(dummy_file, "Success", move=False, overwrite=True)
        assert p2.name == "invoice_test.jpg"
        success_files = list((proc_dir / "Success").iterdir())
        assert len(success_files) == 1, f"Expected 1 file, got {len(success_files)}"

        # Archive to Rejected (should move out of Success to maintain single copy)
        p3 = archiver.archive(dummy_file, "Rejected", move=False, overwrite=True)
        assert p3.exists()
        assert not (proc_dir / "Success" / "invoice_test.jpg").exists()
        assert (proc_dir / "Rejected" / "invoice_test.jpg").exists()

        print("[PASS] test_archiver_deduplication")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_database_and_excel_export():
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        db_path = tmp_dir / "test.db"
        db = Database(db_path)

        corr_id = "CORR-TEST-001"
        posting_ref = "POST-TEST-001"
        test_hash = "abc123hash"

        db.save_invoice({
            "correlation_id": corr_id,
            "file_path": "sample.jpg",
            "file_hash": test_hash,
            "invoice_number": "INV-2025-001",
            "vendor_name": "PT Maju Jaya",
            "po_number": "PO-001",
            "amount": 1200000.0,
            "currency": "IDR",
            "match_status": "MATCHED",
            "needs_approval": True,
            "approval_status": "APPROVED",
            "posting_ref": posting_ref,
            "posted_at": "2026-11-05 10:00:00",
            "status": "COMPLETED"
        })

        # Test find_completed_invoice
        found = db.find_completed_invoice(file_hash=test_hash)
        assert found is not None
        assert found["invoice_number"] == "INV-2025-001"

        db.save_erp_posting({
            "invoice_number": "INV-2025-001",
            "vendor_name": "PT Maju Jaya",
            "po_number": "PO-001",
            "amount": 1200000.0,
            "currency": "IDR",
            "posting_date": "2026-11-05",
            "approval_status": "APPROVED",
            "posting_ref": posting_ref,
            "submitted_at": "2026-11-05 10:00:00"
        })

        db.add_process_log(corr_id, "TEST_STEP", "SUCCESS", "All good")

        # Export Excel files
        cfg = AppConfig.load()
        inv_out = tmp_dir / "Invoices.xlsx"
        erp_out = tmp_dir / "ERP_Dummy.xlsx"
        log_out = tmp_dir / "ProcessLogs.xlsx"

        db.export_invoices(cfg.templates_dir / "Invoices.xlsx", inv_out)
        db.export_erp_dummy(cfg.templates_dir / "ERP_Dummy.xlsx", erp_out)
        db.export_process_logs(cfg.templates_dir / "ProcessLogs.xlsx", log_out)

        # Verify Invoices.xlsx
        wb_inv = openpyxl.load_workbook(inv_out)
        assert "Invoices_T" in wb_inv.sheetnames
        ws_inv = wb_inv["Invoices_T"]
        assert ws_inv.max_row == 2
        assert ws_inv.cell(row=2, column=1).value == corr_id
        assert ws_inv.cell(row=2, column=11).value == posting_ref  # PostingRef

        # Verify ERP_Dummy.xlsx
        wb_erp = openpyxl.load_workbook(erp_out)
        assert "PostedInvoices" in wb_erp.sheetnames
        ws_erp = wb_erp["PostedInvoices"]
        assert ws_erp.max_row == 2
        assert ws_erp.cell(row=2, column=8).value == posting_ref  # PostingRef matching!

        # Verify ProcessLogs.xlsx
        wb_log = openpyxl.load_workbook(log_out)
        assert "Logs_T" in wb_log.sheetnames
        ws_log = wb_log["Logs_T"]
        assert ws_log.max_row == 2
        assert ws_log.cell(row=2, column=2).value == corr_id

        print("[PASS] test_database_and_excel_export")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_approved_invoice_email_and_fresh_run():
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        db_path = tmp_dir / "sync_test.db"
        db = Database(db_path)

        # Seed data
        db.save_invoice({"correlation_id": "C1", "invoice_number": "INV-001", "status": "COMPLETED"})
        db.save_erp_posting({"invoice_number": "INV-001", "posting_ref": "REF-01"})
        db.add_process_log("C1", "TEST", "OK", "msg")

        # Test fresh run reset
        cleared = db.reset_for_fresh_run()
        assert cleared["invoices_cleared"] == 1
        assert cleared["erp_cleared"] == 1
        assert cleared["logs_cleared"] == 1

        with db.get_connection() as conn:
            assert conn.execute("SELECT count(*) FROM invoices").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM erp_postings").fetchone()[0] == 0

        # Test approved invoice email dispatch
        cfg = AppConfig.load()
        appr = ApprovalService(cfg, auto_approve=True)
        dummy_invoice = tmp_dir / "invoice.jpg"
        dummy_invoice.write_bytes(b"dummy")

        sent = appr.send_approved_invoice_email(
            correlation_id="C-TEST",
            invoice_number="INV-2025-001",
            vendor_name="PT Test",
            po_number="PO-001",
            amount=1000000.0,
            currency="IDR",
            posting_ref="REF-TEST",
            file_path=dummy_invoice
        )
        assert sent is True
        print("[PASS] test_approved_invoice_email_and_fresh_run")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    print(">>> Running Self-Verification Tests...")
    test_config_loader()
    test_regex_extractor()
    test_po_validator()
    test_approval_threshold()
    test_image_preprocessor_and_guidance()
    test_archiver_deduplication()
    test_database_and_excel_export()
    test_approved_invoice_email_and_fresh_run()
    print("\nALL AUTOMATION TESTS PASSED SUCCESSFULLY!")
