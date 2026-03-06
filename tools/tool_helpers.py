import json
from typing import Any, Dict, Optional
import requests


# --------------------------
# Common helpers
# --------------------------
def _ok(result: Any, **meta) -> str:
    payload = {"ok": True, "result": result}
    if meta:
        payload["meta"] = meta
    return json.dumps(payload, ensure_ascii=False, default=str)


def _fail(error: str, **meta) -> str:
    payload = {"ok": False, "error": error}
    if meta:
        payload["meta"] = meta
    return json.dumps(payload, ensure_ascii=False, default=str)


def _get(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = 10) -> Dict[str, Any]:
    r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
    # Your Node /api/stats always returns 200 even on errors,
    # but other endpoints return 4xx; handle both.
    try:
        data = r.json()
    except Exception:
        data = {"raw_text": r.text}
    return {"status": r.status_code, "json": data}
