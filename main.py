import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import sys
import tempfile
import uuid

from config.settings import AppConfig
from core.database import Database
from core.logger import AutomationLogger
from modules.approval import ApprovalService
from modules.archiver import FileArchiver
from modules.email_intake import EmailIntakeService
from modules.erp_poster import ERPBrowserPoster
from modules.exporter import ExcelExporter
from modules.extractor import InvoiceExtractor
from modules.image_preprocessor import ImageQualityPreprocessor
from modules.ocr_engine import OCREngine
from modules.validator import POValidator


def compute_file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def run_pipeline(
    source: str | None = None,
    headless: bool = False,
    auto_approve: bool = False,
    move_files: bool = False,
    force: bool = False,
    config_file: str | None = None,
    limit: int | None = None
) -> None:
    # 1. Initialize Configuration
    config = AppConfig.load(config_file)
    if headless:
        config.headless = True

    # 2. Initialize Core Services
    db = Database(config.db_path)
    logger = AutomationLogger(db)
    ocr = OCREngine(config.vision_api_key)
    validator = POValidator(config.purchase_orders_csv)
    approval_svc = ApprovalService(config, auto_approve=auto_approve)
    erp_poster = ERPBrowserPoster(config)
    archiver = FileArchiver(config.processed_dir)
    intake_svc = EmailIntakeService(config)
    exporter = ExcelExporter(db, config)

    # Clean up prior duplicate artifacts from previous runs
    removed_files = archiver.cleanup_duplicates()
    db_cleanup = db.cleanup_duplicate_records()
    if removed_files or db_cleanup["invoices_removed"]:
        logger.log("SYSTEM", "CLEANUP", "INFO",
                   f"Deduplication cleanup: removed {removed_files} redundant files, {db_cleanup['invoices_removed']} duplicate DB rows")

    logger.log("SYSTEM", "INITIALIZATION", "INFO",
               f"Threshold: {config.threshold_amount:,.0f} IDR | Headless: {config.headless}")

    # 3. Retrieve Invoices
    files = intake_svc.get_invoices_to_process(source)
    if not files:
        logger.log("SYSTEM", "INTAKE", "WARNING", "No invoice files found to process.")
        print("\n[!] No invoice files found. Place files in 'inbox/' or specify with --source.")
        return

    if limit:
        files = files[:limit]

    logger.log("SYSTEM", "INTAKE", "INFO", f"Loaded {len(files)} invoice(s) for processing.")
    print(f"\n>>> Starting IT Automation Pipeline ({len(files)} files found)...\n")

    # 4. Process Each Invoice End-to-End
    for idx, file_path in enumerate(files, 1):
        corr_id = f"CORR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
        file_name = file_path.name
        file_hash = compute_file_hash(file_path)

        print(f"[{idx}/{len(files)}] Processing: {file_name} (ID: {corr_id})")
        logger.log(corr_id, "INTAKE", "SUCCESS", f"Processing file: {file_name} (hash: {file_hash[:10]}...)")

        # Step 1.5: Idempotency / Deduplication Check
        if not force:
            existing = db.find_completed_invoice(file_hash=file_hash)
            if existing:
                msg = f"Invoice '{file_name}' already successfully processed with PostingRef '{existing.get('posting_ref')}'. Skipping duplicate ERP submission."
                logger.log(corr_id, "DEDUPLICATION", "SKIPPED", msg)
                print(f"    -> [DEDUPLICATION] {msg}")
                # Ensure properly archived in Success without numbered duplicate
                archiver.archive(file_path, "Success", move=move_files, overwrite=True)
                continue

        # Step 2: Computer Vision Quality Assessment & Pre-processing
        quality_report = None
        enhanced_temp_path = None
        try:
            quality_report, raw_img = ImageQualityPreprocessor.assess_quality(file_path)
            has_defects = (quality_report.is_blurry or quality_report.is_skewed or
                           quality_report.is_dark or quality_report.has_flash_glare or
                           quality_report.has_stains_noise)

            if has_defects:
                defect_desc = (f"Blur={quality_report.blur_score}, Skew={quality_report.skew_angle}°, "
                               f"Brightness={quality_report.brightness}, Glare={quality_report.glare_percentage}%")
                logger.log(corr_id, "IMAGE_QUALITY", "DEFECT_DETECTED", defect_desc)

                # Emit guidance for operators
                for guide in quality_report.guidelines:
                    logger.log(corr_id, "QUALITY_GUIDANCE", "ADVISORY", guide)
                    print(f"    -> [GUIDANCE] {guide}")

                # Generate enhanced image
                enhanced_cv = ImageQualityPreprocessor.enhance_image(raw_img, quality_report)
                temp_dir = Path(tempfile.gettempdir()) / "it_automation"
                temp_dir.mkdir(parents=True, exist_ok=True)
                enhanced_temp_path = temp_dir / f"enhanced_{file_path.name}"
                import cv2
                cv2.imwrite(str(enhanced_temp_path), enhanced_cv)
        except Exception as qe:
            logger.log(corr_id, "IMAGE_QUALITY", "WARNING", f"Quality check warning: {qe}")

        # Step 3: OCR & Regex Extraction (with auto-retry on enhanced image)
        extracted = None
        ocr_source = file_path

        try:
            raw_text = ocr.extract_text(ocr_source)
            extracted = InvoiceExtractor.extract(raw_text)

            # If extraction failed or incomplete, retry with enhanced image if available
            if (not extracted.is_valid) and enhanced_temp_path and enhanced_temp_path.exists():
                logger.log(corr_id, "OCR_EXTRACTION", "RETRY_ENHANCED", "Initial extraction incomplete. Retrying with enhanced image...")
                raw_text_enh = ocr.extract_text(enhanced_temp_path)
                extracted_enh = InvoiceExtractor.extract(raw_text_enh)
                if extracted_enh.is_valid or (extracted_enh.amount and not extracted.amount):
                    extracted = extracted_enh
                    logger.log(corr_id, "AUTO_ENHANCEMENT", "RECOVERED", "Successfully recovered invoice data using CV filters")

        except Exception as e:
            logger.log(corr_id, "OCR_EXTRACTION", "FAILED", f"OCR error: {e}")
            archiver.archive(file_path, "Failed", move=move_files, overwrite=True)
            continue
        finally:
            if enhanced_temp_path and enhanced_temp_path.exists():
                try:
                    enhanced_temp_path.unlink()
                except OSError:
                    pass

        # Check secondary deduplication by Invoice Number if already in DB
        if extracted and extracted.invoice_number and not force:
            existing_by_num = db.find_completed_invoice(invoice_number=extracted.invoice_number)
            if existing_by_num:
                stored_hash = existing_by_num.get("file_hash")
                if stored_hash is None or stored_hash == file_hash:
                    # Same document previously processed, sync file_hash
                    if stored_hash is None:
                        db.update_invoice(existing_by_num["correlation_id"], {"file_hash": file_hash})
                    msg = f"Invoice '{file_name}' ({extracted.invoice_number}) already successfully posted with Ref '{existing_by_num.get('posting_ref')}'. Skipping duplicate."
                    logger.log(corr_id, "DEDUPLICATION", "SKIPPED", msg)
                    print(f"    -> [DEDUPLICATION] {msg}")
                    archiver.archive(file_path, "Success", move=move_files, overwrite=True)
                    continue
                else:
                    msg = f"InvoiceNumber '{extracted.invoice_number}' already posted to ERP with Ref '{existing_by_num.get('posting_ref')}'. Duplicate document rejected."
                    logger.log(corr_id, "DEDUPLICATION", "REJECTED", msg)
                    print(f"    -> [DEDUPLICATION] {msg}")
                    archiver.archive(file_path, "Rejected", move=move_files, overwrite=True)
                    continue

        if not extracted.is_valid:
            error_reason = extracted.error_message or "Extraction failed"
            # Provide actionable remediation advice
            if "Corrupted" in error_reason:
                error_reason += ". SARAN: Minta vendor mengirimkan ulang file PDF/gambar invoice resmi yang bersih."
            elif "PO_Number" in error_reason:
                error_reason += ". SARAN: Nomor PO terpotong/tidak terbaca. Pastikan nomor PO tercetak lengkap."

            logger.log(corr_id, "OCR_EXTRACTION", "FAILED", error_reason)
            db.save_invoice({
                "correlation_id": corr_id,
                "file_path": str(file_path),
                "file_hash": file_hash,
                "invoice_number": extracted.invoice_number or "UNKNOWN",
                "vendor_name": extracted.vendor_name or "UNKNOWN",
                "po_number": extracted.po_number or "UNKNOWN",
                "amount": extracted.amount or 0.0,
                "currency": extracted.currency,
                "match_status": "INVALID",
                "needs_approval": False,
                "approval_status": "N/A",
                "status": "FAILED"
            })
            archiver.archive(file_path, "Failed", move=move_files, overwrite=True)
            continue

        logger.log(corr_id, "OCR_EXTRACTION", "SUCCESS",
                   f"Extracted Inv:{extracted.invoice_number}, Vendor:{extracted.vendor_name}, PO:{extracted.po_number}, Amt:{extracted.amount:,.0f} {extracted.currency}")

        # Step 4: Initial Database Save
        invoice_record = {
            "correlation_id": corr_id,
            "file_path": str(file_path),
            "file_hash": file_hash,
            "invoice_number": extracted.invoice_number,
            "vendor_name": extracted.vendor_name,
            "po_number": extracted.po_number,
            "amount": extracted.amount,
            "currency": extracted.currency,
            "match_status": "PENDING",
            "needs_approval": False,
            "approval_status": "PENDING",
            "posting_ref": "",
            "posted_at": "",
            "status": "PROCESSING"
        }
        db.save_invoice(invoice_record)
        logger.log(corr_id, "DATABASE_SAVE", "SUCCESS", "Invoice record registered in SQLite")

        # Step 5: PO Validation with Actionable Remediation Guidance
        val_res = validator.validate(extracted.po_number, extracted.vendor_name, extracted.amount, extracted.currency)
        validation_msg = val_res.message
        if val_res.match_status == "NOT_FOUND":
            validation_msg += f". SARAN: Buat dan approve PO '{extracted.po_number}' di PurchaseOrders.csv."
        elif val_res.match_status == "MISMATCH":
            validation_msg += f". SARAN: Sesuaikan vendor/nominal dengan PO resmi ({val_res.expected_vendor}, {val_res.expected_amount})."

        logger.log(corr_id, "PO_VALIDATION", val_res.match_status, validation_msg)
        db.update_invoice(corr_id, {"match_status": val_res.match_status})

        if not val_res.is_valid:
            db.update_invoice(corr_id, {"status": "REJECTED"})
            archiver.archive(file_path, "Rejected", move=move_files, overwrite=True)
            continue

        # Step 6: Approval Workflow
        approval = approval_svc.evaluate(
            corr_id,
            extracted.invoice_number or "",
            extracted.vendor_name or "",
            extracted.amount or 0.0,
            extracted.currency
        )
        logger.log(corr_id, "APPROVAL", approval.status, approval.message)
        db.update_invoice(corr_id, {
            "needs_approval": "TRUE" if approval.needs_approval else "FALSE",
            "approval_status": approval.status
        })

        if not approval.approved:
            db.update_invoice(corr_id, {"status": "REJECTED"})
            archiver.archive(file_path, "Rejected", move=move_files, overwrite=True)
            continue

        # Step 7: ERP Browser Posting
        posting_ref = erp_poster.generate_posting_ref(corr_id)
        post_payload = {
            "invoice_number": extracted.invoice_number,
            "vendor_name": extracted.vendor_name,
            "po_number": extracted.po_number,
            "amount": extracted.amount,
            "currency": extracted.currency
        }
        posting_result = erp_poster.post_invoice(post_payload, posting_ref)

        if posting_result.success:
            logger.log(corr_id, "ERP_POSTING", "SUCCESS", f"Posted to ERP with Ref: {posting_ref}")
            # Save into erp_postings
            db.save_erp_posting({
                "invoice_number": extracted.invoice_number,
                "vendor_name": extracted.vendor_name,
                "po_number": extracted.po_number,
                "amount": extracted.amount,
                "currency": extracted.currency,
                "posting_date": datetime.now().strftime("%Y-%m-%d"),
                "approval_status": approval.status,
                "posting_ref": posting_ref,
                "submitted_at": posting_result.submitted_at
            })
            # Update invoice record
            db.update_invoice(corr_id, {
                "posting_ref": posting_ref,
                "posted_at": posting_result.submitted_at,
                "status": "COMPLETED"
            })
            archived_path = archiver.archive(file_path, "Success", move=move_files, overwrite=True)
            db.update_invoice(corr_id, {"file_path": str(archived_path)})
        else:
            logger.log(corr_id, "ERP_POSTING", "FAILED", posting_result.message)
            db.update_invoice(corr_id, {"status": "FAILED"})
            archiver.archive(file_path, "Failed", move=move_files, overwrite=True)

    # Step 8: Export Excel Files
    print("\n>>> Exporting reports according to templates...")
    exports = exporter.export_all()
    logger.log("SYSTEM", "EXCEL_EXPORT", "SUCCESS",
               f"Exported Invoices.xlsx, ERP_Dummy.xlsx, ProcessLogs.xlsx")

    print("\n================ PIPELINE EXECUTION SUMMARY ================")
    print(f" SQLite Database  : {config.db_path}")
    print(f" Invoices Export  : {exports['invoices']}")
    print(f" ERP Dummy Export : {exports['erp_dummy']}")
    print(f" Process Logs     : {exports['process_logs']}")
    print(f" Processed Folder : {config.processed_dir}")
    print("============================================================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="IT Automation - End-to-End Invoice Processing Pipeline")
    parser.add_argument("--source", type=str, default=None, help="Source folder of invoices or 'email' for IMAP")
    parser.add_argument("--headless", action="store_true", help="Run browser automation in headless mode")
    parser.add_argument("--auto-approve", action="store_true", help="Auto approve invoices exceeding threshold (for automated tests)")
    parser.add_argument("--move", action="store_true", help="Move processed files instead of copying")
    parser.add_argument("--force", action="store_true", help="Force re-processing even if invoice was already completed")
    parser.add_argument("--config", type=str, default=None, help="Path to custom Config.xlsx")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of invoices to process")

    args = parser.parse_args()
    run_pipeline(
        source=args.source,
        headless=args.headless,
        auto_approve=args.auto_approve,
        move_files=args.move,
        force=args.force,
        config_file=args.config,
        limit=args.limit
    )


if __name__ == "__main__":
    main()
