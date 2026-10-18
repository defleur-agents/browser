#!/usr/bin/env python3
"""Patch stock noVNC 1.3.0 touch taps to use paced native RFB clicks (from tailnet-browser)."""

from __future__ import annotations

import sys
from pathlib import Path

STOCK_THRESHOLDS = """const DOUBLE_TAP_TIMEOUT = 1000;
const DOUBLE_TAP_THRESHOLD = 50;"""
PATCHED_THRESHOLDS = """// Tailnet Browser: never snap a new phone tap to an earlier target.
const DOUBLE_TAP_TIMEOUT = 0;
const DOUBLE_TAP_THRESHOLD = 0;"""

STOCK_DISPATCH = """        this._fakeMouseMove(this._gestureFirstDoubleTapEv, pos.x, pos.y);
        this._handleMouseButton(pos.x, pos.y, true, bmask);
        this._handleMouseButton(pos.x, pos.y, false, bmask);"""
PATCHED_DISPATCH = """        // Snapshot this gesture before a queued earlier tap finishes.
        const tap = {
            x: pos.x,
            y: pos.y,
            cursorX: ev.detail.clientX,
            cursorY: ev.detail.clientY,
            bmask,
        };
        const nativeTap = async () => {
            let pressed = false;
            try {
                this._handleMouseMove(tap.x, tap.y);
                this._cursor.move(tap.cursorX, tap.cursorY);
                pressed = true;
                this._handleMouseButton(tap.x, tap.y, true, tap.bmask);
                // A real press duration prevents remote X11 clients and challenge
                // widgets from coalescing a burst of down/up packets.
                await new Promise((resolve) => setTimeout(resolve, 80));
            } finally {
                if (pressed) {
                    this._handleMouseButton(tap.x, tap.y, false, tap.bmask);
                }
            }
            await new Promise((resolve) => setTimeout(resolve, 45));
        };

        // Serialize taps through the actual RFB/X11 mouse path. This keeps the
        // input equivalent to a physical mouse and preserves every target when
        // the user taps faster than the remote browser can drain.
        this._tailnetTapQueue = (this._tailnetTapQueue || Promise.resolve())
            .then(nativeTap, nativeTap);"""


def patch_rfb_taps(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if PATCHED_THRESHOLDS in text and PATCHED_DISPATCH in text:
        return False
    if STOCK_THRESHOLDS not in text:
        raise RuntimeError("Expected stock noVNC tap thresholds were not found")
    if STOCK_DISPATCH not in text:
        raise RuntimeError("Expected stock noVNC tap dispatch was not found")
    text = text.replace(STOCK_THRESHOLDS, PATCHED_THRESHOLDS, 1)
    text = text.replace(STOCK_DISPATCH, PATCHED_DISPATCH, 1)
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} /path/to/core/rfb.js", file=sys.stderr)
        return 2
    changed = patch_rfb_taps(Path(sys.argv[1]))
    print("patched" if changed else "already-patched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
