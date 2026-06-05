"""
core.py — pure / data logic for GhostGauge.

No rumps, no AppKit, no macOS-only imports.
Importable on Linux (CI) with only stdlib + httpx + keyring.
"""

import getpass
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import keyring

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"

HEADERS = {
    "anthropic-beta": "oauth-2025-04-20",
    "User-Agent": "claude-code/2.1.0",
    "Accept": "application/json",
}

BAR_WIDTH = 14


def get_access_token() -> str | None:
    """Read OAuth access token from Keychain or fallback file. Never returns token material to caller logs."""
    try:
        raw = keyring.get_password(KEYCHAIN_SERVICE, getpass.getuser())
    except Exception:
        raw = None
    if raw is None and CREDENTIALS_FILE.exists():
        try:
            raw = CREDENTIALS_FILE.read_text(encoding="utf-8")
        except OSError:
            return None
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        if "claudeAiOauth" in data:
            return data["claudeAiOauth"]["accessToken"]
        return data["accessToken"]
    except (json.JSONDecodeError, KeyError):
        return None


def bar(pct: float, width: int = 10) -> str:
    """Render a unicode block progress bar of given width (plain ASCII, used by --once mode)."""
    pct = max(0, min(100, pct))
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def extract_pct(window: dict) -> float | None:
    """Try multiple key names for utilization percentage. Value is already 0-100."""
    for key in ("utilization", "used_percentage", "used", "percentage"):
        if key in window:
            val = window[key]
            try:
                return round(float(val))
            except (TypeError, ValueError):
                continue
    return None


def extract_reset(window: dict) -> str | None:
    """Try multiple key names for reset time, return raw string or None."""
    for key in ("resets_at", "reset_at", "resetsAt"):
        if key in window:
            return window[key]
    return None


def format_reset_relative(raw: str | None) -> str:
    """Format reset time as relative delta for current-session (five_hour) window."""
    if raw is None:
        return "unknown"
    try:
        ts = raw
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt_utc = datetime.fromisoformat(ts)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta_secs = (dt_utc - now).total_seconds()
        if delta_secs <= 0:
            return "resets soon"
        delta_min = int(delta_secs // 60)
        if delta_min < 1:
            return "resets in <1 min"
        if delta_min < 60:
            return f"resets in {delta_min} min"
        h = delta_min // 60
        m = delta_min % 60
        return f"resets in {h}h {m}m"
    except Exception:
        return "unknown"


def format_reset_absolute(raw: str | None) -> str:
    """Format reset time as absolute local weekday+time for weekly windows."""
    if raw is None:
        return "unknown"
    try:
        ts = raw
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt_utc = datetime.fromisoformat(ts)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone()
        # %-I strips leading zero on hour (Linux/macOS)
        return "resets " + dt_local.strftime("%a %-I:%M %p")
    except Exception:
        return "unknown"


def find_plan_name(data: dict) -> str | None:
    """
    Best-effort: scan top-level response for a plan/tier/subscription field.
    Returns the value as a string if found, None otherwise.
    Never returns token material — only plan-shaped strings.
    """
    plan_keys = [k for k in data if any(word in k.lower() for word in ("plan", "tier", "subscription"))]
    for k in plan_keys:
        val = data[k]
        if isinstance(val, str) and val:
            return val
    return None


def fetch_usage(token: str) -> dict:
    """
    Returns dict with keys: ok, session_pct, session_reset_raw, week_pct, week_reset_raw,
    sonnet_pct, sonnet_reset_raw, plan_name, top_level_keys,
    error, status_code.
    sonnet_* keys are None when window is absent/null.
    Never includes token material.
    """
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(USAGE_URL, headers=headers, timeout=30)
    except httpx.RequestError as exc:
        return {"ok": False, "error": str(exc), "status_code": None}

    if resp.status_code == 401:
        return {"ok": False, "error": "unauthorized", "status_code": 401}
    if resp.status_code == 429:
        return {"ok": False, "error": "rate_limited", "status_code": 429}
    if resp.status_code != 200:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "status_code": resp.status_code}

    try:
        data = resp.json()
    except Exception:
        return {"ok": False, "error": "invalid response", "status_code": resp.status_code}

    # Capture top-level keys (names only, no values — security rule)
    top_level_keys = sorted(data.keys()) if isinstance(data, dict) else []

    five_hour = data.get("five_hour") or {}
    seven_day = data.get("seven_day") or {}
    seven_day_sonnet = data.get("seven_day_sonnet") or {}

    session_pct = extract_pct(five_hour)
    session_reset_raw = extract_reset(five_hour)
    week_pct = extract_pct(seven_day)
    week_reset_raw = extract_reset(seven_day)

    sonnet_pct = extract_pct(seven_day_sonnet) if seven_day_sonnet else None
    sonnet_reset_raw = extract_reset(seven_day_sonnet) if seven_day_sonnet else None

    plan_name = find_plan_name(data)

    return {
        "ok": True,
        "session_pct": session_pct,
        "session_reset_raw": session_reset_raw,
        "week_pct": week_pct,
        "week_reset_raw": week_reset_raw,
        "sonnet_pct": sonnet_pct,
        "sonnet_reset_raw": sonnet_reset_raw,
        "plan_name": plan_name,
        "top_level_keys": top_level_keys,
        "status_code": 200,
    }


def _make_value_line(pct: int | None, reset_str: str) -> str:
    """
    Build the bar+pct+reset string for --once plain-text output.
    Format: <10-char bar>  <3-char pct>%  · <reset>
    """
    b = bar(pct) if pct is not None else "░" * 10
    pct_str = f"{pct:>3}%" if pct is not None else " n/a"
    return f"{b}  {pct_str}  · {reset_str}"
