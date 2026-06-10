"""
core.py — pure / data logic for GhostGauge.

No rumps, no AppKit, no macOS-only imports.
Importable on Linux (CI) with only stdlib + httpx + keyring.
"""

import getpass
import json
import subprocess
import sys
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


def _read_keychain_via_security() -> str | None:
    """
    Read the credentials JSON via /usr/bin/security (Apple-signed, stable code
    identity) instead of Security.framework from our own binary. The keychain
    ACL "allow" then sticks across rebuilds, so the user is never re-prompted.
    Returns the raw secret string or None. Never logs the secret.
    """
    if sys.platform != "darwin":
        return None
    try:
        proc = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", getpass.getuser(), "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _read_raw_credentials() -> str | None:
    """
    Read the raw credentials JSON string from the best available source.
    Lookup order:
    1. /usr/bin/security CLI (macOS only)
    2. keyring.get_password()
    3. CREDENTIALS_FILE (~/.claude/.credentials.json)
    Returns the raw string or None. Never logs the secret.
    """
    raw = _read_keychain_via_security()
    if raw is None:
        try:
            raw = keyring.get_password(KEYCHAIN_SERVICE, getpass.getuser())
        except Exception:
            raw = None
    if raw is None and CREDENTIALS_FILE.exists():
        try:
            raw = CREDENTIALS_FILE.read_text(encoding="utf-8")
        except OSError:
            return None
    return raw


def get_access_token() -> str | None:
    """
    Read OAuth access token from the best available source. Lookup order:

    1. /usr/bin/security CLI (macOS only) — Apple-signed binary whose code identity
       never changes across rebuilds, so the keychain ACL prompt is shown only once.
    2. keyring.get_password() — fallback for non-macOS or if the CLI fails.
    3. CREDENTIALS_FILE (~/.claude/.credentials.json) — last resort flat-file fallback.

    Never returns token material to caller logs.
    """
    raw = _read_raw_credentials()
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        if "claudeAiOauth" in data:
            return data["claudeAiOauth"]["accessToken"]
        return data["accessToken"]
    except (json.JSONDecodeError, KeyError):
        return None


def get_plan_info() -> str | None:
    """
    Read subscriptionType and rateLimitTier from credentials JSON and return a
    human-readable plan string like "Max 5x" or "Pro".
    Returns None if nothing usable is found.
    MUST never return token material — only subscriptionType / rateLimitTier fields.
    """
    import re

    raw = _read_raw_credentials()
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        # Unwrap claudeAiOauth envelope if present
        if "claudeAiOauth" in data:
            inner = data["claudeAiOauth"]
        else:
            inner = data
        if not isinstance(inner, dict):
            return None

        subscription_type = inner.get("subscriptionType")
        rate_limit_tier = inner.get("rateLimitTier")

        if not subscription_type or not isinstance(subscription_type, str):
            return None

        plan = subscription_type.capitalize()

        # Extract multiplier suffix like "5x" from e.g. "default_claude_max_5x"
        if rate_limit_tier and isinstance(rate_limit_tier, str):
            m = re.search(r"_(\d+x)$", rate_limit_tier)
            if m:
                plan = f"{plan} {m.group(1)}"

        return plan
    except (json.JSONDecodeError, KeyError, AttributeError):
        return None


def bar(pct: float, width: int = 10) -> str:
    """Render a unicode block progress bar of given width (plain ASCII, used by --once mode).
    Minimum fill: if pct > 0 but rounding gives 0 filled cells, uses 1 cell."""
    pct = max(0, min(100, pct))
    filled = round(pct / 100 * width)
    if pct > 0 and filled == 0:
        filled = 1
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
    sonnet_pct, sonnet_reset_raw, opus_pct, opus_reset_raw, plan_name, top_level_keys,
    error, status_code.
    sonnet_* and opus_* keys are None when window is absent/null.
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
        raw_retry = resp.headers.get("Retry-After")
        retry_after = None
        if raw_retry is not None:
            try:
                retry_after = float(int(raw_retry))
            except ValueError:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(raw_retry)
                    retry_after = max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
                except Exception:
                    retry_after = None
        return {"ok": False, "error": "rate_limited", "status_code": 429, "retry_after": retry_after}
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
    seven_day_opus = data.get("seven_day_opus") or {}

    session_pct = extract_pct(five_hour)
    session_reset_raw = extract_reset(five_hour)
    week_pct = extract_pct(seven_day)
    week_reset_raw = extract_reset(seven_day)

    sonnet_pct = extract_pct(seven_day_sonnet) if seven_day_sonnet else None
    sonnet_reset_raw = extract_reset(seven_day_sonnet) if seven_day_sonnet else None

    opus_pct = extract_pct(seven_day_opus) if seven_day_opus else None
    opus_reset_raw = extract_reset(seven_day_opus) if seven_day_opus else None

    plan_name = find_plan_name(data)

    return {
        "ok": True,
        "session_pct": session_pct,
        "session_reset_raw": session_reset_raw,
        "week_pct": week_pct,
        "week_reset_raw": week_reset_raw,
        "sonnet_pct": sonnet_pct,
        "sonnet_reset_raw": sonnet_reset_raw,
        "opus_pct": opus_pct,
        "opus_reset_raw": opus_reset_raw,
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
