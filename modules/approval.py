from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import imaplib
import smtplib
import time
from config.settings import AppConfig


@dataclass
class ApprovalDecision:
    needs_approval: bool
    status: str  # APPROVED, REJECTED, NOT_REQUIRED, PENDING, TIMEOUT
    approved: bool
    message: str


class ApprovalService:
    def __init__(self, config: AppConfig, auto_approve: bool = False):
        self.config = config
        self.auto_approve = auto_approve

    def evaluate(self, correlation_id: str, invoice_number: str, vendor_name: str,
                 amount: float, currency: str) -> ApprovalDecision:
        threshold = self.config.threshold_amount
        if amount <= threshold:
            return ApprovalDecision(
                needs_approval=False,
                status="NOT_REQUIRED",
                approved=True,
                message=f"Amount {amount:,.0f} {currency} <= Threshold {threshold:,.0f} {currency}"
            )

        # Requires Approval
        # Try sending real email if SMTP is configured
        if self.config.smtp_user and self.config.smtp_password:
            sent = self._send_approval_email(correlation_id, invoice_number, vendor_name, amount, currency)
            if sent:
                decision = self._poll_imap_reply(correlation_id)
                if decision:
                    return decision

        # Fallback to auto-approve flag if enabled
        if self.auto_approve:
            return ApprovalDecision(
                needs_approval=True,
                status="APPROVED",
                approved=True,
                message=f"Auto-approved: {amount:,.0f} {currency} > Threshold {threshold:,.0f} {currency}"
            )

        # Interactive terminal fallback
        print("\n" + "=" * 60)
        print(f"[APPROVAL REQUIRED] Invoice: {invoice_number} | Correlation: {correlation_id}")
        print(f"Vendor: {vendor_name} | Amount: {amount:,.0f} {currency} | Threshold: {threshold:,.0f} {currency}")
        print("=" * 60)
        try:
            choice = input("Approve invoice? (Y/n): ").strip().lower()
            if choice in ("y", "yes", ""):
                return ApprovalDecision(
                    needs_approval=True,
                    status="APPROVED",
                    approved=True,
                    message="Approved manually via interactive prompt"
                )
            else:
                return ApprovalDecision(
                    needs_approval=True,
                    status="REJECTED",
                    approved=False,
                    message="Rejected manually via interactive prompt"
                )
        except (EOFError, KeyboardInterrupt):
            return ApprovalDecision(
                needs_approval=True,
                status="REJECTED",
                approved=False,
                message="Non-interactive session: rejected by default"
            )

    def _send_approval_email(self, correlation_id: str, invoice_number: str,
                             vendor_name: str, amount: float, currency: str) -> bool:
        try:
            msg = MIMEMultipart()
            msg["From"] = self.config.smtp_user
            msg["To"] = self.config.approver_email
            msg["Subject"] = f"[APPROVAL REQUIRED] Invoice {invoice_number} (Ref: {correlation_id})"

            body = (
                f"Hello Approver,\n\n"
                f"An invoice requires your approval as it exceeds the threshold of {self.config.threshold_amount:,.0f} {currency}:\n\n"
                f"Invoice Number: {invoice_number}\n"
                f"Vendor Name: {vendor_name}\n"
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
            return True
        except Exception:
            return False

    def _poll_imap_reply(self, correlation_id: str, timeout_sec: int = 15) -> Optional[ApprovalDecision]:
        if not (self.config.imap_user and self.config.imap_password):
            return None

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                with imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port) as mail:
                    mail.login(self.config.imap_user, self.config.imap_password)
                    mail.select("INBOX")
                    status, messages = mail.search(None, f'(SUBJECT "{correlation_id}")')
                    if status == "OK" and messages[0]:
                        msg_ids = messages[0].split()
                        latest_id = msg_ids[-1]
                        _, msg_data = mail.fetch(latest_id, "(RFC822)")
                        import email
                        msg = email.message_from_bytes(msg_data[0][1])
                        content = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    content += part.get_payload(decode=True).decode(errors="ignore")
                        else:
                            content = msg.get_payload(decode=True).decode(errors="ignore")

                        upper_c = content.upper()
                        if "APPROVE" in upper_c:
                            return ApprovalDecision(needs_approval=True, status="APPROVED", approved=True, message="Approved via email reply")
                        elif "REJECT" in upper_c:
                            return ApprovalDecision(needs_approval=True, status="REJECTED", approved=False, message="Rejected via email reply")
            except Exception:
                pass
            time.sleep(3)

        return None
