import os
import sys
from collections import deque

_BANNER_DEFAULT = r"""
__     ____            _              __ _
\ \   / ___|_       _ (_)_ __   __ _ / _| |_
 \ \  \___  \ \ /\ / /| | '_ \ / _` | |_| __|
 / /   ___) |\ V  V / | | | | | (_) |  _| |_
/_/___|____/  \_/\_/  |_|_| |_|\__, |_|  \__|
 |_____|                       |___/
"""

def _term_width(default: int = 80) -> int:
    try:
        import shutil as _shutil
        size = _shutil.get_terminal_size((default, 24))
        return max(20, int(size.columns))
    except Exception:
        return default

def progress_bar(completed: int, total: int, width: int = 30) -> str:
    completed = max(0, min(completed, total))
    total = max(1, total)
    filled = int(width * completed / total)
    bar = "#" * filled + "-" * (width - filled)
    pct = int(100 * completed / total)
    return f"[{bar}] {completed}/{total} ({pct}%)"

class TUI:
    """
    Minimal TUI with modes:
      - single: one status line rewritten in place
      - panel: primary status + tail area of N lines
      - portable: no ANSI, just newlines
      - ultra: simplified full redraw avoidance
    Environment variables:
      SWINGFT_TUI_MODE=single|panel
      SWINGFT_TUI_PANEL_LINES=N
      SWINGFT_TUI_PORTABLE=1
      SWINGFT_TUI_FORCE_TTY=1
      SWINGFT_TUI_ULTRA=1|0
      SWINGFT_TUI_ECHO=1 (used by callers to echo raw logs)
    """
    def __init__(self, banner: str | None = None):
        self.banner = banner or _BANNER_DEFAULT
        # stdout buffering hint
        try:
            sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._force_tty = (os.environ.get("SWINGFT_TUI_FORCE_TTY", "") == "1")
        self._portable = (os.environ.get("SWINGFT_TUI_PORTABLE", "") == "1") or (not sys.stdout.isatty())
        if self._force_tty:
            self._portable = False
        ultra_env = os.environ.get("SWINGFT_TUI_ULTRA", "")
        self._ultra = (ultra_env == "1")
        if ultra_env == "0":
            self._ultra = False
        self._mode = os.environ.get("SWINGFT_TUI_MODE", "single").strip().lower()
        self._single = (self._mode == "single")
        self._panel = (self._mode == "panel")
        self._panel_lines = int(os.environ.get("SWINGFT_TUI_PANEL_LINES", "10"))
        self._last_width = 0

    # public API
    def print_banner(self):
        print(self.banner)

    def init(self):
        if self._single:
            sys.stdout.write("\n"); sys.stdout.flush(); return
        if self._panel:
            sys.stdout.write("\n")
            sys.stdout.write("\x1b[s")
            sys.stdout.write("\x1b[2K\n")
            for _ in range(self._panel_lines):
                sys.stdout.write("\x1b[2K\n")
            sys.stdout.flush(); return
        if self._portable:
            sys.stdout.write("\n\n"); sys.stdout.flush(); return
        sys.stdout.write("\n\n"); sys.stdout.write("\x1b[s"); sys.stdout.flush()

    def set_status(self, lines):
        if not isinstance(lines, (list, tuple)): lines = [str(lines)]
        if self._panel:
            segs = [str(ln) for ln in lines if str(ln).strip()]
            primary = segs[0] if segs else ""
            tail = segs[1:1 + self._panel_lines]

            # move to saved cursor and clear the area below to remove previous logs
            try:
                sys.stdout.write("\x1b[u")
                sys.stdout.write("\x1b[J")
            except Exception:
                pass

            # header output (fit to width)
            width = _term_width()
            out = primary[:width - 1]
            sys.stdout.write("\x1b[2K" + out + "\n")

            # overwrite exactly panel_lines lines (empty lines included)
            for i in range(self._panel_lines):
                ln = tail[i] if i < len(tail) else ""
                sys.stdout.write("\x1b[2K" + ln + "\n")

            sys.stdout.flush()
            self._last_width = len(out)
            return
        if self._single or self._ultra or self._portable:
            segs = [str(ln) for ln in lines if str(ln).strip()]
            if len(segs) > 2: segs = segs[:2]
            msg = " | ".join(segs).strip()
            width = _term_width()
            out = msg[:width - 1]
            sys.stdout.write("\r\x1b[2K" + out)
            sys.stdout.flush()
            self._last_width = len(out)
            return
        # advanced saved-cursor mode
        sys.stdout.write("\x1b[u\x1b[J")
        for ln in lines:
            sys.stdout.write(str(ln) + "\n")
        sys.stdout.flush()

    # raw writer to avoid recursion when stdout is temporarily redirected
    def _set_status_raw(self, lines):
        out_stream = sys.__stdout__
        if not isinstance(lines, (list, tuple)):
            lines = [str(lines)]
        if self._panel:
            segs = [str(ln) for ln in lines if str(ln).strip()]
            primary = segs[0] if segs else ""
            tail = segs[1:1 + self._panel_lines]
            try:
                out_stream.write("\x1b[u")
                out_stream.write("\x1b[J")
            except Exception:
                pass
            width = _term_width()
            out = primary[:width - 1]
            out_stream.write("\x1b[2K" + out + "\n")
            for i in range(self._panel_lines):
                ln = tail[i] if i < len(tail) else ""
                out_stream.write("\x1b[2K" + ln + "\n")
            try:
                out_stream.flush()
            except Exception:
                pass
            self._last_width = len(out)
            return
        if self._single or self._ultra or self._portable:
            segs = [str(ln) for ln in lines if str(ln).strip()]
            if len(segs) > 2:
                segs = segs[:2]
            msg = " | ".join(segs).strip()
            width = _term_width()
            out = msg[:width - 1]
            out_stream.write("\r\x1b[2K" + out)
            try:
                out_stream.flush()
            except Exception:
                pass
            self._last_width = len(out)
            return
        out_stream.write("\x1b[u\x1b[J")
        for ln in lines:
            out_stream.write(str(ln) + "\n")
        try:
            out_stream.flush()
        except Exception:
            pass

    def redraw_full(self, lines):
        if not isinstance(lines, (list, tuple)): lines = [str(lines)]
        if self._single or self._panel:
            self.set_status(lines); return
        sys.stdout.write("\r")
        if self._ultra:
            sys.stdout.write("\r\n")
            self.print_banner()
            if lines:
                sys.stdout.write("\n"); sys.stdout.flush()
                self.set_status([lines[0]])
            return
        sys.stdout.write("\x1b[H\x1b[2J")
        sys.stdout.write(self.banner + "\n")
        for ln in lines: sys.stdout.write(str(ln) + "\n")
        if not self._portable:
            sys.stdout.write("\n\n\x1b[s")
        sys.stdout.flush()

    def show_exact_screen(self, lines):
        """
        Print the provided lines exactly. For panel mode treat first line as header and rest as tail.
        """
        if not isinstance(lines, (list, tuple)):
            lines = [str(lines)]
        if self._panel:
            primary = lines[0] if lines else ""
            tail = lines[1:1 + self._panel_lines]
            try:
                sys.stdout.write("\x1b[u")
                sys.stdout.write("\x1b[J")
            except Exception:
                pass
            width = _term_width()
            out = primary[:width - 1]
            sys.stdout.write("\x1b[2K" + out + "\n")
            for i in range(self._panel_lines):
                ln = tail[i] if i < len(tail) else ""
                sys.stdout.write("\x1b[2K" + ln + "\n")
            sys.stdout.flush()
            return
        # fallback to redraw_full for other modes
        self.redraw_full(lines)

    def show_sequence(self, screens, pause_fn=None):
        """
        Show a sequence of screens. Each screen may be a list of lines or a tuple(name, lines).
        pause_fn, if provided, is called between screens (e.g., lambda: input('Enter')).
        """
        for s in screens:
            if isinstance(s, (list, tuple)) and not (isinstance(s, tuple) and len(s) >= 2 and not isinstance(s[0], str)):
                # list of lines
                lines = s
            elif isinstance(s, tuple) and len(s) >= 2:
                lines = s[1]
            else:
                lines = [str(s)]
            self.show_exact_screen(lines)
            if pause_fn:
                try:
                    pause_fn()
                except Exception:
                    pass

    def prompt_line(self, prompt: str) -> str:
        if self._panel:
            try:
                sys.stdout.write("\x1b[u\x1b[s")
                move = max(1, self._panel_lines)
                sys.stdout.write(f"\x1b[{move}B\r\x1b[2K"); sys.stdout.flush()
                ans = input(str(prompt))
            except Exception:
                ans = ""
            try:
                sys.stdout.write("\r\x1b[u"); sys.stdout.write("\x1b[2K\n")
                for _ in range(self._panel_lines): sys.stdout.write("\x1b[2K\n")
                sys.stdout.write("\x1b[u"); sys.stdout.flush()
            except Exception:
                pass
            try:
                sys.stdout.write("\r\x1b[2K\x1b[u"); sys.stdout.flush()
            except Exception:
                pass
            return ans
        if self._single:
            try: ans = input("\r" + str(prompt))
            except Exception: ans = ""
            try: sys.stdout.write("\r\x1b[2K"); sys.stdout.flush()
            except Exception: pass
            return ans
        if self._portable:
            try: ans = input(str(prompt))
            except Exception: ans = ""
            self.redraw_full([""])
            return ans
        if self._ultra:
            try: ans = input("\r" + str(prompt))
            except Exception: ans = ""
            try:
                width = _term_width()
                sys.stdout.write("\r" + (" " * width) + "\r"); sys.stdout.flush()
            except Exception: pass
            return ans
        try:
            sys.stdout.write("\x1b[u\x1b[B\r\x1b[2K"); sys.stdout.flush()
            ans = input(str(prompt))
        except Exception:
            ans = ""
        try:
            sys.stdout.write("\r\x1b[2K\x1b[u"); sys.stdout.flush()
        except Exception:
            pass
        return ans

    # optional helper for tailing streams if callers want it
    class StreamEcho:
        def __init__(self, set_status_cb, header: str = "", tail_len: int = 10):
            self._set = set_status_cb
            self._header = header
            self._buf = ""
            self._tail = deque(maxlen=tail_len)

        def write(self, s: str):
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self._tail.append(line)
                self._set([self._header, *list(self._tail)])

        def flush(self):
            if self._buf:
                line, self._buf = self._buf, ""
                if line.strip():
                    self._tail.append(line)
            self._set([self._header, *list(self._tail)])

    def make_stream_echo(self, header: str = "", tail_len: int = 10):
        # use raw setter to avoid recursion when stdout is redirected into echo stream
        return TUI.StreamEcho(self._set_status_raw, header=header, tail_len=tail_len)