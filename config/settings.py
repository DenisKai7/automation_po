from dataclasses import dataclass, field
from pathlib import Path
import os
import openpyxl
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")


@dataclass
class AppConfig:
    # From Config.xlsx
    threshold_amount: float = 1000000.0
    forms_url: str = ""
    excel_erp_path: str = "/ERP_Dummy.xlsx"
    approver_email: str = "aldidadenis@gmail.com"

    # From .env / Secrets
    vision_api_key: str = os.getenv("VISION_API_KEY", "AIzaSyD9bQ80NIXZyQYz_PclqLKYTlUUusrV6iA")
    imap_server: str = os.getenv("IMAP_SERVER", "imap.gmail.com")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_user: str = os.getenv("IMAP_USER", "")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")

    smtp_server: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")

    headless: bool = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
    browser_type: str = os.getenv("BROWSER_TYPE", "edge")

    # Project Paths
    base_dir: Path = BASE_DIR
    templates_dir: Path = BASE_DIR / "templates"
    processed_dir: Path = BASE_DIR / "Processed"
    data_dir: Path = BASE_DIR / "data"
    inbox_dir: Path = BASE_DIR / "inbox"
    purchase_orders_csv: Path = BASE_DIR / "PurchaseOrders.csv"
    db_path: Path = BASE_DIR / "data" / "automation.db"

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "AppConfig":
        cfg = cls()
        config_file = Path(config_path) if config_path else BASE_DIR / "Config.xlsx"

        if config_file.exists():
            wb = openpyxl.load_workbook(config_file, data_only=True)
            ws = wb["Config_T"] if "Config_T" in wb.sheetnames else wb.active
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or not row[0]:
                    continue
                k = str(row[0]).strip()
                v = row[1] if len(row) > 1 else ""

                if k == "ThresholdAmount" and v is not None:
                    try:
                        cfg.threshold_amount = float(v)
                    except ValueError:
                        pass
                elif k == "FormsUrl" and v:
                    cfg.forms_url = str(v).strip()
                elif k == "ExcelERPPath" and v:
                    cfg.excel_erp_path = str(v).strip()
                elif k == "ApproverEmail" and v:
                    cfg.approver_email = str(v).strip()

        # .env override for forms_url if provided
        env_form_url = os.getenv("FORMS_URL", "").strip()
        if env_form_url:
            cfg.forms_url = env_form_url

        env_approver = os.getenv("APPROVER_EMAIL", "").strip()
        if env_approver:
            cfg.approver_email = env_approver

        # Ensure essential directories exist
        cfg.processed_dir.mkdir(parents=True, exist_ok=True)
        (cfg.processed_dir / "Success").mkdir(parents=True, exist_ok=True)
        (cfg.processed_dir / "Failed").mkdir(parents=True, exist_ok=True)
        (cfg.processed_dir / "Rejected").mkdir(parents=True, exist_ok=True)
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        cfg.inbox_dir.mkdir(parents=True, exist_ok=True)

        return cfg
