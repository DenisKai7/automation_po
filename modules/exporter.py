from pathlib import Path
from config.settings import AppConfig
from core.database import Database


class ExcelExporter:
    def __init__(self, db: Database, config: AppConfig):
        self.db = db
        self.config = config

    def export_all(self, output_dir: Path | None = None) -> dict:
        out_dir = Path(output_dir) if output_dir else self.config.base_dir
        templates_dir = self.config.templates_dir

        invoices_out = out_dir / "Invoices.xlsx"
        erp_out = out_dir / "ERP_Dummy.xlsx"
        logs_out = out_dir / "ProcessLogs.xlsx"

        # Check template files exist
        tmpl_invoices = templates_dir / "Invoices.xlsx"
        tmpl_erp = templates_dir / "ERP_Dummy.xlsx"
        tmpl_logs = templates_dir / "ProcessLogs.xlsx"

        res_inv = self.db.export_invoices(tmpl_invoices, invoices_out)
        res_erp = self.db.export_erp_dummy(tmpl_erp, erp_out)
        res_logs = self.db.export_process_logs(tmpl_logs, logs_out)

        return {
            "invoices": res_inv,
            "erp_dummy": res_erp,
            "process_logs": res_logs
        }
