from dataclasses import dataclass
from datetime import datetime
import email
from email import encoders
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import imaplib
from pathlib import Path
import re
import smtplib
import time
from typing import Optional
from config.settings import AppConfig


@dataclass
class ApprovalDecision:
    needs_approval: bool
    status: str  # APPROVED, REJECTED, NOT_REQUIRED, PENDING, TIMEOUT
    approved: bool
    message: str


class ApprovalService:
    def __init__(self, config: AppConfig, auto_approve: bool = False, poll_timeout: int = 60):
        self.config = config
        self.auto_approve = auto_approve
        self.poll_timeout = poll_timeout

    def evaluate(self, correlation_id: str, invoice_number: str, vendor_name: str,
                 amount: float, currency: str, po_number: str = "") -> ApprovalDecision:
        threshold = self.config.threshold_amount
        if amount <= threshold:
            return ApprovalDecision(
                needs_approval=False,
                status="NOT_REQUIRED",
                approved=True,
                message=f"Amount {amount:,.0f} {currency} <= Threshold {threshold:,.0f} {currency}"
            )

        # Requires Approval
        print(f"\n[EMAIL_APPROVAL] PO Validated: Invoice {invoice_number} exceeds threshold ({amount:,.0f} > {threshold:,.0f} {currency}).")
        print(f"[EMAIL_APPROVAL] Requesting approval email to: {self.config.approver_email}")

        # If --auto-approve flag is explicitly enabled, bypass email waiting
        if self.auto_approve:
            return ApprovalDecision(
                needs_approval=True,
                status="APPROVED",
                approved=True,
                message=f"Auto-approved via --auto-approve: {amount:,.0f} {currency} > Threshold {threshold:,.0f} {currency}"
            )

        # Try sending real email if SMTP is configured
        if self.config.smtp_user and self.config.smtp_password:
            sent = self._send_approval_email(correlation_id, invoice_number, vendor_name, amount, currency, po_number)
            if sent:
                decision = self._poll_imap_reply(correlation_id, timeout_sec=self.poll_timeout)
                if decision:
                    return decision
        else:
            print(f"[EMAIL_APPROVAL] [INFO] SMTP_USER/SMTP_PASSWORD di .env belum diisi -> Menggunakan simulasi lokal.")

        # Interactive terminal fallback
        print("\n" + "=" * 60)
        print(f"[APPROVAL REQUIRED] Invoice: {invoice_number} | Correlation: {correlation_id}")
        print(f"Vendor: {vendor_name} | Amount: {amount:,.0f} {currency} | Threshold: {threshold:,.0f} {currency}")
        print(f"Approver Target: {self.config.approver_email}")
        print("=" * 60)
        try:
            choice = input("Approve invoice? (Y/n): ").strip().lower()
            if choice in ("y", "yes", ""):
                return ApprovalDecision(
                    needs_approval=True,
                    status="APPROVED",
                    approved=True,
                    message=f"Approved manually via interactive prompt ({self.config.approver_email})"
                )
            else:
                return ApprovalDecision(
                    needs_approval=True,
                    status="REJECTED",
                    approved=False,
                    message=f"Rejected manually via interactive prompt ({self.config.approver_email})"
                )
        except (EOFError, KeyboardInterrupt):
            return ApprovalDecision(
                needs_approval=True,
                status="REJECTED",
                approved=False,
                message="Non-interactive session: rejected by default"
            )

    def send_approved_invoice_email(
        self,
        correlation_id: str,
        invoice_number: str,
        vendor_name: str,
        po_number: str,
        amount: float,
        currency: str,
        posting_ref: str,
        file_path: Optional[Path | str] = None
    ) -> bool:
        """Sends approved invoice confirmation and attachment to approver/admin email."""
        target_email = self.config.approver_email
        subject = f"[INVOICE APPROVED] Invoice {invoice_number} - {vendor_name} (Ref: {posting_ref})"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        body = (
            f"Halo,\n\n"
            f"Faktur (Invoice) berikut telah BERHASIL DISETUJUI (APPROVED) dan diproses ke sistem ERP:\n\n"
            f"  • Nomor Invoice   : {invoice_number}\n"
            f"  • Nama Vendor     : {vendor_name}\n"
            f"  • Nomor PO        : {po_number}\n"
            f"  • Total Nominal   : {amount:,.0f} {currency}\n"
            f"  • Posting Ref ERP : {posting_ref}\n"
            f"  • Status          : APPROVED & POSTED\n"
            f"  • Timestamp       : {now_str}\n"
            f"  • Correlation ID  : {correlation_id}\n\n"
            f"Dokumen fisik invoice terlampir pada email ini.\n\n"
            f"Salam,\nIT Automation System"
        )

        msg = MIMEMultipart()
        msg["From"] = self.config.smtp_user or "automation@system.local"
        msg["To"] = target_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Attach file if available
        if file_path:
            p = Path(file_path)
            if p.exists() and p.is_file():
                try:
                    with open(p, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{p.name}"')
                    msg.attach(part)
                except Exception as ex:
                    print(f"[!] Warning attaching file: {ex}")

        # Send via SMTP if credentials available
        if self.config.smtp_user and self.config.smtp_password:
            try:
                with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(self.config.smtp_user, self.config.smtp_password)
                    server.send_message(msg)
                print(f"[EMAIL_NOTIFICATION] Live approved invoice email successfully sent to {target_email}")
                return True
            except Exception as e:
                print(f"[EMAIL_NOTIFICATION] Failed sending live email to {target_email}: {e}")
                return False

        # ponytail: offline mock notification, add live SMTP credentials in .env for external relay
        print(f"[EMAIL_NOTIFICATION] [INFO] SMTP_USER/SMTP_PASSWORD di .env belum diisi -> Email fisik TIDAK dikirim ke {target_email} (Simulasi Offline).")
        return True

    def _send_approval_email(self, correlation_id: str, invoice_number: str,
                             vendor_name: str, amount: float, currency: str, po_number: str = "") -> bool:
        try:
            msg = MIMEMultipart()
            msg["From"] = self.config.smtp_user
            msg["To"] = self.config.approver_email
            msg["Subject"] = f"[APPROVAL REQUIRED] PO Validation - Invoice {invoice_number} (Ref: {correlation_id})"
            msg["Message-ID"] = f"<APPROVAL-REQ-{correlation_id}@{self.config.smtp_server}>"

            body = (
                f"Hello Approver ({self.config.approver_email}),\n\n"
                f"An invoice has passed PO validation and requires your approval as it exceeds the threshold of {self.config.threshold_amount:,.0f} {currency}:\n\n"
                f"Invoice Number: {invoice_number}\n"
                f"Vendor Name: {vendor_name}\n"
                f"PO Number: {po_number}\n"
                f"Amount: {amount:,.0f} {currency}\n"
                f"Correlation ID: {correlation_id}\n\n"
                f"Please reply to this email with 'APPROVE' or 'REJECT'.\n\n"
                f"Best regards,\nIT Automation System"
            )
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.config.smtp_user, self.config.smtp_password)
                server.send_message(msg)
            print(f"[EMAIL_APPROVAL] Live approval email successfully sent to {self.config.approver_email}")
            return True
        except Exception as e:
            print(f"[EMAIL_APPROVAL] Failed sending approval email to {self.config.approver_email}: {e}")
            return False

    def _extract_reply_body(self, content: str) -> str:
        """Extracts only newly typed user response, stripping quoted email templates."""
        reply_lines = []
        for line in content.splitlines():
            line_s = line.strip()
            if line_s.startswith(">"):
                continue
            if re.match(r"^-+\s*(Original Message|Pesan Asli)\s*-+", line_s, re.I):
                break
            if re.match(r"^(On|Pada)\s+.+(wrote|menulis):", line_s, re.I):
                break
            if "Please reply to this email with 'APPROVE' or 'REJECT'" in line_s:
                continue
            if "An invoice has passed PO validation and requires your approval" in line_s:
                continue
            if line_s:
                reply_lines.append(line_s)
        return " ".join(reply_lines).strip().upper()

    def _poll_imap_reply(self, correlation_id: str, timeout_sec: int = 60) -> Optional[ApprovalDecision]:
        if not (self.config.imap_user and self.config.imap_password):
            return None

        sent_msg_id = f"<APPROVAL-REQ-{correlation_id}@{self.config.smtp_server}>"
        print(f"[EMAIL_APPROVAL] Menunggu balasan email dari {self.config.approver_email} (maksimal {timeout_sec}s)...")
        print(f"[EMAIL_APPROVAL] Silakan buka email dan balas dengan 'APPROVE' atau 'REJECT'.")

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            remaining = int(deadline - time.time())
            print(f"[EMAIL_APPROVAL] Menunggu balasan email... (sisa {remaining}s) ", end="\r", flush=True)
            try:
                with imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port) as mail:
                    mail.login(self.config.imap_user, self.config.imap_password)
                    mail.select("INBOX")
                    status, messages = mail.search(None, f'(SUBJECT "{correlation_id}")')
                    if status == "OK" and messages[0]:
                        msg_ids = messages[0].split()
                        for m_id in reversed(msg_ids):
                            _, msg_data = mail.fetch(m_id, "(RFC822)")
                            parsed_msg = email.message_from_bytes(msg_data[0][1])

                            # Skip the outgoing request email itself
                            msg_id_header = (parsed_msg.get("Message-ID") or "").strip()
                            if msg_id_header == sent_msg_id:
                                continue

                            # Check decoded subject
                            subject = parsed_msg.get("Subject", "")
                            decoded_parts = decode_header(subject)
                            sub_text = "".join(b.decode(enc or "utf-8", errors="ignore") if isinstance(b, bytes) else str(b) for b, enc in decoded_parts)

                            has_reply_prefix = any(sub_text.lower().startswith(p) for p in ("re:", "fwd:", "balasan:")) or "re:" in sub_text.lower()
                            has_reply_header = bool(parsed_msg.get("In-Reply-To") or parsed_msg.get("References"))

                            if not (has_reply_prefix or has_reply_header):
                                continue

                            content = ""
                            if parsed_msg.is_multipart():
                                for part in parsed_msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        content += part.get_payload(decode=True).decode(errors="ignore")
                            else:
                                content = parsed_msg.get_payload(decode=True).decode(errors="ignore")

                            reply_text = self._extract_reply_body(content)

                            if re.search(r"\bAPPROVE\b", reply_text):
                                print(f"\n[EMAIL_APPROVAL] Balasan email 'APPROVE' terdeteksi dari {self.config.approver_email}!")
                                return ApprovalDecision(needs_approval=True, status="APPROVED", approved=True, message="Approved via email reply")
                            elif re.search(r"\bREJECT\b", reply_text):
                                print(f"\n[EMAIL_APPROVAL] Balasan email 'REJECT' terdeteksi dari {self.config.approver_email}!")
                                return ApprovalDecision(needs_approval=True, status="REJECTED", approved=False, message="Rejected via email reply")
            except Exception:
                pass

            time.sleep(3)

        print(f"\n[EMAIL_APPROVAL] Waktu tunggu ({timeout_sec}s) habis tanpa balasan email.")
        return None
