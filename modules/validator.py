from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import csv


@dataclass
class ValidationResult:
    match_status: str  # MATCHED, MISMATCH, NOT_FOUND, INACTIVE_PO, INVALID
    is_valid: bool
    message: str
    expected_vendor: Optional[str] = None
    expected_amount: Optional[float] = None
    expected_currency: Optional[str] = None


class POValidator:
    def __init__(self, csv_path: Path | str):
        self.csv_path = Path(csv_path)
        self._po_cache: Dict[str, dict] = {}
        self.load_orders()

    def load_orders(self) -> None:
        if not self.csv_path.exists():
            return

        with open(self.csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                po_num = row.get("PO_Number", "").strip().upper()
                if po_num:
                    self._po_cache[po_num] = {
                        "VendorName": row.get("VendorName", "").strip(),
                        "TotalAmount": float(row.get("TotalAmount", 0)),
                        "Currency": row.get("Currency", "IDR").strip().upper(),
                        "IsActive": row.get("IsActive", "FALSE").strip().upper() == "TRUE"
                    }

    def validate(self, po_number: Optional[str], vendor_name: Optional[str], amount: Optional[float], currency: str) -> ValidationResult:
        if not po_number:
            return ValidationResult(
                match_status="INVALID",
                is_valid=False,
                message="PO Number is missing or invalid"
            )

        po_key = po_number.strip().upper()
        if po_key not in self._po_cache:
            return ValidationResult(
                match_status="NOT_FOUND",
                is_valid=False,
                message=f"PO {po_key} not found in PurchaseOrders.csv"
            )

        po = self._po_cache[po_key]

        if not po["IsActive"]:
            return ValidationResult(
                match_status="INACTIVE_PO",
                is_valid=False,
                message=f"PO {po_key} is marked inactive"
            )

        # Normalize and compare vendor
        norm_inv_vendor = "".join(filter(str.isalnum, (vendor_name or "").lower()))
        norm_po_vendor = "".join(filter(str.isalnum, po["VendorName"].lower()))
        if norm_inv_vendor != norm_po_vendor:
            return ValidationResult(
                match_status="MISMATCH",
                is_valid=False,
                message=f"Vendor mismatch. PO: {po['VendorName']}, Invoice: {vendor_name}",
                expected_vendor=po["VendorName"],
                expected_amount=po["TotalAmount"],
                expected_currency=po["Currency"]
            )

        # Compare Currency
        if currency.strip().upper() != po["Currency"]:
            return ValidationResult(
                match_status="MISMATCH",
                is_valid=False,
                message=f"Currency mismatch. PO: {po['Currency']}, Invoice: {currency}",
                expected_vendor=po["VendorName"],
                expected_amount=po["TotalAmount"],
                expected_currency=po["Currency"]
            )

        # Compare Amount
        if amount is None or abs(float(amount) - po["TotalAmount"]) > 0.01:
            return ValidationResult(
                match_status="MISMATCH",
                is_valid=False,
                message=f"Amount mismatch. PO: {po['TotalAmount']}, Invoice: {amount}",
                expected_vendor=po["VendorName"],
                expected_amount=po["TotalAmount"],
                expected_currency=po["Currency"]
            )

        return ValidationResult(
            match_status="MATCHED",
            is_valid=True,
            message="PO matched with PurchaseOrders.csv",
            expected_vendor=po["VendorName"],
            expected_amount=po["TotalAmount"],
            expected_currency=po["Currency"]
        )
