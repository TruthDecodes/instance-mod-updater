from __future__ import annotations

import re
import sys
import time
from typing import Callable

from . import term


def format_bytes(n: int | float | None) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024.0)):
        if abs(n) >= div:
            return f"{n / div:.1f} {unit}"
    return f"{int(n)} B"


def format_rate(bps: float) -> str:
    if bps <= 0:
        return "-"
    return f"{format_bytes(bps)}/s"


def _clear_line() -> None:
    # Erase from cursor to end of line (works in Windows Terminal / modern conhost)
    sys.stderr.write("\033[K")


class LineProgress:
    """Single-line status on stderr (overwrites itself)."""

    def __init__(self) -> None:
        self._active = False

    def set(self, text: str) -> None:
        # cap plain length; style after so we do not cut mid-escape
        plain = text
        if len(plain) > 130:
            plain = plain[:127] + "..."
        text = style_log_line(plain)
        sys.stderr.write("\r" + text)
        _clear_line()
        sys.stderr.flush()
        self._active = True

    def park(self) -> None:
        """Erase the live status line so a durable message can follow it."""
        if not self._active:
            return
        sys.stderr.write("\r")
        _clear_line()
        sys.stderr.flush()
        self._active = False

    def end(self, final: str | None = None) -> None:
        if final is not None:
            sys.stderr.write("\r" + style_log_line(final))
            _clear_line()
            sys.stderr.write("\n")
        elif self._active:
            sys.stderr.write("\n")
        sys.stderr.flush()
        self._active = False


class ProgressBar:
    """Single-line download progress: label, bytes, %, rate. Only for real transfers."""

    def __init__(self, label: str = "", total: int | None = None) -> None:
        self.label = (label or "download")[:48]
        self.total = total if total and total > 0 else None
        self.done = 0
        self.t0 = time.monotonic()
        self._last_print = 0.0
        self._finished = False

    def update(self, n: int = 0, *, absolute: int | None = None) -> None:
        if absolute is not None:
            self.done = absolute
        else:
            self.done += n
        now = time.monotonic()
        if not self._finished and (now - self._last_print) < 0.12 and (
            self.total is None or self.done < (self.total or 0)
        ):
            return
        self._last_print = now
        self._draw()

    def _draw(self) -> None:
        elapsed = max(time.monotonic() - self.t0, 1e-6)
        rate = self.done / elapsed
        label = term.dim(f"DL {self.label}")
        if self.total:
            pct = min(100.0, 100.0 * self.done / self.total)
            bar = (
                f"  {label}: {format_bytes(self.done)}/{format_bytes(self.total)} "
                f"{pct:5.1f}%  {format_rate(rate)}"
            )
        else:
            bar = f"  {label}: {format_bytes(self.done)}  {format_rate(rate)}"
        sys.stderr.write("\r" + bar)
        _clear_line()
        sys.stderr.flush()

    def finish(self, ok: bool = True) -> None:
        if self._finished:
            return
        self._finished = True
        elapsed = max(time.monotonic() - self.t0, 1e-6)
        rate = self.done / elapsed
        status = term.ok("OK") if ok else term.fail("FAIL")
        label = term.dim(f"DL {self.label}")
        if self.total:
            line = (
                f"  {label}: {format_bytes(self.done)}/{format_bytes(self.total)} "
                f"100%  avg {format_rate(rate)}  [{status}]"
            )
        else:
            line = (
                f"  {label}: {format_bytes(self.done)}  "
                f"avg {format_rate(rate)}  [{status}]"
            )
        sys.stderr.write("\r" + line)
        _clear_line()
        sys.stderr.write("\n")
        sys.stderr.flush()


def announce_transfer(
    label: str,
    size: int | float | None,
    *,
    ok: bool = True,
    cached: bool = False,
) -> None:
    """One committed stderr line for every jar transfer (including tiny files)."""
    status = term.ok("OK") if ok else term.fail("FAIL")
    kind = "cached" if cached else "DL"
    prefix = term.dim(f"{kind} {label}")
    line = f"  {prefix}: {format_bytes(size)}  [{status}]"
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


LogFn = Callable[[str], None]


_COUNT_KEYS = (
    "updates",
    "downloaded",
    "cached",
    "current",
    "pack_only",
    "no_source",
    "errors",
    "upd",
    "dl",
    "ok",
    "miss",
    "err",
    "failed",
    "applied",
    "skipped",
)


