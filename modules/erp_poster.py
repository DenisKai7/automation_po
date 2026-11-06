from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import os
import shutil
import socket
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

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

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

        # Launch browser with isolated dynamic port and profile
        port = self._find_free_port()
        user_data = self.config.data_dir / f"browser_profile_{port}_{int(time.time()*1000)}"
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
            # Connect to CDP page with retry
            tabs_url = f"http://127.0.0.1:{port}/json"
            tabs = None
            for _ in range(10):
                try:
                    res = httpx.get(tabs_url, timeout=3)
                    if res.status_code == 200:
                        tabs = res.json()
                        if tabs:
                            break
                except Exception:
                    pass
                time.sleep(0.5)

            if not tabs:
                raise RuntimeError(f"No active browser tabs found via CDP on port {port}.")

            # Find page tab
            target_tab = next((t for t in tabs if t.get("type") == "page"), tabs[0])
            ws_url = target_tab["webSocketDebuggerUrl"]
            ws = websocket.create_connection(ws_url, timeout=15)

            # 1. Navigate to form
            ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": target_url}}))
            ws.recv()
            time.sleep(3.5)  # Wait for page elements to render

            approver_email = self.config.approver_email or "aldidadenis@gmail.com"
            inv_num = str(invoice_data.get('invoice_number', ''))
            vendor = str(invoice_data.get('vendor_name', ''))
            po_num = str(invoice_data.get('po_number', ''))
            amt = str(int(invoice_data.get('amount', 0)) if float(invoice_data.get('amount', 0)).is_integer() else invoice_data.get('amount', 0))
            curr = str(invoice_data.get('currency', 'IDR'))

            # Check if this is the built-in mock ERP form
            check_mock_js = "!!document.getElementById('erpForm')"
            ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": check_mock_js, "returnByValue": True}}))
            is_mock = json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", False)

            if is_mock:
                mock_fill = f"""
                (() => {{
                    document.getElementById('invoice_number').value = "{inv_num}";
                    document.getElementById('vendor_name').value = "{vendor}";
                    document.getElementById('po_number').value = "{po_num}";
                    document.getElementById('amount').value = "{amt}";
                    document.getElementById('currency').value = "{curr}";
                    document.getElementById('posting_ref').value = "{posting_ref}";
                    document.getElementById('submitBtn').click();
                    return true;
                }})()
                """
                ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {"expression": mock_fill, "returnByValue": True}}))
                ws.recv()
                time.sleep(1.0)
            else:
                # Live Google Forms / MS Forms via native CDP input simulation
                # Step 2a: Fill email if present
                ws.send(json.dumps({
                    "id": 10,
                    "method": "Runtime.evaluate",
                    "params": {"expression": """
                        (() => {
                            const el = document.querySelector('input[type="email"]') || document.querySelector('input[autocomplete="email"]');
                            if (el) { el.focus(); el.click(); return true; }
                            return false;
                        })()
                    """, "returnByValue": True}
                }))
                has_email = json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", False)
                if has_email:
                    ws.send(json.dumps({"id": 11, "method": "Input.insertText", "params": {"text": approver_email}}))
                    ws.recv()
                    time.sleep(0.3)

                # Step 2b: Fill invoice data fields
                fields = [
                    ("posting", posting_ref),
                    ("invoice", inv_num),
                    ("vendor", vendor),
                    ("po", po_num),
                    ("amount", amt),
                    ("currency", curr)
                ]
                for key, val in fields:
                    focus_js = f"""
                    (() => {{
                        const items = Array.from(document.querySelectorAll('div[role="listitem"]'));
                        for (const it of items) {{
                            const h = (it.querySelector('[role="heading"]')?.innerText || it.innerText || '').toLowerCase();
                            const inp = it.querySelector('input:not([type="email"]):not([type="hidden"]), textarea');
                            if (!inp) continue;

                            let match = false;
                            if ('{key}' === 'posting' && (h.includes('posting') || h.includes('ref'))) match = true;
                            else if ('{key}' === 'invoice' && (h.includes('invoice') || h.includes('faktur'))) match = true;
                            else if ('{key}' === 'vendor' && (h.includes('vendor') || h.includes('pemasok'))) match = true;
                            else if ('{key}' === 'po' && !h.includes('posting') && (h.includes('po') || h.includes('purchase'))) match = true;
                            else if ('{key}' === 'amount' && (h.includes('amount') || h.includes('nominal') || h.includes('total'))) match = true;
                            else if ('{key}' === 'currency' && (h.includes('currency') || h.includes('mata uang') || h.includes('uang'))) match = true;

                            if (match) {{
                                inp.focus();
                                inp.click();
                                return true;
                            }}
                        }}
                        return false;
                    }})()
                    """
                    ws.send(json.dumps({"id": 20, "method": "Runtime.evaluate", "params": {"expression": focus_js, "returnByValue": True}}))
                    focused = json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", False)
                    if focused:
                        ws.send(json.dumps({"id": 21, "method": "Input.insertText", "params": {"text": str(val)}}))
                        ws.recv()
                        time.sleep(0.3)

                # Step 2c: Click Submit Button
                submit_js = """
                (() => {
                    const buttons = Array.from(document.querySelectorAll('div[role="button"], button, input[type="submit"]'));
                    const btn = buttons.find(b => {
                        const txt = (b.innerText || b.textContent || b.value || '').trim().toLowerCase();
                        return txt === 'kirim' || txt === 'submit' || txt === 'send';
                    });
                    if (btn) { btn.click(); return true; }
                    return false;
                })()
                """
                ws.send(json.dumps({"id": 30, "method": "Runtime.evaluate", "params": {"expression": submit_js, "returnByValue": True}}))
                ws.recv()
                time.sleep(4.0)

            # 4. Verify submission success
            verify_script = """
            (() => {
                const url = window.location.href.toLowerCase();
                const bodyText = (document.body.innerText || document.body.textContent || '').toLowerCase();
                return url.includes('formresponse') ||
                       bodyText.includes('response has been recorded') ||
                       bodyText.includes('telah direkam') ||
                       bodyText.includes('submission confirmed') ||
                       bodyText.includes('terima kasih') ||
                       bodyText.includes('berhasil');
            })()
            """
            ws.send(json.dumps({
                "id": 40,
                "method": "Runtime.evaluate",
                "params": {"expression": verify_script, "returnByValue": True}
            }))
            verify_res = json.loads(ws.recv())
            success = verify_res.get("result", {}).get("result", {}).get("value", False)

            return PostingResult(
                posting_ref=posting_ref,
                success=success,
                submitted_at=submitted_at,
                message=f"Form submitted successfully at {target_url}" if success else f"Form submission unconfirmed at {target_url}"
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
            # Kill process tree cleanly to prevent zombie Chromium child processes
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
            time.sleep(0.5)
            shutil.rmtree(user_data, ignore_errors=True)
