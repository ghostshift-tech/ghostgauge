# /// script
# requires-python = ">=3.11"
# dependencies = ["rumps", "httpx", "keyring"]
# ///

import argparse
import getpass
import json
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
    sonnet_pct, sonnet_reset_raw, plan_name, top_level_keys, error, status_code.
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


def run_once() -> int:
    """--once mode: print usage then exit. Never print token material."""
    try:
        token = get_access_token()
        if token is None:
            print("Error: Could not read Keychain item 'Claude Code-credentials'", file=sys.stderr)
            return 1

        result = fetch_usage(token)
        if not result["ok"]:
            sc = result["status_code"]
            err = result["error"]
            if sc == 401:
                print("Error: Token expired — run `claude` to re-authenticate")
            elif sc == 429:
                print("Error: Rate limited by API — try again later")
            else:
                print(f"Error: {err}")
            return 1

        # Print discovered top-level response keys (no values)
        print(f"[top-level response keys]: {result['top_level_keys']}")
        print(f"[plan_name field]: {result['plan_name']!r}")
        print()

        s_pct = result["session_pct"]
        s_reset = format_reset_relative(result["session_reset_raw"])
        w_pct = result["week_pct"]
        w_reset = format_reset_absolute(result["week_reset_raw"])
        sonnet_pct = result["sonnet_pct"]
        sonnet_reset = format_reset_absolute(result["sonnet_reset_raw"])

        plan_name = result["plan_name"]
        plan_header = f"Plan usage limits — {plan_name}" if plan_name else "Plan usage limits"
        print(plan_header)
        print(f"  Current session")
        print(f"  {_make_value_line(int(s_pct) if s_pct is not None else None, s_reset)}")
        print()
        print("Weekly limits")
        print("  All models")
        print(f"  {_make_value_line(int(w_pct) if w_pct is not None else None, w_reset)}")

        if sonnet_pct is not None and sonnet_reset is not None:
            print("  Sonnet only")
            print(f"  {_make_value_line(int(sonnet_pct), sonnet_reset)}")

        return 0
    except Exception:
        print("Error: unexpected failure", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# AppKit custom NSView panel (GUI only — never called in --once mode)
# ---------------------------------------------------------------------------

# Module-level cache for the Claude icon NSImage (built once, GUI-only).
_claude_icon_cache = None


def _claude_icon_image():
    """
    Build and return a 16x16 NSImage of a Claude-style sunburst (orange, ~11 spokes).
    Cached in _claude_icon_cache after first call. Returns None on any failure.
    Never called in --once mode.
    """
    global _claude_icon_cache
    if _claude_icon_cache is not None:
        return _claude_icon_cache
    try:
        import math
        from AppKit import NSImage, NSBezierPath, NSColor, NSGraphicsContext
        from Foundation import NSMakeSize, NSMakePoint, NSZeroRect

        SIZE = 18.0  # slightly larger backing for crispness, displayed at ~16 pt
        NUM_SPOKES = 11
        CENTER = SIZE / 2.0
        INNER_R = 2.8   # spoke starts near center
        OUTER_R = 7.8   # spoke ends near edge
        LINE_W = 1.7
        ANGLE_STEP = 2 * math.pi / NUM_SPOKES

        image = NSImage.alloc().initWithSize_(NSMakeSize(SIZE, SIZE))
        image.lockFocus()
        try:
            ctx = NSGraphicsContext.currentContext()
            ctx.setShouldAntialias_(True)

            orange = NSColor.colorWithSRGBRed_green_blue_alpha_(
                215 / 255.0, 135 / 255.0, 95 / 255.0, 1.0
            )
            orange.set()

            path = NSBezierPath.bezierPath()
            path.setLineWidth_(LINE_W)
            path.setLineCapStyle_(1)  # NSRoundLineCapStyle = 1

            for i in range(NUM_SPOKES):
                angle = i * ANGLE_STEP - math.pi / 2.0  # start from top
                x1 = CENTER + INNER_R * math.cos(angle)
                y1 = CENTER + INNER_R * math.sin(angle)
                x2 = CENTER + OUTER_R * math.cos(angle)
                y2 = CENTER + OUTER_R * math.sin(angle)
                path.moveToPoint_(NSMakePoint(x1, y1))
                path.lineToPoint_(NSMakePoint(x2, y2))

            path.stroke()
        finally:
            image.unlockFocus()

        image.setTemplate_(False)
        _claude_icon_cache = image
        return image
    except Exception:
        return None

def _appkit_available() -> bool:
    """Return True if AppKit/Foundation are importable (always True on macOS with rumps installed)."""
    try:
        from AppKit import NSColor  # noqa: F401
        return True
    except ImportError:
        return False


# PyObjC NSView subclasses must be defined at module level exactly once.
# We define them lazily on first use but keep them in module-level globals so
# they are never re-registered (PyObjC raises if you define the same ObjC
# class name twice in the same process).
_GhostGaugeBarView = None
_ClaudeUsagePanel = None


def _ensure_appkit_classes() -> bool:
    """
    Register PyObjC NSView subclasses once at module level.
    Returns True on success, False if AppKit is unavailable.
    """
    global _GhostGaugeBarView, _ClaudeUsagePanel
    if _GhostGaugeBarView is not None:
        return True
    try:
        import objc
        from AppKit import NSView, NSColor, NSBezierPath
        from Foundation import NSMakeRect

        _BAR_TRACK_WIDTH = 150.0
        _BAR_HEIGHT = 6.0
        _BAR_CORNER = min(3.0, _BAR_HEIGHT / 2.0)

        class GhostGaugeBarView(NSView):
            def initWithFrame_(self, frame):
                self = objc.super(GhostGaugeBarView, self).initWithFrame_(frame)
                if self is not None:
                    self._pct = 0.0
                return self

            def setPct_(self, pct):
                self._pct = max(0.0, min(100.0, float(pct)))

            def isFlipped(self):
                return True

            def drawRect_(self, dirty_rect):
                # Track (full width, faint)
                NSColor.tertiaryLabelColor().set()
                track_rect = NSMakeRect(0, 0, _BAR_TRACK_WIDTH, _BAR_HEIGHT)
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    track_rect, _BAR_CORNER, _BAR_CORNER
                ).fill()
                # Fill (orange, proportional)
                claude_orange = NSColor.colorWithSRGBRed_green_blue_alpha_(
                    215 / 255.0, 135 / 255.0, 95 / 255.0, 1.0
                )
                fill_w = _BAR_TRACK_WIDTH * self._pct / 100.0
                if self._pct > 0 and fill_w < 3.0:
                    fill_w = 3.0
                if fill_w > 0:
                    claude_orange.set()
                    fill_rect = NSMakeRect(0, 0, fill_w, _BAR_HEIGHT)
                    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                        fill_rect, _BAR_CORNER, _BAR_CORNER
                    ).fill()

        class ClaudeUsagePanel(NSView):
            def isFlipped(self):
                return True

        _GhostGaugeBarView = GhostGaugeBarView
        _ClaudeUsagePanel = ClaudeUsagePanel
        return True
    except Exception:
        return False


