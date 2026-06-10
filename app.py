# /// script
# requires-python = ">=3.11"
# dependencies = ["rumps", "httpx", "keyring"]
# ///

import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from core import (
    _make_value_line,
    fetch_usage,
    format_reset_absolute,
    format_reset_relative,
    get_access_token,
    get_plan_info,
)

REPO_URL = "https://github.com/ghostshift-tech/ghostgauge"

VERSION = "1.0.1"

# Threshold constants for warning color + notification
WARN_THRESHOLD = 85   # % at/above which usage is shown in warning color + notified
WARN_RESET = 80       # hysteresis: must drop below this before it can alert again


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

        # Fall back to credentials plan info if API didn't return a plan name
        if not result.get("plan_name"):
            try:
                result["plan_name"] = get_plan_info()
            except Exception:
                pass

        # Print discovered top-level response keys (no values)
        print(f"[top-level response keys]: {result['top_level_keys']}")
        print(f"[plan_name field]: {result['plan_name']!r}")
        print()

        s_pct = result["session_pct"]
        s_reset = format_reset_relative(result["session_reset_raw"])
        w_pct = result["week_pct"]
        w_reset = format_reset_absolute(result["week_reset_raw"])
        sonnet_pct = result["sonnet_pct"]
        sonnet_reset_raw = result.get("sonnet_reset_raw")
        opus_pct = result.get("opus_pct")
        opus_reset_raw = result.get("opus_reset_raw")

        plan_name = result["plan_name"]
        plan_header = f"Plan usage limits — {plan_name}" if plan_name else "Plan usage limits"
        print(plan_header)
        print("  Current session")
        print(f"  {_make_value_line(int(s_pct) if s_pct is not None else None, s_reset)}")
        print()
        print("Weekly limits")
        print("  All models")
        print(f"  {_make_value_line(int(w_pct) if w_pct is not None else None, w_reset)}")

        # Opus row: only show when BOTH pct and reset_raw are present (matches GUI rule)
        if opus_pct is not None and opus_reset_raw is not None:
            opus_reset = format_reset_absolute(opus_reset_raw)
            print("  Opus only")
            print(f"  {_make_value_line(int(opus_pct), opus_reset)}")

        # Sonnet row: only show when BOTH pct and reset_raw are present (matches GUI rule)
        if sonnet_pct is not None and sonnet_reset_raw is not None:
            sonnet_reset = format_reset_absolute(sonnet_reset_raw)
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


def _drawn_spark_image():
    """
    Fallback: build and return an 18x18 NSImage of a Claude-style spark mark
    (orange, 12 tapered rays) drawn via NSBezierPath.
    Returns None on any failure. Never called in --once mode.
    """
    try:
        import math

        from AppKit import NSBezierPath, NSColor, NSGraphicsContext, NSImage
        from Foundation import NSMakePoint, NSMakeSize

        SIZE = 18.0
        NUM_RAYS = 12
        CENTER = SIZE / 2.0
        ANGLE_STEP = 2 * math.pi / NUM_RAYS

        INNER_R = 2.2
        OUTER_R_BASE = 7.6
        OUTER_R_ALT = 6.8
        LINE_W_INNER = 2.2
        LINE_W_OUTER = 0.9

        image = NSImage.alloc().initWithSize_(NSMakeSize(SIZE, SIZE))
        image.lockFocus()
        try:
            ctx = NSGraphicsContext.currentContext()
            ctx.setShouldAntialias_(True)

            orange = NSColor.colorWithSRGBRed_green_blue_alpha_(
                215 / 255.0, 135 / 255.0, 95 / 255.0, 1.0
            )
            orange.set()

            for i in range(NUM_RAYS):
                angle = i * ANGLE_STEP - math.pi / 2.0
                outer_r = OUTER_R_BASE if i % 2 == 0 else OUTER_R_ALT
                mid_r = INNER_R + (outer_r - INNER_R) * 0.45

                x_start = CENTER + INNER_R * math.cos(angle)
                y_start = CENTER + INNER_R * math.sin(angle)
                x_mid = CENTER + mid_r * math.cos(angle)
                y_mid = CENTER + mid_r * math.sin(angle)

                p_inner = NSBezierPath.bezierPath()
                p_inner.setLineWidth_(LINE_W_INNER)
                p_inner.setLineCapStyle_(1)  # NSRoundLineCapStyle
                p_inner.moveToPoint_(NSMakePoint(x_start, y_start))
                p_inner.lineToPoint_(NSMakePoint(x_mid, y_mid))
                p_inner.stroke()

                x_tip = CENTER + outer_r * math.cos(angle)
                y_tip = CENTER + outer_r * math.sin(angle)

                p_outer = NSBezierPath.bezierPath()
                p_outer.setLineWidth_(LINE_W_OUTER)
                p_outer.setLineCapStyle_(1)  # NSRoundLineCapStyle
                p_outer.moveToPoint_(NSMakePoint(x_mid, y_mid))
                p_outer.lineToPoint_(NSMakePoint(x_tip, y_tip))
                p_outer.stroke()

        finally:
            image.unlockFocus()

        image.setTemplate_(False)
        return image
    except Exception:
        return None


