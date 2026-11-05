from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class ExtractedInvoice:
    invoice_number: Optional[str]
    vendor_name: Optional[str]
    po_number: Optional[str]
    amount: Optional[float]
    currency: str
    is_valid: bool
    error_message: Optional[str] = None
    raw_text: str = ""


class InvoiceExtractor:
    # Explicit regex patterns per technical requirements
    RE_INVOICE = re.compile(r"\b(INV-\d{4}-\d{3,4})\b", re.IGNORECASE)
    RE_PO = re.compile(r"\b(PO-\d{3,4})\b", re.IGNORECASE)
    RE_PO_INCOMPLETE = re.compile(r"(?:PO|PG)\s*Number[:\s]+PO-(?!\d)", re.IGNORECASE)
    RE_AMOUNT_CURRENCY = re.compile(r"\b(\d{4,12})\s*(IDR|DR|USD|EUR)\b", re.IGNORECASE)
    RE_VENDOR_LABEL = re.compile(r"(?:Vendor\s*Name\s*:\s*)([^\r\n]+)", re.IGNORECASE)
    RE_VENDOR_LINE = re.compile(r"^(?:PT|CV|UD)\b[A-Za-z0-9\s.,-]+$", re.IGNORECASE)
    RE_CORRUPT_INDICATORS = re.compile(r"\b(INVALID|ERROR|Err)\b|[%$*#@!]{3,}", re.IGNORECASE)

    @classmethod
    def extract(cls, raw_text: str) -> ExtractedInvoice:
        text = raw_text.strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # 1. Check for corrupted/invalid invoice flags
        if cls.RE_CORRUPT_INDICATORS.search(text):
            return ExtractedInvoice(
                invoice_number=None,
                vendor_name=None,
                po_number=None,
                amount=None,
                currency="IDR",
                is_valid=False,
                error_message="Corrupted or invalid invoice data detected",
                raw_text=text
            )

        # 2. Extract Invoice Number
        inv_match = cls.RE_INVOICE.search(text)
        invoice_number = inv_match.group(1).upper() if inv_match else None

        # 3. Extract PO Number
        po_number = None
        if cls.RE_PO_INCOMPLETE.search(text):
            po_number = None
        else:
            po_match = cls.RE_PO.search(text)
            if po_match:
                po_number = po_match.group(1).upper()

        # 4. Extract Amount & Currency
        amount = None
        currency = "IDR"
        amt_match = cls.RE_AMOUNT_CURRENCY.search(text)
        if amt_match:
            try:
                amount = float(amt_match.group(1))
                curr_token = amt_match.group(2).upper()
                currency = "IDR" if curr_token in ("IDR", "DR") else curr_token
            except ValueError:
                amount = None
        else:
            # Fallback for amount next to 'Amount:' label
            amt_label_match = re.search(r"Amount[:\s]*([0-9.,]+)", text, re.IGNORECASE)
            if amt_label_match:
                num_str = amt_label_match.group(1).replace(",", "").replace(".", "")
                if num_str.isdigit():
                    amount = float(num_str)

        # 5. Extract Vendor Name
        vendor_name = None
        vendor_label_match = cls.RE_VENDOR_LABEL.search(text)
        if vendor_label_match:
            cand = vendor_label_match.group(1).strip()
            if cand:
                vendor_name = cand

        if not vendor_name:
            # Search standalone line with PT / CV / UD prefix
            for line in lines:
                if cls.RE_VENDOR_LINE.match(line) and not re.search(r"INVOICE|Amount|PO\s*Number", line, re.I):
                    vendor_name = line.strip()
                    break

        # 6. Validation of extracted attributes
        missing = []
        if not invoice_number:
            missing.append("InvoiceNumber")
        if not vendor_name:
            missing.append("VendorName")
        if not po_number:
            missing.append("PO_Number")
        if amount is None or amount <= 0:
            missing.append("Amount")

        if missing:
            return ExtractedInvoice(
                invoice_number=invoice_number,
                vendor_name=vendor_name,
                po_number=po_number,
                amount=amount,
                currency=currency,
                is_valid=False,
                error_message=f"Missing or incomplete fields: {', '.join(missing)}",
                raw_text=text
            )

        return ExtractedInvoice(
            invoice_number=invoice_number,
            vendor_name=vendor_name,
            po_number=po_number,
            amount=amount,
            currency=currency,
            is_valid=True,
            error_message=None,
            raw_text=text
        )
