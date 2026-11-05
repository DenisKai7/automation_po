# Technical Test: Junior Automation Developer (Python)

**Use case:** invoice email → OCR (Google Vision) → regex extraction → database → PO validation → approval by
email → ERP posting through a web form (browser) → Excel export

## Duration and constraints

- 2–3 days
- Python.
- OCR with Google Cloud Vision; we send you an API key. Extract the data from the OCR text with regex, not with an LLM.
- Use a database. The Excel files are exports from it.
- The ERP is simulated by a Microsoft Form or Google Form that you create yourself.
- Use your own mailbox, not your work email.
- Build it the way you would build an automation for production, with good development practices. The project structure, design, libraries, and error handling are your choice.

## Goal

Build an end-to-end automation: invoice email → OCR → regex extraction → database → PO validation → approval by
email when needed → posting to the ERP form through the browser → Excel export → process log.

## Flow

1. **Email intake:** read new emails that have an invoice image attached, and save the attachment. Ideally the automation picks up new emails by itself; sending the email and then running the script by hand is acceptable.
2. **OCR and extraction:** Google Vision, then regex for InvoiceNumber, VendorName, PO_Number, Amount, and Currency.
3. **Database:** save the invoice and its data.
4. **PO validation:** check the invoice against `PurchaseOrders.csv`.
5. **Approval:** when the amount is above ThresholdAmount (`Config.xlsx`), email the ApproverEmail; the approver approves or rejects by replying.
6. **ERP posting:** submit the invoice with a PostingRef to your form (FormsUrl) through the browser. The browser is visible; a setting to switch headless on or off is a plus.
7. **Export and archive:** export `Invoices.xlsx`, `ERP_Dummy.xlsx`, and `ProcessLogs.xlsx` following the templates, and move each image to `/Processed` according to its result.

## Provided files

| File                                                                                | Content                                                |
|-------------------------------------------------------------------------------------|--------------------------------------------------------|
| `Config.xlsx`                                                                       | ThresholdAmount, FormsUrl, ExcelERPPath, ApproverEmail |
| `PurchaseOrders.csv`                                                                | Purchase orders                                        |
| `templates/Invoices.xlsx`, `templates/ERP_Dummy.xlsx`, `templates/ProcessLogs.xlsx` | Export templates                                       |
| `samples/`                                                                          | Sample invoice images                                  |
| Google Vision API key                                                               | Sent separately                                        |

## Acceptance criteria

1. The process runs end to end.
2. Data is stored in a database, and the Excel files are exported from it.
3. The PostingRef is the same in the form responses, `ERP_Dummy.xlsx`, and `Invoices.xlsx`.
4. The threshold is read from `Config.xlsx` (dynamic).
5. `ProcessLogs.xlsx` records steps and errors, and every image ends up in `/Processed` according to its result.

## Submission

- A link to a Git repository (private is fine if you invite our reviewer).
- `README.md`: how to set it up and run it.
- A link to your form, with access to its responses for our reviewer.
- A short screen recording of one full run.

## Notes

- We run your automation on our laptop (Windows), with our own mailbox (IMAP/SMTP), our API key, and invoices you have not seen.
- AI tools are allowed. In the interview you explain your code and change it.