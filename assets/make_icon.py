# /// script
# requires-python = ">=3.11"
# dependencies = ["pyobjc-framework-Cocoa", "pyobjc-framework-Quartz"]
# ///
"""
Draws the GhostGauge app icon (1024x1024) using AppKit/PyObjC and saves it
as assets/icon_1024.png relative to this script's directory.

Layout:
  - Dark squircle background with vertical gradient #34343A -> #1A1A1E
  - Gauge arc (240° sweep, gap at bottom): track in #4A4A50, value in #D7875F
  - Needle pointing to ~68% position, colored #F0C9B4
  - Center hub circle in #D7875F
"""

import math
import os

import AppKit
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize
from Quartz import CoreGraphics


def color(hex_str: str, alpha: float = 1.0) -> AppKit.NSColor:
    """Convert a CSS hex color string to NSColor (sRGB)."""
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


def draw_icon(size: int = 1024) -> AppKit.NSImage:
    s = float(size)
    cx = s / 2
    cy = s / 2

    image = AppKit.NSImage.alloc().initWithSize_(NSMakeSize(s, s))
    image.lockFocus()
    try:
        ctx = AppKit.NSGraphicsContext.currentContext()
        ctx.setImageInterpolation_(AppKit.NSImageInterpolationHigh)
        ctx.setShouldAntialias_(True)

        # ------------------------------------------------------------------ #
        # 1. Clear to transparent                                              #
        # ------------------------------------------------------------------ #
        AppKit.NSColor.clearColor().set()
        AppKit.NSRectFill(NSMakeRect(0, 0, s, s))

        # ------------------------------------------------------------------ #
        # 2. Squircle background                                               #
        # ------------------------------------------------------------------ #
        corner_radius = 224.0
        squircle = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, s, s), corner_radius, corner_radius
        )

        # Vertical gradient: AppKit Y-axis is bottom-up, so startPoint is
        # bottom (y=0) for the dark end, endPoint is top (y=s) for the light end.
        grad = AppKit.NSGradient.alloc().initWithStartingColor_endingColor_(
            color("#1A1A1E"),  # bottom (darker)
            color("#34343A"),  # top (lighter)
        )
        grad.drawInBezierPath_angle_(squircle, 270)  # 270° = bottom-to-top

        # ------------------------------------------------------------------ #
        # 3. Gauge arc parameters                                              #
        # ------------------------------------------------------------------ #
        # AppKit angles: 0° = 3 o'clock, increases counter-clockwise (math convention).
        # We want a 240° gauge with the gap at the bottom:
        #   start: 210° from positive-x (i.e. lower-left), sweep clockwise 240°.
        # NSBezierPath appendBezierPathWithArcWithCenter uses clockwise=YES for
        # going in the negative (clockwise) direction in AppKit's flipped-y math.
        # Easier: use CoreGraphics context directly via NSGraphicsContext.CGContext.

        cg_ctx = ctx.CGContext()

        arc_center_x = cx
        arc_center_y = cy + s * 0.03  # shift center slightly upward for visual balance
        arc_radius = s * 0.305         # ~62% of half-canvas, leaves good padding
        stroke_width = 70.0

        # CG angles are in radians, measured counter-clockwise from positive-x.
        # Gap at the bottom means the arc goes from lower-right to lower-left
        # (clockwise). In CG:
        #   start = -210° = -210*pi/180 (lower left in standard math = 210° CCW from +x)
        #   end   = -210° + 240° but going clockwise means subtracting in CG space
        # Simpler: start_cg = 210° CCW = 7π/6, end_cg = 210° - 240° = -30° = 330° CCW
        # clockwise=1 in CG means clockwise (decreasing angle).
        start_angle_deg = 210.0   # lower-left of gap
        sweep_deg       = 240.0
        end_angle_deg   = start_angle_deg - sweep_deg  # = -30 deg == 330 deg

        start_rad = math.radians(start_angle_deg)
        end_rad   = math.radians(end_angle_deg)

        # ------------------------------------------------------------------ #
        # 3a. Track arc (dim, full 240°)                                       #
        # ------------------------------------------------------------------ #
        CoreGraphics.CGContextSaveGState(cg_ctx)
        CoreGraphics.CGContextSetLineWidth(cg_ctx, stroke_width)
        CoreGraphics.CGContextSetLineCap(cg_ctx, CoreGraphics.kCGLineCapRound)
        r, g, b = 0x4A / 255.0, 0x4A / 255.0, 0x50 / 255.0
        CoreGraphics.CGContextSetRGBStrokeColor(cg_ctx, r, g, b, 1.0)
        CoreGraphics.CGContextAddArc(
            cg_ctx,
            arc_center_x, arc_center_y,
            arc_radius,
            start_rad, end_rad,
            1,  # clockwise
        )
        CoreGraphics.CGContextStrokePath(cg_ctx)
        CoreGraphics.CGContextRestoreGState(cg_ctx)

        # ------------------------------------------------------------------ #
        # 3b. Value arc (orange, ~68% of 240° = 163.2°)                       #
        # ------------------------------------------------------------------ #
        value_pct   = 0.68
        value_sweep = sweep_deg * value_pct          # 163.2°
        value_end_deg = start_angle_deg - value_sweep  # = 46.8°
        value_end_rad = math.radians(value_end_deg)

        CoreGraphics.CGContextSaveGState(cg_ctx)
        CoreGraphics.CGContextSetLineWidth(cg_ctx, stroke_width)
        CoreGraphics.CGContextSetLineCap(cg_ctx, CoreGraphics.kCGLineCapRound)
        r, g, b = 0xD7 / 255.0, 0x87 / 255.0, 0x5F / 255.0
        CoreGraphics.CGContextSetRGBStrokeColor(cg_ctx, r, g, b, 1.0)
        CoreGraphics.CGContextAddArc(
            cg_ctx,
            arc_center_x, arc_center_y,
            arc_radius,
            start_rad, value_end_rad,
            1,  # clockwise
        )
        CoreGraphics.CGContextStrokePath(cg_ctx)
        CoreGraphics.CGContextRestoreGState(cg_ctx)

        # ------------------------------------------------------------------ #
        # 4. Needle                                                            #
        # ------------------------------------------------------------------ #
        # Needle points from center hub toward the arc at the value_end angle.
        needle_angle_rad = value_end_rad
        needle_len       = arc_radius - stroke_width * 0.5 - 18  # stops just inside arc
        hub_radius       = 42.0

        needle_tip_x = arc_center_x + math.cos(needle_angle_rad) * needle_len
        needle_tip_y = arc_center_y + math.sin(needle_angle_rad) * needle_len

        # Tapered needle: draw a filled shape instead of a line for polish.
        # Base (at hub): half-width = 13, Tip: half-width = 3
        perp_angle = needle_angle_rad + math.pi / 2  # perpendicular
        base_hw    = 13.0
        tip_hw     = 3.0
        hub_x      = arc_center_x + math.cos(needle_angle_rad) * hub_radius
        hub_y      = arc_center_y + math.sin(needle_angle_rad) * hub_radius

        p1x = hub_x + math.cos(perp_angle) * base_hw
        p1y = hub_y + math.sin(perp_angle) * base_hw
        p2x = hub_x - math.cos(perp_angle) * base_hw
        p2y = hub_y - math.sin(perp_angle) * base_hw
        p3x = needle_tip_x - math.cos(perp_angle) * tip_hw
        p3y = needle_tip_y - math.sin(perp_angle) * tip_hw
        p4x = needle_tip_x + math.cos(perp_angle) * tip_hw
        p4y = needle_tip_y + math.sin(perp_angle) * tip_hw

        needle_path = AppKit.NSBezierPath.bezierPath()
        needle_path.moveToPoint_(NSMakePoint(p1x, p1y))
        needle_path.lineToPoint_(NSMakePoint(p4x, p4y))
        needle_path.lineToPoint_(NSMakePoint(p3x, p3y))
        needle_path.lineToPoint_(NSMakePoint(p2x, p2y))
        needle_path.closePath()

        color("#F0C9B4").set()
        needle_path.fill()

        # Subtle outline
        color("#F0C9B4", 0.5).set()
        needle_path.setLineWidth_(1.5)
        needle_path.stroke()

        # ------------------------------------------------------------------ #
        # 5. Center hub                                                        #
        # ------------------------------------------------------------------ #
        hub_rect = NSMakeRect(
            arc_center_x - hub_radius,
            arc_center_y - hub_radius,
            hub_radius * 2,
            hub_radius * 2,
        )
        hub_path = AppKit.NSBezierPath.bezierPathWithOvalInRect_(hub_rect)
        color("#D7875F").set()
        hub_path.fill()

        # Hub highlight ring
        color("#F0C9B4", 0.35).set()
        hub_path.setLineWidth_(4.0)
        hub_path.stroke()

    finally:
        image.unlockFocus()

    return image


def save_png(image: AppKit.NSImage, out_path: str) -> None:
    tiff_data = image.TIFFRepresentation()
    bitmap = AppKit.NSBitmapImageRep.imageRepWithData_(tiff_data)
    png_data = bitmap.representationUsingType_properties_(
        AppKit.NSBitmapImageFileTypePNG, {}
    )
    png_data.writeToFile_atomically_(out_path, True)


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, "icon_1024.png")

    print("Drawing GhostGauge icon…")
    img = draw_icon(1024)
    save_png(img, out_path)
    size = os.path.getsize(out_path)
    print(f"Saved: {out_path} ({size:,} bytes)")