def _claude_icon_image():
    """
    Return an 18x18 NSImage for the menubar logo.

    Priority:
      1. Load claude-color.svg via NSImage (vector, color logo).
         Candidate paths tried in order so this works in both run modes:
         - Path(__file__).parent / "claude-color.svg"
           (py2app bundle: script + resources both land in Contents/Resources)
         - Path(__file__).parent / "assets" / "claude-color.svg"
           (dev: repo root / assets/)
         - $RESOURCEPATH / "claude-color.svg"  (explicit py2app env override)
      2. Fall back to the hand-drawn spark (_drawn_spark_image()) on any failure.

    Cached in _claude_icon_cache after first call. Returns None on any failure.
    Never called in --once mode.
    """
    global _claude_icon_cache
    if _claude_icon_cache is not None:
        return _claude_icon_cache

    # --- Attempt to load SVG ---
    try:
        from AppKit import NSImage
        from Foundation import NSMakeSize

        candidates = [
            Path(__file__).parent / "claude-color.svg",
            Path(__file__).parent / "assets" / "claude-color.svg",
        ]
        resource_path_env = os.environ.get("RESOURCEPATH", "")
        if resource_path_env:
            candidates.append(Path(resource_path_env) / "claude-color.svg")

        svg_path = None
        for candidate in candidates:
            if candidate.exists():
                svg_path = candidate
                break

        if svg_path is not None:
            img = NSImage.alloc().initWithContentsOfFile_(str(svg_path))
            if img is not None:
                img.setSize_(NSMakeSize(18.0, 18.0))
                img.setTemplate_(False)
                _claude_icon_cache = img
                return img
    except Exception:
        pass

    # --- Fallback: drawn spark ---
    img = _drawn_spark_image()
    if img is not None:
        _claude_icon_cache = img
    return img


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
        from AppKit import NSBezierPath, NSColor, NSView
        from Foundation import NSMakeRect

        _BAR_TRACK_WIDTH = 150.0
        _BAR_HEIGHT = 6.0
        _BAR_CORNER = min(3.0, _BAR_HEIGHT / 2.0)

        class GhostGaugeBarView(NSView):
            def initWithFrame_(self, frame):
                self = objc.super(GhostGaugeBarView, self).initWithFrame_(frame)
                if self is not None:
                    self._pct = 0.0
                    self._warn = False
                return self

            def setPct_(self, pct):
                self._pct = max(0.0, min(100.0, float(pct)))

            def setWarn_(self, warn: bool):
                self._warn = bool(warn)

            def isFlipped(self):
                return True

            def drawRect_(self, dirty_rect):
                # Track (full width, faint)
                NSColor.tertiaryLabelColor().set()
                track_rect = NSMakeRect(0, 0, _BAR_TRACK_WIDTH, _BAR_HEIGHT)
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    track_rect, _BAR_CORNER, _BAR_CORNER
                ).fill()
                # Fill: warning red when at/above threshold, else Claude orange
                warn_flag = getattr(self, "_warn", False)
                if warn_flag:
                    fill_color = NSColor.colorWithSRGBRed_green_blue_alpha_(
                        224 / 255.0, 83 / 255.0, 63 / 255.0, 1.0
                    )
                else:
                    fill_color = NSColor.colorWithSRGBRed_green_blue_alpha_(
                        215 / 255.0, 135 / 255.0, 95 / 255.0, 1.0
                    )
                fill_w = _BAR_TRACK_WIDTH * self._pct / 100.0
                if self._pct > 0 and fill_w < 3.0:
                    fill_w = 3.0
                if fill_w > 0:
                    fill_color.set()
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
        Opus only           (white label, only if present)
        [====bar====]  5% · resets Mon 1:59 PM
        Sonnet only         (white label, only if present)
        [====bar====]  5% · resets Mon 1:59 PM
    """
    try:
        if not _ensure_appkit_classes():
            return None

        from AppKit import NSColor, NSFont, NSTextField
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

        # ---- Warning color ----
        warn_red = NSColor.colorWithSRGBRed_green_blue_alpha_(
            224 / 255.0, 83 / 255.0, 63 / 255.0, 1.0
        )

        # ---- Prepare data ----
        s_pct = result["session_pct"]
        w_pct = result["week_pct"]
        sonnet_pct = result["sonnet_pct"]
        opus_pct = result.get("opus_pct")

        s_reset = format_reset_relative(result["session_reset_raw"])
        w_reset = format_reset_absolute(result["week_reset_raw"])
        sonnet_reset = (
            format_reset_absolute(result["sonnet_reset_raw"])
            if result.get("sonnet_reset_raw") else None
        )
        opus_reset = (
            format_reset_absolute(result["opus_reset_raw"])
            if result.get("opus_reset_raw") else None
        )

        plan_name = result.get("plan_name")
        plan_header_text = f"Plan usage limits — {plan_name}" if plan_name else "Plan usage limits"

        s_pct_int = int(s_pct) if s_pct is not None else 0
        w_pct_int = int(w_pct) if w_pct is not None else 0

        s_warn = s_pct is not None and s_pct_int >= WARN_THRESHOLD
        w_warn = w_pct is not None and w_pct_int >= WARN_THRESHOLD

        s_suffix_color = warn_red if s_warn else suffix_color
        w_suffix_color = warn_red if w_warn else suffix_color

        s_suffix = f"  {s_pct_int}% · {s_reset}" if s_pct is not None else f"  n/a · {s_reset}"
        w_suffix = f"  {w_pct_int}% · {w_reset}" if w_pct is not None else f"  n/a · {w_reset}"

        show_sonnet = sonnet_pct is not None and sonnet_reset is not None
        sonnet_pct_int = int(sonnet_pct) if sonnet_pct is not None else 0
        sonnet_warn = show_sonnet and sonnet_pct_int >= WARN_THRESHOLD
        sonnet_suffix_color = warn_red if sonnet_warn else suffix_color
        sonnet_suffix = (
            f"  {sonnet_pct_int}% · {sonnet_reset}" if show_sonnet else ""
        )

        show_opus = opus_pct is not None and opus_reset is not None
        opus_pct_int = int(opus_pct) if opus_pct is not None else 0
        opus_warn = show_opus and opus_pct_int >= WARN_THRESHOLD
        opus_suffix_color = warn_red if opus_warn else suffix_color
        opus_suffix = (
            f"  {opus_pct_int}% · {opus_reset}" if show_opus else ""
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
        if show_opus:
            total_h += SONNET_GAP                  # gap before opus
            total_h += LABEL_H + SMALL_GAP        # "Opus only"
            total_h += BAR_ROW_H                   # opus bar row
        if show_sonnet:
            total_h += SONNET_GAP                  # gap before sonnet
            total_h += LABEL_H + SMALL_GAP        # "Sonnet only"
            total_h += BAR_ROW_H                   # sonnet bar row
        total_h += BOTTOM_PAD

        panel = ClaudeUsagePanel.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, total_h)
        )

        # ---- Helper: place a bar row (BarView + suffix label) ----
        def add_bar_row(y: float, pct_int: int, suffix_text: str, warn: bool = False, sc=None) -> float:
            bar_y = y + (BAR_ROW_H - BAR_HEIGHT) / 2.0  # vertically center bar in row
            bv = GhostGaugeBarView.alloc().initWithFrame_(
                NSMakeRect(H_PAD, bar_y, BAR_TRACK_WIDTH, BAR_HEIGHT)
            )
            bv.setPct_(float(pct_int))
            bv.setWarn_(warn)
            panel.addSubview_(bv)

            actual_suffix_color = sc if sc is not None else suffix_color
            suffix_tf = make_label(suffix_text, actual_suffix_color, suffix_font)
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
        y = add_bar_row(y, s_pct_int, s_suffix, warn=s_warn, sc=s_suffix_color)

        y += SECTION_GAP

        # Weekly limits header
        y = add_label(y, "Weekly limits", header_color, header_font, HEADER_H)
        y += SMALL_GAP

        # All models label
        y = add_label(y, "All models", label_color, label_font, LABEL_H)
        y += SMALL_GAP

        # All models bar row
        y = add_bar_row(y, w_pct_int, w_suffix, warn=w_warn, sc=w_suffix_color)

        if show_opus:
            y += SONNET_GAP

            # Opus only label
            y = add_label(y, "Opus only", label_color, label_font, LABEL_H)
            y += SMALL_GAP

            # Opus bar row
            y = add_bar_row(y, opus_pct_int, opus_suffix, warn=opus_warn, sc=opus_suffix_color)

        if show_sonnet:
            y += SONNET_GAP

            # Sonnet only label
            y = add_label(y, "Sonnet only", label_color, label_font, LABEL_H)
            y += SMALL_GAP

            # Sonnet bar row
            y = add_bar_row(y, sonnet_pct_int, sonnet_suffix, warn=sonnet_warn, sc=sonnet_suffix_color)

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
            self.menu = ["Loading…", None, rumps.MenuItem("Refresh", callback=self.on_refresh),
                         rumps.MenuItem("Quit", callback=rumps.quit_application)]
            self._last_result: dict | None = None
            self._last_refresh: datetime | None = None
            self._styling_enabled = _appkit_available()
            self._token = None  # cached access token; read from Keychain once per launch
            self._notified: dict = {}  # per-window key → bool for notification hysteresis
            self._backoff_until = None  # time.monotonic() deadline; None = not rate-limited
            self._backoff_count = 0     # consecutive 429s for exponential backoff
            try:
                self._plan_info = get_plan_info()
            except Exception:
                self._plan_info = None
            self._do_refresh()

        def _build_session_bar_str(self, session_pct) -> str:
            """Return a 5-cell block bar string (each cell = 20%) for the given session percentage."""
            WIDTH = 5
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
                    NSColor,
                    NSFont,
                    NSFontAttributeName,
                    NSForegroundColorAttributeName,
                    NSMutableAttributedString,
                )
                from Foundation import NSRange

                mono_font = NSFont.monospacedSystemFontOfSize_weight_(13.0, 0.0)

                # Use warning red when at/above threshold, else Claude orange
                session_warn = session_pct is not None and pct_int >= WARN_THRESHOLD
                if session_warn:
                    fill_color = NSColor.colorWithSRGBRed_green_blue_alpha_(
                        224 / 255.0, 83 / 255.0, 63 / 255.0, 1.0
                    )
                else:
                    fill_color = NSColor.colorWithSRGBRed_green_blue_alpha_(
                        215 / 255.0, 135 / 255.0, 95 / 255.0, 1.0
                    )
                track_color = NSColor.tertiaryLabelColor()

                full_text = bar_str + suffix
                astr = NSMutableAttributedString.alloc().initWithString_(full_text)
                total_len = len(full_text)

                # Apply monospaced font across entire string
                astr.addAttribute_value_range_(
                    NSFontAttributeName, mono_font, NSRange(0, total_len)
                )

                # Color filled cells (█) — fill_color (orange or warn red)
                filled_count = bar_str.count("█")
                if filled_count > 0:
                    astr.addAttribute_value_range_(
                        NSForegroundColorAttributeName, fill_color, NSRange(0, filled_count)
                    )

                # Color track cells (░) — tertiaryLabel
                track_count = bar_str.count("░")
                if track_count > 0:
                    astr.addAttribute_value_range_(
                        NSForegroundColorAttributeName,
                        track_color,
                        NSRange(filled_count, track_count),
                    )

                # Color suffix — same fill_color as filled cells (orange or warn red)
                if len(suffix) > 0:
                    astr.addAttribute_value_range_(
                        NSForegroundColorAttributeName,
                        fill_color,
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

        def _check_threshold_notifications(self, result: dict):
            """
            Fire rumps notifications when any window crosses WARN_THRESHOLD.
            Uses hysteresis: re-arms only when pct drops below WARN_RESET.
            Wrapped in try/except — safe in dev/non-bundle mode.
            """
            windows = [
                ("session", result.get("session_pct"), "Current session"),
                ("week",    result.get("week_pct"),    "All models"),
                ("opus",    result.get("opus_pct"),    "Opus"),
                ("sonnet",  result.get("sonnet_pct"),  "Sonnet"),
            ]
            for key, pct, label in windows:
                if pct is None:
                    continue
                pct_int = int(pct)
                if pct_int >= WARN_THRESHOLD and not self._notified.get(key, False):
                    try:
                        import rumps as _rumps
                        _rumps.notification(
                            "GhostGauge",
                            f"{label} usage at {pct_int}%",
                            "Approaching your limit",
                        )
                    except Exception:
                        pass
                    self._notified[key] = True
                elif pct_int < WARN_RESET:
                    self._notified[key] = False

        def _do_refresh(self):
            try:
                # Backoff gate: skip network call while still in the rate-limit window.
                if self._backoff_until is not None:
                    if time.monotonic() < self._backoff_until:
                        remaining_min = int((self._backoff_until - time.monotonic()) // 60) + 1
                        status_msg = f"Rate limited — retrying in ~{remaining_min} min"
                        if self._last_result is not None:
                            self._rebuild_menu(self._last_result, status_msg=status_msg)
                        else:
                            self._set_menu_message(status_msg)
                            self.title = "⏳ rate limited"
                        return
                    else:
                        self._backoff_until = None  # window elapsed, fall through and try again

                # Read Keychain only once per launch; re-read only on 401 (token rotation).
                if self._token is None:
                    self._token = get_access_token()
                if self._token is None:
                    self.title = "⚠️ Claude: no token"
                    self._set_menu_message("Could not read Keychain item 'Claude Code-credentials'")
                    return

                result = fetch_usage(self._token)

                # On 401: token may have been rotated — evict cache and retry once.
                if not result["ok"] and result["status_code"] == 401:
                    self._token = None
                    self._token = get_access_token()
                    if self._token is not None:
                        result = fetch_usage(self._token)
                    # If still 401 (or no token), fall through to the error path below.

                if not result["ok"]:
                    sc = result["status_code"]
                    if sc == 401:
                        # 401 is always actionable — user must see it regardless of cached data
                        self.title = "⚠️ Claude: re-auth"
                        self._set_menu_message("Token expired — run `claude` to re-authenticate")
                    elif sc == 429:
                        base = result.get("retry_after")
                        if base is None:
                            base = min(120 * (2 ** self._backoff_count), 1800)
                            self._backoff_count += 1
                        self._backoff_until = time.monotonic() + float(base)
                        wait_min = int(float(base) // 60) + 1
                        status_msg = f"Rate limited — retrying in ~{wait_min} min"
                        if self._last_result is not None:
                            # Keep stale data visible; insert status line below "Last updated"
                            self._rebuild_menu(self._last_result, status_msg=status_msg)
                        else:
                            self.title = "⏳ rate limited"
                            self._set_menu_message(status_msg)
                    else:
                        status_msg = "Refresh failed — will retry"
                        if self._last_result is not None:
                            self._rebuild_menu(self._last_result, status_msg=status_msg)
                        else:
                            self.title = "⚠️ Claude"
                            self._set_menu_message(result["error"])
                    return

                # Successful fetch — fill in plan info from credentials if API didn't return one
                if not result.get("plan_name") and self._plan_info:
                    result["plan_name"] = self._plan_info

                self._backoff_count = 0
                self._backoff_until = None
                self._last_result = result
                self._last_refresh = datetime.now().astimezone()
                self._apply_menubar_title(result)
                self._check_threshold_notifications(result)
                self._rebuild_menu(result)
            except Exception:
                self.title = "⚠️ Claude"
                self._set_menu_message("Refresh failed — try again")

        def _rebuild_menu(self, result: dict, status_msg: str | None = None):
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
                sonnet_reset_raw = result.get("sonnet_reset_raw")
                opus_pct = result.get("opus_pct")
                opus_reset_raw = result.get("opus_reset_raw")
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
                # Opus row: only show when BOTH pct and reset_raw are present (matches GUI rule)
                if opus_pct is not None and opus_reset_raw is not None:
                    items.append(rumps.MenuItem(
                        f"  Opus only: {_make_value_line(int(opus_pct), format_reset_absolute(opus_reset_raw))}"
                    ))
                # Sonnet row: only show when BOTH pct and reset_raw are present (matches GUI rule)
                if sonnet_pct is not None and sonnet_reset_raw is not None:
                    items.append(rumps.MenuItem(
                        f"  Sonnet only: {_make_value_line(int(sonnet_pct), format_reset_absolute(sonnet_reset_raw))}"
                    ))

            items.append(None)  # separator
            last_updated_text = (
                f"Last updated {self._last_refresh.strftime('%-I:%M:%S %p')}"
                if self._last_refresh is not None
                else "Last updated —"
            )
            last_updated_mi = rumps.MenuItem(last_updated_text)
            last_updated_mi.set_callback(None)  # dim, same style as status line below
            items.append(last_updated_mi)
            # Insert status line (dim, no callback) right after "Last updated" when given
            if status_msg is not None:
                status_mi = rumps.MenuItem(status_msg)
                status_mi.set_callback(None)
                items.append(status_mi)
            items.append(rumps.MenuItem("Refresh", callback=self.on_refresh))
            items.append(rumps.MenuItem("Update GhostGauge", callback=self.on_update))
            version_mi = rumps.MenuItem(f"GhostGauge v{VERSION}")
            version_mi.set_callback(None)
            items.append(version_mi)
            items.append(rumps.MenuItem("Quit", callback=rumps.quit_application))

            self.menu.clear()
            self.menu = items

        def _set_menu_message(self, msg: str):
            last_updated_text = (
                f"Last updated {self._last_refresh.strftime('%-I:%M:%S %p')}"
                if self._last_refresh is not None
                else "Last updated —"
            )
            version_mi = rumps.MenuItem(f"GhostGauge v{VERSION}")
            version_mi.set_callback(None)
            last_updated_mi = rumps.MenuItem(last_updated_text)
            last_updated_mi.set_callback(None)  # dim, same style as version item
            self.menu.clear()
            self.menu = [
                rumps.MenuItem(msg),
                None,
                last_updated_mi,
                rumps.MenuItem("Refresh", callback=self.on_refresh),
                rumps.MenuItem("Update GhostGauge", callback=self.on_update),
                version_mi,
                rumps.MenuItem("Quit", callback=rumps.quit_application),
            ]

        @rumps.timer(60)
        def auto_refresh(self, _sender):
            self._do_refresh()

        def on_refresh(self, _sender):
            self._backoff_until = None
            self._backoff_count = 0
            self._do_refresh()

        def _on_wake(self):
            """Called on system wake-from-sleep via rumps.events.on_wake."""
            self._do_refresh()

        def on_update(self, _sender):
            try:
                # Resolve source repo path: bundle writes source_path.txt next to app.py
                source_txt = Path(__file__).parent / "source_path.txt"
                if source_txt.exists():
                    content = source_txt.read_text(encoding="utf-8").strip()
                    path = Path(content) if content else Path(__file__).parent
                else:
                    path = Path(__file__).parent

                if path.exists() and (path / ".git").exists():
                    inner = f"cd {shlex.quote(str(path))} && git pull && ./install.sh"
                    as_escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
                    script = f'tell application "Terminal" to do script "{as_escaped}"'
                    subprocess.run(["osascript", "-e", script], check=False)
                else:
                    subprocess.run(["open", REPO_URL], check=False)
                    try:
                        rumps.notification(
                            "GhostGauge",
                            "Update",
                            "Source repo not found locally — opened the GitHub page. "
                            "Pull and run install.command manually.",
                        )
                    except Exception:
                        pass
            except Exception:
                subprocess.run(["open", REPO_URL], check=False)

    app = GhostGauge()
    try:
        rumps.events.on_wake.register(app._on_wake)
    except Exception:
        pass
    app.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Claude Code usage menubar app")
    parser.add_argument("--once", action="store_true", help="Print usage once and exit (no GUI)")
    args = parser.parse_args()

    if args.once:
        sys.exit(run_once())
    else:
        main_gui()
