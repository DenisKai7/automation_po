import logging
import sys
from typing import Optional
from core.database import Database


class AutomationLogger:
    def __init__(self, db: Optional[Database] = None):
        self.db = db
        self._logger = logging.getLogger("it_automation")
        self._logger.setLevel(logging.INFO)

        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    def log(self, correlation_id: str, step: str, result: str, message: str) -> None:
        level = logging.INFO
        res_upper = result.upper()
        if res_upper in ("FAILED", "ERROR"):
            level = logging.ERROR
        elif res_upper in ("WARNING", "MISMATCH", "REJECTED"):
            level = logging.WARNING

        self._logger.log(level, f"[{correlation_id}] [{step}] [{result}] {message}")

        if self.db:
            try:
                self.db.add_process_log(correlation_id, step, result, message)
            except Exception as e:
                self._logger.error(f"Failed to write log to DB: {e}")
