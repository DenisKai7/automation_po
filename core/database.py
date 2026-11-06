import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import openpyxl


class Database:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    correlation_id TEXT PRIMARY KEY,
                    file_path TEXT,
                    file_hash TEXT,
                    invoice_number TEXT,
                    vendor_name TEXT,
                    po_number TEXT,
                    amount REAL,
                    currency TEXT,
                    match_status TEXT,
                    needs_approval TEXT,
                    approval_status TEXT,
                    posting_ref TEXT,
                    posted_at TEXT,
                    status TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS erp_postings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT,
                    vendor_name TEXT,
                    po_number TEXT,
                    amount REAL,
                    currency TEXT,
                    posting_date TEXT,
                    approval_status TEXT,
                    posting_ref TEXT UNIQUE,
                    submitted_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS process_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    correlation_id TEXT,
                    step TEXT,
                    result TEXT,
                    message TEXT
                )
            """)

            # Ensure file_hash column exists if database was created previously
            cursor.execute("PRAGMA table_info(invoices)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "file_hash" not in columns:
                cursor.execute("ALTER TABLE invoices ADD COLUMN file_hash TEXT")

            conn.commit()

    def reset_for_fresh_run(self) -> dict:
        """Clears old historical data so the new run uses only the active sample/updated dataset."""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM invoices")
            inv_c = c.rowcount
            c.execute("DELETE FROM erp_postings")
            erp_c = c.rowcount
            c.execute("DELETE FROM process_logs")
            log_c = c.rowcount
            conn.commit()
        return {"invoices_cleared": inv_c, "erp_cleared": erp_c, "logs_cleared": log_c}

    def find_completed_invoice(self, file_hash: Optional[str] = None, invoice_number: Optional[str] = None) -> Optional[dict]:
        """Checks if the same file or invoice number was already successfully processed and posted to ERP."""
        with self.get_connection() as conn:
            if file_hash:
                row = conn.execute(
                    "SELECT * FROM invoices WHERE file_hash = ? AND status = 'COMPLETED'",
                    (file_hash,)
                ).fetchone()
                if row:
                    return dict(row)

            if invoice_number and invoice_number != "UNKNOWN":
                row = conn.execute(
                    "SELECT * FROM invoices WHERE invoice_number = ? AND status = 'COMPLETED'",
                    (invoice_number,)
                ).fetchone()
                if row:
                    return dict(row)

        return None

    def save_invoice(self, data: Dict[str, Any]) -> None:
        now = datetime.now().isoformat()
        file_hash = data.get("file_hash")
        inv_num = data.get("invoice_number")
        file_path = data.get("file_path", "")
        file_name = Path(file_path).name if file_path else ""

        with self.get_connection() as conn:
            existing = None
            if file_hash:
                existing = conn.execute("SELECT correlation_id FROM invoices WHERE file_hash = ?", (file_hash,)).fetchone()
            if not existing and inv_num and inv_num != "UNKNOWN":
                existing = conn.execute("SELECT correlation_id FROM invoices WHERE invoice_number = ?", (inv_num,)).fetchone()
            if not existing and file_name:
                existing = conn.execute("SELECT correlation_id FROM invoices WHERE file_path LIKE ?", (f"%{file_name}",)).fetchone()

            if existing:
                old_corr = existing["correlation_id"]
                conn.execute("""
                    UPDATE invoices SET
                        correlation_id = :correlation_id,
                        file_path = :file_path,
                        file_hash = :file_hash,
                        invoice_number = :invoice_number,
                        vendor_name = :vendor_name,
                        po_number = :po_number,
                        amount = :amount,
                        currency = :currency,
                        match_status = :match_status,
                        needs_approval = :needs_approval,
                        approval_status = :approval_status,
                        posting_ref = :posting_ref,
                        posted_at = :posted_at,
                        status = :status,
                        updated_at = :updated_at
                    WHERE correlation_id = :old_corr
                """, {
                    "correlation_id": data.get("correlation_id", old_corr),
                    "file_path": data.get("file_path", ""),
                    "file_hash": data.get("file_hash", ""),
                    "invoice_number": data.get("invoice_number", ""),
                    "vendor_name": data.get("vendor_name", ""),
                    "po_number": data.get("po_number", ""),
                    "amount": data.get("amount", 0.0),
                    "currency": data.get("currency", "IDR"),
                    "match_status": data.get("match_status", ""),
                    "needs_approval": "TRUE" if data.get("needs_approval") else "FALSE",
                    "approval_status": data.get("approval_status", ""),
                    "posting_ref": data.get("posting_ref", ""),
                    "posted_at": data.get("posted_at", ""),
                    "status": data.get("status", ""),
                    "updated_at": now,
                    "old_corr": old_corr
                })
                conn.commit()
                return

            conn.execute("""
                INSERT INTO invoices (
                    correlation_id, file_path, file_hash, invoice_number, vendor_name, po_number,
                    amount, currency, match_status, needs_approval, approval_status,
                    posting_ref, posted_at, status, created_at, updated_at
                ) VALUES (
                    :correlation_id, :file_path, :file_hash, :invoice_number, :vendor_name, :po_number,
                    :amount, :currency, :match_status, :needs_approval, :approval_status,
                    :posting_ref, :posted_at, :status, :created_at, :updated_at
                )
            """, {
                "correlation_id": data.get("correlation_id", ""),
                "file_path": data.get("file_path", ""),
                "file_hash": data.get("file_hash", ""),
                "invoice_number": data.get("invoice_number", ""),
                "vendor_name": data.get("vendor_name", ""),
                "po_number": data.get("po_number", ""),
                "amount": data.get("amount", 0.0),
                "currency": data.get("currency", "IDR"),
                "match_status": data.get("match_status", ""),
                "needs_approval": "TRUE" if data.get("needs_approval") else "FALSE",
                "approval_status": data.get("approval_status", ""),
                "posting_ref": data.get("posting_ref", ""),
                "posted_at": data.get("posted_at", ""),
                "status": data.get("status", ""),
                "created_at": data.get("created_at", now),
                "updated_at": now
            })
            conn.commit()

    def update_invoice(self, correlation_id: str, updates: Dict[str, Any]) -> None:
        updates["updated_at"] = datetime.now().isoformat()
        set_clauses = [f"{k} = :{k}" for k in updates.keys()]
        updates["correlation_id"] = correlation_id
        sql = f"UPDATE invoices SET {', '.join(set_clauses)} WHERE correlation_id = :correlation_id"
        with self.get_connection() as conn:
            conn.execute(sql, updates)
            conn.commit()

    def save_erp_posting(self, data: Dict[str, Any]) -> None:
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO erp_postings (
                    invoice_number, vendor_name, po_number, amount, currency,
                    posting_date, approval_status, posting_ref, submitted_at
                ) VALUES (
                    :invoice_number, :vendor_name, :po_number, :amount, :currency,
                    :posting_date, :approval_status, :posting_ref, :submitted_at
                )
            """, {
                "invoice_number": data.get("invoice_number", ""),
                "vendor_name": data.get("vendor_name", ""),
                "po_number": data.get("po_number", ""),
                "amount": data.get("amount", 0.0),
                "currency": data.get("currency", "IDR"),
                "posting_date": data.get("posting_date", datetime.now().strftime("%Y-%m-%d")),
                "approval_status": data.get("approval_status", ""),
                "posting_ref": data.get("posting_ref", ""),
                "submitted_at": data.get("submitted_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            })
            conn.commit()

    def add_process_log(self, correlation_id: str, step: str, result: str, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO process_logs (timestamp, correlation_id, step, result, message)
                VALUES (?, ?, ?, ?, ?)
            """, (ts, correlation_id, step, result, message))
            conn.commit()

    def cleanup_duplicate_records(self) -> dict:
        """Deduplicates historical runs: preserves the latest record per invoice."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Deduplicate erp_postings by invoice_number (keep highest id)
            cursor.execute("""
                DELETE FROM erp_postings
                WHERE id NOT IN (
                    SELECT MAX(id) FROM erp_postings GROUP BY invoice_number
                )
            """)
            erp_removed = cursor.rowcount

            # Deduplicate invoices by (file_path, invoice_number) keeping latest updated_at
            cursor.execute("""
                DELETE FROM invoices
                WHERE correlation_id NOT IN (
                    SELECT correlation_id FROM (
                        SELECT correlation_id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY CASE 
                                       WHEN invoice_number != 'UNKNOWN' AND invoice_number IS NOT NULL 
                                       THEN invoice_number 
                                       ELSE file_path 
                                   END 
                                   ORDER BY updated_at DESC
                               ) as rn
                        FROM invoices
                    ) WHERE rn = 1
                )
            """)
            inv_removed = cursor.rowcount
            conn.commit()

        return {"erp_postings_removed": erp_removed, "invoices_removed": inv_removed}

    def _save_workbook_safely(self, wb: openpyxl.Workbook, target_path: Path | str) -> Path:
        target = Path(target_path)
        try:
            wb.save(target)
            return target
        except PermissionError:
            # Fallback if file is locked by Excel
            stem = target.stem
            fallback = target.parent / f"{stem}_exported.xlsx"
            wb.save(fallback)
            print(f"[!] PERINGATAN: File '{target.name}' terkunci (sedang dibuka Excel). Hasil diekspor ke '{fallback.name}'.")
            return fallback

    def export_invoices(self, template_path: Path | str, output_path: Path | str) -> Path:
        wb = openpyxl.load_workbook(template_path)
        ws = wb["Invoices_T"] if "Invoices_T" in wb.sheetnames else wb.active

        while ws.max_row > 1:
            ws.delete_rows(2)

        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT correlation_id, file_path, invoice_number, vendor_name, po_number,
                       amount, currency, match_status, needs_approval, approval_status,
                       posting_ref, posted_at, status, created_at, updated_at
                FROM invoices
                ORDER BY created_at ASC
            """).fetchall()

            for r in rows:
                ws.append(list(r))

        return self._save_workbook_safely(wb, output_path)

    def export_erp_dummy(self, template_path: Path | str, output_path: Path | str) -> Path:
        wb = openpyxl.load_workbook(template_path)
        ws = wb["PostedInvoices"] if "PostedInvoices" in wb.sheetnames else wb.active

        while ws.max_row > 1:
            ws.delete_rows(2)

        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT invoice_number, vendor_name, po_number, amount, currency,
                       posting_date, approval_status, posting_ref, submitted_at
                FROM erp_postings
                ORDER BY id ASC
            """).fetchall()

            for r in rows:
                ws.append(list(r))

        return self._save_workbook_safely(wb, output_path)

    def export_process_logs(self, template_path: Path | str, output_path: Path | str) -> Path:
        wb = openpyxl.load_workbook(template_path)
        ws = wb["Logs_T"] if "Logs_T" in wb.sheetnames else wb.active

        while ws.max_row > 1:
            ws.delete_rows(2)

        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT timestamp, correlation_id, step, result, message
                FROM process_logs
                ORDER BY id ASC
            """).fetchall()

            for r in rows:
                ws.append(list(r))

        return self._save_workbook_safely(wb, output_path)
