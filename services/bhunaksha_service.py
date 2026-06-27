"""
services/bhunaksha_service.py

Browser-free fetch using requests (no Playwright/Chromium). Runs on any host.
Returns parsed JSON dict, or {"error": ..., "body": ...} on failure.
"""

import json
import requests

BASE = "https://mahabhunakasha.mahabhumi.gov.in"


def get_plot_info(giscode, plotno, save_debug=False, timeout=30):
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": f"{BASE}/27/index.html",
        "X-Requested-With": "XMLHttpRequest",
    })

    try:
        s.get(f"{BASE}/27/index.html", timeout=timeout)
        s.post(
            f"{BASE}/rest/MapInfo/getVVVVExtentGeoref",
            data={"state": "27", "giscode": giscode, "srs": "4326"},
            timeout=timeout,
        )
        r = s.post(
            f"{BASE}/rest/MapInfo/getPlotInfo",
            data={"state": "27", "giscode": giscode, "plotno": str(plotno), "srs": "4326"},
            timeout=timeout,
        )
        text = r.text
    except requests.RequestException as e:
        return {"error": f"Network error contacting Bhunaksha: {e}", "body": ""}

    try:
        data = json.loads(text)
        if save_debug:
            with open("response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        return data
    except Exception:
        if save_debug:
            with open("response.txt", "w", encoding="utf-8") as f:
                f.write(text)
        return {
            "error": "Response was not valid JSON (the requests-only method may be "
                     "blocked; if so, use the Playwright version on a VPS/Docker host).",
            "body": text[:2000],
        }
