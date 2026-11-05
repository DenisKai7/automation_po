import base64
from pathlib import Path
from typing import Optional
import httpx


class OCREngine:
    VISION_URL = "https://vision.googleapis.com/v1/images:annotate"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def extract_text(self, image_path: Path | str) -> str:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        with open(path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "requests": [
                {
                    "image": {"content": content_b64},
                    "features": [{"type": "TEXT_DETECTION"}]
                }
            ]
        }

        url = f"{self.VISION_URL}?key={self.api_key}"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        responses = data.get("responses", [])
        if not responses:
            return ""

        error = responses[0].get("error")
        if error:
            raise RuntimeError(f"Vision API Error: {error.get('message')}")

        annotations = responses[0].get("textAnnotations", [])
        if annotations:
            return annotations[0].get("description", "")

        return ""