def _build_usage_panel(result: dict):
    """
    Build and return an NSView containing the Claude Desktop-style usage panel.
    GUI-only — never call in --once mode.
    Returns None if AppKit is unavailable or construction fails.

    Layout (top to bottom):
        Plan usage limits   (dim header)
        Current session     (white label)
        [====bar====]  6% · resets in 4h 31m
        (section gap)
        Weekly limits       (dim header)
        All models          (white label)
        [====bar====]  17% · resets Mon 1:59 PM
        Sonnet only         (white label, only if present)
        [====bar====]  5% · resets Mon 1:59 PM
    """
    try:
        if not _ensure_appkit_classes():
            return None

        from AppKit import NSTextField, NSColor, NSFont
        from Foundation import NSMakeRect

        GhostGaugeBarView = _GhostGaugeBarView
        ClaudeUsagePanel = _ClaudeUsagePanel

        PANEL_WIDTH = 360.0
        H_PAD = 16.0
        BAR_TRACK_WIDTH = 150.0
        BAR_HEIGHT = 6.0   # must match _BAR_HEIGHT used in GhostGaugeBarView.drawRect_

        # ---- Helper: make a label NSTextField ----
        def make_label(text: str, color, font) -> NSTextField:
            tf = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
            tf.setEditable_(False)
            tf.setBezeled_(False)
            tf.setDrawsBackground_(False)
            tf.setSelectable_(False)
            tf.setStringValue_(text)
            tf.setTextColor_(color)
            tf.setFont_(font)
            tf.sizeToFit()
            return tf

        # ---- Fonts / colors ----
        header_font = NSFont.systemFontOfSize_weight_(11.0, 0.0)        # semibold-ish weight 0 = regular; close enough
        label_font = NSFont.systemFontOfSize_(13.0)
        suffix_font = NSFont.systemFontOfSize_(12.0)
        header_color = NSColor.secondaryLabelColor()
        label_color = NSColor.labelColor()
        suffix_color = NSColor.secondaryLabelColor()

        # ---- Prepare data ----
        s_pct = result["session_pct"]
        w_pct = result["week_pct"]
        sonnet_pct = result["sonnet_pct"]

        s_reset = format_reset_relative(result["session_reset_raw"])
        w_reset = format_reset_absolute(result["week_reset_raw"])
        sonnet_reset = (
            format_reset_absolute(result["sonnet_reset_raw"])
            if result.get("sonnet_reset_raw") else None
        )

        plan_name = result.get("plan_name")
        plan_header_text = f"Plan usage limits — {plan_name}" if plan_name else "Plan usage limits"

        s_pct_int = int(s_pct) if s_pct is not None else 0
        w_pct_int = int(w_pct) if w_pct is not None else 0

        s_suffix = f"  {s_pct_int}% · {s_reset}" if s_pct is not None else f"  n/a · {s_reset}"
        w_suffix = f"  {w_pct_int}% · {w_reset}" if w_pct is not None else f"  n/a · {w_reset}"

        show_sonnet = sonnet_pct is not None and sonnet_reset is not None
        sonnet_pct_int = int(sonnet_pct) if sonnet_pct is not None else 0
        sonnet_suffix = (
            f"  {sonnet_pct_int}% · {sonnet_reset}" if show_sonnet else ""
        )

        # ---- Layout constants ----
        TOP_PAD = 12.0
        BOTTOM_PAD = 12.0
        HEADER_H = 18.0
        LABEL_H = 20.0
        BAR_ROW_H = 20.0   # row height that contains the bar + suffix
        SMALL_GAP = 4.0    # gap between label and bar row / between header and label
        SECTION_GAP = 12.0 # gap between sections
        SONNET_GAP = 8.0   # extra gap before sonnet row within weekly section

        # ---- Compute total height ----
        total_h = TOP_PAD
        total_h += HEADER_H + SMALL_GAP           # plan header
        total_h += LABEL_H + SMALL_GAP            # "Current session"
        total_h += BAR_ROW_H                       # session bar row
        total_h += SECTION_GAP                     # gap between sections
        total_h += HEADER_H + SMALL_GAP           # "Weekly limits"
        total_h += LABEL_H + SMALL_GAP            # "All models"
        total_h += BAR_ROW_H                       # all-models bar row
        if show_sonnet:
            total_h += SONNET_GAP                  # gap before sonnet
            total_h += LABEL_H + SMALL_GAP        # "Sonnet only"
            total_h += BAR_ROW_H                   # sonnet bar row
        total_h += BOTTOM_PAD

        panel = ClaudeUsagePanel.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, total_h)
        )

        # ---- Helper: place a bar row (BarView + suffix label) ----
        def add_bar_row(y: float, pct_int: int, suffix_text: str) -> float:
            bar_y = y + (BAR_ROW_H - BAR_HEIGHT) / 2.0  # vertically center bar in row
            bv = GhostGaugeBarView.alloc().initWithFrame_(
                NSMakeRect(H_PAD, bar_y, BAR_TRACK_WIDTH, BAR_HEIGHT)
            )
            bv.setPct_(float(pct_int))
            panel.addSubview_(bv)

            suffix_tf = make_label(suffix_text, suffix_color, suffix_font)
            sx = H_PAD + BAR_TRACK_WIDTH + 6.0
            # vertically center suffix text in row
            suffix_frame = suffix_tf.frame()
            sy = y + (BAR_ROW_H - suffix_frame.size.height) / 2.0
            suffix_tf.setFrameOrigin_((sx, sy))
            panel.addSubview_(suffix_tf)

            return y + BAR_ROW_H

        # ---- Helper: place a full-width label ----
        def add_label(y: float, text: str, color, font, row_h: float) -> float:
            tf = make_label(text, color, font)
            tf_frame = tf.frame()
            ty = y + (row_h - tf_frame.size.height) / 2.0
            tf.setFrameOrigin_((H_PAD, ty))
            panel.addSubview_(tf)
            return y + row_h

        # ---- Lay out rows top-to-bottom ----
        y = TOP_PAD

        # Plan header
        y = add_label(y, plan_header_text, header_color, header_font, HEADER_H)
        y += SMALL_GAP

        # Current session label
        y = add_label(y, "Current session", label_color, label_font, LABEL_H)
        y += SMALL_GAP

        # Session bar row
        y = add_bar_row(y, s_pct_int, s_suffix)

        y += SECTION_GAP

        # Weekly limits header
        y = add_label(y, "Weekly limits", header_color, header_font, HEADER_H)
        y += SMALL_GAP

        # All models label
        y = add_label(y, "All models", label_color, label_font, LABEL_H)
        y += SMALL_GAP

        # All models bar row
        y = add_bar_row(y, w_pct_int, w_suffix)

        if show_sonnet:
            y += SONNET_GAP

            # Sonnet only label
            y = add_label(y, "Sonnet only", label_color, label_font, LABEL_H)
            y += SMALL_GAP

            # Sonnet bar row
            y = add_bar_row(y, sonnet_pct_int, sonnet_suffix)

        return panel

    except Exception:
        return None