def _style_counts(msg: str) -> str:
    """Color key=N tokens (non-zero hot; zeros stay plain)."""
    if not term.enabled():
        return msg

    def repl(m: re.Match[str]) -> str:
        key, val = m.group(1), m.group(2)
        try:
            n = int(val)
        except ValueError:
            return m.group(0)
        if n <= 0:
            return term.dim(f"{key}={val}")
        hot = {
            "updates": term.cyan,
            "upd": term.cyan,
            "downloaded": term.magenta,
            "dl": term.magenta,
            "cached": term.cyan,
            "current": term.green,
            "ok": term.green,
            "pack_only": term.yellow,
            "no_source": term.yellow,
            "miss": term.yellow,
            "errors": term.red,
            "err": term.red,
            "failed": term.red,
            "applied": term.green,
            "skipped": term.yellow,
        }.get(key)
        return hot(f"{key}={val}") if hot else f"{key}={val}"

    keys = "|".join(_COUNT_KEYS)
    return re.sub(rf"\b({keys})=(\d+)", repl, msg)


def _style_ratio(msg: str) -> str:
    """Tint N/M style ratios (e.g. 206/309 known jars)."""
    if not term.enabled():
        return msg

    def repl(m: re.Match[str]) -> str:
        a, b = m.group(1), m.group(2)
        return f"{term.cyan(a)}/{term.dim(b)}"

    return re.sub(r"\b(\d+)/(\d+)\b", repl, msg)


def style_log_line(msg: str) -> str:
    """Status coloring for pipeline logs and progress end-lines (same wording)."""
    if not msg:
        return msg
    if not term.enabled():
        return msg

    s = msg.lstrip()
    # Outcome tags
    if s.startswith("DONE "):
        m = re.search(r"errors=(\d+)", s)
        base = term.yellow(msg) if (m and int(m.group(1)) > 0) else term.green(msg)
        return _style_counts(base) if "errors=" in s else base
    if s.startswith("OK ") or s.startswith("Already OK") or " already satisfies " in s:
        return term.green(msg)
    if s.startswith("FAIL ") or s.startswith("MISSING ") or s.startswith("ERROR"):
        return term.red(msg)
    if s.startswith("APPLY blocked") or s.startswith("Hint:"):
        return term.yellow(msg)
    if s.startswith("SKIP ") or s.startswith("Dry-run:"):
        return term.dim(msg)
    if s.startswith("APPLY done") or s.startswith("APPLY:"):
        colored = term.green(msg) if "failed=0" in s or "nothing" in s else (
            term.yellow(msg) if "failed=" in s else msg
        )
        return _style_counts(colored)
    if s.startswith("NeoForge upgrade:") or s.startswith("Downloading installer"):
        return term.cyan(msg)
    if s.startswith("Report:") or s.startswith("Manifest:") or s.startswith("Backup:"):
        return term.dim(msg)
    if s.startswith("Java:") or s.startswith("Installed profile:") or s.startswith(
        "Patched instance"
    ):
        return term.green(msg)

    # Check-phase chatter (user's long status block)
    if s.startswith("Modrinth:") or s.startswith("Modrinth "):
        return _style_ratio(term.cyan(msg))
    if s.startswith("CurseForge:") or s.startswith("CurseForge "):
        return _style_ratio(term.yellow(msg))
    if s.startswith("Fetching FTB pack") or s.startswith("Scanning mods"):
        # path after the verb stays readable: cyan whole line is fine
        return term.cyan(msg)
    if s.startswith("Cached pack to") or s.startswith("Loaded pack file"):
        return term.green(msg)
    if s.startswith("Scan done") or s.startswith("Check done"):
        body = term.green(msg)
        return _style_counts(_style_ratio(body))
    if s.startswith("Modrinth hashes") or s.startswith("Modrinth versions"):
        return _style_ratio(term.cyan(msg))
    if s.startswith("CurseForge files"):
        return _style_ratio(term.yellow(msg))
    if s.startswith("Scan [") or s.startswith("Check ["):
        return term.dim(msg)
    if s.startswith("No pack id") or "Modrinth-only" in s:
        return term.yellow(msg)

    # Generic key=value tails on otherwise plain lines
    if re.search(
        r"\b(updates|downloaded|cached|current|pack_only|no_source|errors)=\d+", s
    ):
        return _style_counts(msg)
    return msg


def log_line(msg: str, log: LogFn | None = None) -> None:
    if log:
        log(msg)
    else:
        print(style_log_line(msg), flush=True)
