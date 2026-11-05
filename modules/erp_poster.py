from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import os
import shutil
import subprocess
import time
from typing import Optional
import httpx
import websocket
from config.settings import AppConfig


@dataclass
class PostingResult:
    posting_ref: str
    success: bool
    submitted_at: str
    message: str


class ERPBrowserPoster:
    def __init__(self, config: AppConfig):
        self.config = config
        self.browser_path = self._find_browser()

    def _find_browser(self) -> str:
        # Check Edge first (standard on Windows), then Chrome
        edge_candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            shutil.which("msedge")
        ]
        for c in edge_candidates:
            if c and Path(c).exists():
                return str(c)

        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            shutil.which("chrome")
        ]
        for c in chrome_candidates:
            if c and Path(c).exists():
                return str(c)

        raise RuntimeError("No compatible Chromium browser (Edge or Chrome) found on system.")

    def generate_posting_ref(self, correlation_id: str) -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        suffix = correlation_id.replace("-", "")[-6:] if correlation_id else "000000"
        return f"ERP-{ts}-{suffix}"

    def post_invoice(self, invoice_data: dict, posting_ref: str) -> PostingResult:
        target_url = self.config.forms_url.strip()
        # If no custom URL provided or placeholder URL, fallback to built-in mock ERP form
        if not target_url or "your-form-url" in target_url:
            mock_html = self.config.templates_dir / "mock_erp_form.html"
            target_url = mock_html.resolve().as_uri()

        submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Launch browser with remote debugging port
        port = 9222
        user_data = self.config.data_dir / f"browser_profile_{int(time.time())}"
        user_data.mkdir(parents=True, exist_ok=True)

        args = [
            self.browser_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data}",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        if self.config.headless:
            args.append("--headless=new")

        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.0)

        ws = None
        try:
            # Connect to CDP page
            tabs_url = f"http://127.0.0.1:{port}/json"
            tabs = httpx.get(tabs_url, timeout=5).json()
            if not tabs:
                raise RuntimeError("No active browser tabs found via CDP.")

            ws_url = tabs[0]["webSocketDebuggerUrl"]
            ws = websocket.create_connection(ws_url, timeout=10)

            # 1. Navigate to form
            ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": target_url}}))
            ws.recv()
            time.sleep(2.5)  # Wait for page elements to render

            # 2. Inject form data using universal script for MS Forms, Google Forms & Mock Form
            js_script = f"""
            (function() {{
                const data = {{
                    invoiceNumber: "{invoice_data.get('invoice_number', '')}",
                    vendorName: "{invoice_data.get('vendor_name', '')}",
                    poNumber: "{invoice_data.get('po_number', '')}",
                    amount: "{invoice_data.get('amount', '')}",
                    currency: "{invoice_data.get('currency', 'IDR')}",
                    postingRef: "{posting_ref}"
                }};

                const values = [
                    data.invoiceNumber,
                    data.vendorName,
                    data.poNumber,
                    data.amount,
                    data.currency,
                    data.postingRef
                ];

                // Check Mock Form or standard ID inputs
                const idMap = {{
                    'invoice_number': data.invoiceNumber,
                    'vendor_name': data.vendorName,
                    'po_number': data.poNumber,
                    'amount': data.amount,
                    'currency': data.currency,
                    'posting_ref': data.postingRef
                }};

                let filledCount = 0;
                for (const [id, val] of Object.entries(idMap)) {{
                    const el = document.getElementById(id);
                    if (el) {{
                        el.value = val;
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        filledCount++;
                    }}
                }}

                if (filledCount < 6) {{
                    // Fallback to sequential input query (MS Forms / Google Forms)
                    const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type]), textarea'));
                    const targetInputs = inputs.filter(el => el.offsetParent !== null || el.offsetWidth > 0);
                    targetInputs.slice(0, 6).forEach((input, idx) => {{
                        input.value = values[idx] || '';
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }});
                }}

                // Click submit button
                setTimeout(() => {{
                    const submitBtn = document.querySelector('button[type="submit"]') ||
                                      document.querySelector('button[data-automation-id="submitButton"]') ||
                                      document.querySelector('div[role="button"][jsname]') ||
                                      document.querySelector('button');
                    if (submitBtn) {{
                        submitBtn.click();
                    }}
                }}, 600);

                return true;
            }})();
            """

            ws.send(json.dumps({
                "id": 2,
                "method": "Runtime.evaluate",
                "params": {"expression": js_script}
            }))
            ws.recv()

            time.sleep(2.0)  # Allow form submission to complete

            return PostingResult(
                posting_ref=posting_ref,
                success=True,
                submitted_at=submitted_at,
                message=f"Form submitted successfully at {target_url}"
            )

        except Exception as e:
            return PostingResult(
                posting_ref=posting_ref,
                success=False,
                submitted_at=submitted_at,
                message=f"Browser posting failed: {str(e)}"
            )

        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
            time.sleep(0.5)
            shutil.rmtree(user_data, ignore_errors=True)