# ---------------------------------------------------------------------------
# GUI entry point
# ---------------------------------------------------------------------------

def main_gui():
    import rumps

    class GhostGauge(rumps.App):
        def __init__(self):
            super().__init__("Claude", title="⏳ Claude")
            self.menu = ["Loading…", None, rumps.MenuItem("↻ Refresh", callback=self.on_refresh),
                         rumps.MenuItem("Quit", callback=rumps.quit_application)]
            self._last_result: dict | None = None
            self._styling_enabled = _appkit_available()
            self._do_refresh()

        def _build_session_bar_str(self, session_pct) -> str:
            """Return a 12-cell block bar string for the given session percentage."""
            WIDTH = 12
            if session_pct is None:
                return "░" * WIDTH
            pct = max(0, min(100, int(session_pct)))
            filled = round(pct / 100 * WIDTH)
            if pct > 0 and filled < 1:
                filled = 1
            return "█" * filled + "░" * (WIDTH - filled)

        def _apply_menubar_title(self, result: dict):
            """
            Set the image + attributed title on the NSStatusItem button.
            Falls back gracefully to plain self.title if anything fails.
            """
            session_pct = result.get("session_pct")
            pct_int = max(0, min(100, int(session_pct))) if session_pct is not None else 0
            bar_str = self._build_session_bar_str(session_pct)
            suffix = f"  {pct_int}%"

            # --- plain-text fallback (always set first so it's never empty) ---
            self.title = f"{bar_str}{suffix}"

            if not self._styling_enabled:
                return

            try:
                from AppKit import (
                    NSMutableAttributedString, NSAttributedString,
                    NSColor, NSFont,
                    NSForegroundColorAttributeName, NSFontAttributeName,
                )
                from Foundation import NSRange

                mono_font = NSFont.monospacedSystemFontOfSize_weight_(13.0, 0.0)
                orange = NSColor.colorWithSRGBRed_green_blue_alpha_(
                    215 / 255.0, 135 / 255.0, 95 / 255.0, 1.0
                )
                track_color = NSColor.tertiaryLabelColor()
                label_color = NSColor.labelColor()

                full_text = bar_str + suffix
                astr = NSMutableAttributedString.alloc().initWithString_(full_text)
                total_len = len(full_text)

                # Apply monospaced font across entire string
                astr.addAttribute_value_range_(
                    NSFontAttributeName, mono_font, NSRange(0, total_len)
                )

                # Color filled cells (█) — orange
                filled_count = bar_str.count("█")
                if filled_count > 0:
                    astr.addAttribute_value_range_(
                        NSForegroundColorAttributeName, orange, NSRange(0, filled_count)
                    )

                # Color track cells (░) — tertiaryLabel
                track_count = bar_str.count("░")
                if track_count > 0:
                    astr.addAttribute_value_range_(
                        NSForegroundColorAttributeName,
                        track_color,
                        NSRange(filled_count, track_count),
                    )

                # Color suffix — labelColor
                if len(suffix) > 0:
                    astr.addAttribute_value_range_(
                        NSForegroundColorAttributeName,
                        label_color,
                        NSRange(len(bar_str), len(suffix)),
                    )

                # Find the NSStatusItem button via rumps internals
                button = None
                try:
                    nsapp = getattr(self, "_nsapp", None)
                    nsstatusitem = getattr(nsapp, "nsstatusitem", None)
                    if nsstatusitem is not None:
                        button = nsstatusitem.button()
                except Exception:
                    button = None

                if button is not None:
                    icon = _claude_icon_image()
                    if icon is not None:
                        button.setImage_(icon)
                        button.setImagePosition_(2)  # NSImageLeft = 2
                    # setAttributedTitle_ overrides the plain title set above.
                    # Do NOT call self.title = "" afterwards — NSButton.setTitle_
                    # shares storage with the attributed title and would wipe it.
                    button.setAttributedTitle_(astr)
                # If button is None, the plain self.title set above stands.

            except Exception:
                # Any AppKit failure — plain title already set above, just continue.
                pass

        def _do_refresh(self):
            try:
                token = get_access_token()
                if token is None:
                    self.title = "⚠️ Claude: no token"
                    self._set_menu_message("Could not read Keychain item 'Claude Code-credentials'")
                    return

                result = fetch_usage(token)
                if not result["ok"]:
                    sc = result["status_code"]
                    if sc == 401:
                        self.title = "⚠️ Claude: re-auth"
                        self._set_menu_message("Token expired — run `claude` to re-authenticate")
                    elif sc == 429:
                        self.title = "⏳ Claude: rate limited"
                        self._set_menu_message("Rate limited — will retry automatically")
                    else:
                        self.title = "⚠️ Claude"
                        self._set_menu_message(result["error"])
                    return

                self._last_result = result
                self._apply_menubar_title(result)
                self._rebuild_menu(result)
            except Exception:
                self.title = "⚠️ Claude"
                self._set_menu_message("Refresh failed — try again")

        def _rebuild_menu(self, result: dict):
            panel = None
            if self._styling_enabled:
                try:
                    panel = _build_usage_panel(result)
                except Exception:
                    panel = None

            items = []

            if panel is not None:
                # Mount the NSView panel inside a MenuItem (non-interactive, no hover highlight)
                panel_mi = rumps.MenuItem("")
                panel_mi._menuitem.setView_(panel)
                items.append(panel_mi)
            else:
                # Fallback: plain text items when AppKit is unavailable or panel build fails
                s_pct = result["session_pct"]
                w_pct = result["week_pct"]
                sonnet_pct = result["sonnet_pct"]
                s_reset = format_reset_relative(result["session_reset_raw"])
                w_reset = format_reset_absolute(result["week_reset_raw"])
                plan_name = result.get("plan_name")
                plan_header = f"Plan usage limits — {plan_name}" if plan_name else "Plan usage limits"
                items.append(rumps.MenuItem(plan_header))
                items.append(rumps.MenuItem(
                    f"  Current session: {_make_value_line(int(s_pct) if s_pct is not None else None, s_reset)}"
                ))
                items.append(rumps.MenuItem(
                    f"  All models: {_make_value_line(int(w_pct) if w_pct is not None else None, w_reset)}"
                ))
                if sonnet_pct is not None:
                    sonnet_reset = format_reset_absolute(result["sonnet_reset_raw"])
                    items.append(rumps.MenuItem(
                        f"  Sonnet only: {_make_value_line(int(sonnet_pct), sonnet_reset)}"
                    ))

            items.append(None)  # separator
            items.append(rumps.MenuItem("↻ Refresh", callback=self.on_refresh))
            items.append(rumps.MenuItem("Quit", callback=rumps.quit_application))

            self.menu.clear()
            self.menu = items

        def _set_menu_message(self, msg: str):
            self.menu.clear()
            self.menu = [
                rumps.MenuItem(msg),
                None,
                rumps.MenuItem("↻ Refresh", callback=self.on_refresh),
                rumps.MenuItem("Quit", callback=rumps.quit_application),
            ]

        @rumps.timer(60)
        def auto_refresh(self, _sender):
            self._do_refresh()

        def on_refresh(self, _sender):
            self._do_refresh()

    GhostGauge().run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Claude Code usage menubar app")
    parser.add_argument("--once", action="store_true", help="Print usage once and exit (no GUI)")
    args = parser.parse_args()

    if args.once:
        sys.exit(run_once())
    else:
        main_gui()
