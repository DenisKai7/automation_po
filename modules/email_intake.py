from pathlib import Path
from typing import List, Optional
import email
from email.header import decode_header
import imaplib
import os
from config.settings import AppConfig


class EmailIntakeService:
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".pdf"}

    def __init__(self, config: AppConfig):
        self.config = config

    def fetch_from_imap(self, destination_dir: Path) -> List[Path]:
        saved_files: List[Path] = []
        if not (self.config.imap_user and self.config.imap_password):
            return saved_files

        destination_dir.mkdir(parents=True, exist_ok=True)
        try:
            with imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port) as mail:
                mail.login(self.config.imap_user, self.config.imap_password)
                mail.select("INBOX")

                status, data = mail.search(None, "UNSEEN")
                if status != "OK" or not data[0]:
                    return saved_files

                for msg_id in data[0].split():
                    _, msg_data = mail.fetch(msg_id, "(RFC822)")
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    for part in msg.walk():
                        if part.get_content_maintype() == "multipart":
                            continue
                        if part.get("Content-Disposition") is None:
                            continue

                        filename = part.get_filename()
                        if not filename:
                            continue

                        # Decode filename
                        decoded_parts = decode_header(filename)
                        filename_decoded = ""
                        for b, enc in decoded_parts:
                            if isinstance(b, bytes):
                                filename_decoded += b.decode(enc or "utf-8", errors="ignore")
                            else:
                                filename_decoded += str(b)

                        ext = Path(filename_decoded).suffix.lower()
                        if ext in self.IMAGE_EXTENSIONS:
                            target_path = destination_dir / filename_decoded
                            with open(target_path, "wb") as f:
                                f.write(part.get_payload(decode=True))
                            saved_files.append(target_path)

        except Exception as e:
            print(f"[IMAP] Intake error: {e}")

        return saved_files

    def load_local_folder(self, folder_path: Path | str) -> List[Path]:
        p = Path(folder_path)
        if not p.exists():
            return []
        files = []
        for f in sorted(p.iterdir()):
            if f.is_file() and f.suffix.lower() in self.IMAGE_EXTENSIONS:
                files.append(f)
        return files

    def get_invoices_to_process(self, source_arg: Optional[str] = None) -> List[Path]:
        # 1. Explicit folder source provided
        if source_arg and source_arg.lower() != "email":
            custom_path = Path(source_arg)
            if custom_path.is_dir():
                return self.load_local_folder(custom_path)
            elif custom_path.is_file():
                return [custom_path]

        # 2. Try fetching from IMAP if credentials provided
        if self.config.imap_user and self.config.imap_password:
            imap_files = self.fetch_from_imap(self.config.inbox_dir)
            if imap_files:
                return imap_files

        # 3. Check inbox directory
        inbox_files = self.load_local_folder(self.config.inbox_dir)
        if inbox_files:
            return inbox_files

        # 4. Fallback to Sample Invoice directory for out-of-the-box operation
        sample_dir = self.config.base_dir / "Sample Invoice"
        return self.load_local_folder(sample_dir)
