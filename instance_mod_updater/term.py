"""Minimal ANSI terminal colors for Windows + other VT terminals.

Stdlib only. On 64-bit Windows, console handles must use ctypes ``wintypes``;
default ctypes ``c_int`` restypes truncate HANDLEs and SetConsoleMode silently
fails, which previously left color permanently off under ``run.cmd``.
"""

from __future__ import annotations

import os
import sys

# SGR codes (reset always after each paint so partial lines stay safe).
# Use bright foreground (9x) — on dark PowerShell/Windows Terminal themes,
# bold alone looks like normal white; dim is the only style that "shows".
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_MAGENTA = "\033[95m"
_BLUE = "\033[94m"

_enabled: bool | None = None
_vt_ready: bool = False
# auto | always | never — set via init(color=...) or env
_pref: str = "auto"


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name)
    if v is None:
        return False
    return v.strip().lower() not in ("", "0", "false", "no", "off")


def _is_tty() -> bool:
    try:
        return bool(sys.stdout.isatty() or sys.stderr.isatty())
    except Exception:
        return False


def _looks_like_color_host() -> bool:
    """Env hints that the host already understands ANSI (even if VT toggle fails)."""
    if os.environ.get("WT_SESSION"):  # Windows Terminal
        return True
    if os.environ.get("WT_PROFILE_ID"):
        return True
    if _env_truthy("ANSICON") or os.environ.get("ConEmuANSI") == "ON":
        return True
    term = (os.environ.get("TERM") or "").lower()
    if term and term not in ("dumb", "unknown"):
        return True
    # VS Code / Cursor integrated terminal
    if os.environ.get("TERM_PROGRAM") in ("vscode", "cursor"):
        return True
    return False


def _enable_windows_vt() -> bool:
    """Turn on ENABLE_VIRTUAL_TERMINAL_PROCESSING for stdout and stderr (Win10+)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # Correct prototypes — required on 64-bit Windows (HANDLE is pointer-sized)
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetConsoleMode.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetConsoleMode.restype = wintypes.BOOL

        # MSDN: STD_OUTPUT_HANDLE = (DWORD)-11, STD_ERROR_HANDLE = (DWORD)-12
        STD_OUTPUT_HANDLE = wintypes.DWORD(-11).value
        STD_ERROR_HANDLE = wintypes.DWORD(-12).value
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        INVALID = wintypes.HANDLE(-1).value

        ok_any = False
        for hid in (STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
            h = kernel32.GetStdHandle(hid)
            if not h or h == INVALID:
                continue
            mode = wintypes.DWORD()
            if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                continue
            new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            if new_mode == mode.value:
                # Already on
                ok_any = True
                continue
            if kernel32.SetConsoleMode(h, new_mode):
                ok_any = True
        return ok_any
    except Exception:
        return False


def init(*, color: str | None = None) -> bool:
    """Detect/enable color. Call from CLI main before printing.

    color: 'auto' | 'always' | 'never' (None keeps prior pref / env / auto).
    Safe to call more than once; recomputes when color= is passed.
    """
    global _enabled, _vt_ready, _pref

    if color is not None:
        c = color.strip().lower()
        if c not in ("auto", "always", "never"):
            c = "auto"
        _pref = c
        _enabled = None  # recompute

    if _enabled is not None:
        return _enabled

    # Explicit off
    if _pref == "never" or "NO_COLOR" in os.environ:
        _enabled = False
        return False

    force = (
        _pref == "always"
        or _env_truthy("FORCE_COLOR")
        or _env_truthy("CLICOLOR_FORCE")
    )
    tty = _is_tty()
    host = _looks_like_color_host()

    if not force and not tty and not host:
        _enabled = False
        return False

    if sys.platform == "win32":
        _vt_ready = _enable_windows_vt()
        # Emit ANSI if VT is on, user forced color, or host is known-good.
        # (Previously we required VT success; failed ctypes HANDLE setup made
        # every run.cmd session colorless.)
        if not (_vt_ready or force or host or tty):
            _enabled = False
            return False
        # TTY on modern Windows: emit ANSI even if SetConsoleMode returned
        # false once — Windows Terminal and recent conhost often already
        # interpret CSI sequences for the attached console.
        _enabled = True
    else:
        _vt_ready = True
        _enabled = True

    return True


def enabled() -> bool:
    if _enabled is None:
        return init()
    return _enabled


def paint(text: str, *codes: str) -> str:
    if not text or not enabled() or not codes:
        return text
    return f"{''.join(codes)}{text}{_RESET}"


def bold(text: str) -> str:
    return paint(text, _BOLD)


def dim(text: str) -> str:
    return paint(text, _DIM)


def red(text: str) -> str:
    return paint(text, _RED)


def green(text: str) -> str:
    return paint(text, _GREEN)


def yellow(text: str) -> str:
    return paint(text, _YELLOW)


def cyan(text: str) -> str:
    return paint(text, _CYAN)


def magenta(text: str) -> str:
    return paint(text, _MAGENTA)


def blue(text: str) -> str:
    return paint(text, _BLUE)


def ok(text: str = "OK") -> str:
    return green(text)


def fail(text: str = "FAIL") -> str:
    return red(text)


def warn(text: str) -> str:
    return yellow(text)


def section(title: str) -> str:
    """Phase header, e.g. '=== check: foo ==='."""
    return paint(title, _BOLD, _CYAN)


def label(key: str, value: str) -> str:
    """key=value with a muted key and normal value (compact field line)."""
    return f"{dim(key + '=')}{value}"


def blank() -> None:
    """One blank line on stdout (spacing between phases)."""
    print(flush=True)


def _color_option_tokens(left: str) -> str:
    """Color flags green and {choice,lists} yellow inside an option synopsis."""
    import re

    parts: list[str] = []
    # tokens: {…}, --flags, -x, bare words, punctuation/spaces
    for tok in re.findall(r"\{[^}]*\}|-\S+|[^\s{}-]+|\s+|.", left):
        if tok.startswith("{") and tok.endswith("}"):
            parts.append(yellow(tok))
        elif tok.startswith("-"):
            parts.append(green(tok))
        else:
            parts.append(tok)
    return "".join(parts)


def colorize_help(text: str) -> str:
    """Tint stock argparse help enough to read on a dark console."""
    if not text or not enabled():
        return text
    import re

    out: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        nl = line[len(body) :]
        if body.startswith("usage:"):
            # Color choice sets and option tokens only (not hyphens inside the prog name)
            usage = body
            usage = re.sub(
                r"\{[^}]+\}",
                lambda m: yellow(m.group(0)),
                usage,
            )
            usage = re.sub(
                r"(?<=[\s\[])(--?[\w-]+)",
                lambda m: green(m.group(1)),
                usage,
            )
            if usage.startswith("usage:"):
                usage = cyan("usage:") + usage[len("usage:") :]
            out.append(usage + nl)
            continue
        # Section headers: "options:", "positional arguments:"
        if body and not body.startswith(" ") and body.endswith(":"):
            out.append(cyan(body) + nl)
            continue
        # Usage wrap: "                            {list,check,...} ..."
        if re.match(r"^\s{4,}\{[^}]+\}", body):
            m = re.match(r"^(\s+)(\{[^}]+\})(.*)$", body)
            if m:
                out.append(m.group(1) + yellow(m.group(2)) + m.group(3) + nl)
                continue
        # Option rows (help may wrap onto next line alone)
        #   --color {auto,always,never}
        #                         ANSI colors: ...
        if re.match(r"^\s+-", body):
            m = re.match(r"^(\s+)(.+?)(\s{2,})(.*)$", body)
            if m:
                out.append(
                    m.group(1)
                    + _color_option_tokens(m.group(2))
                    + m.group(3)
                    + dim(m.group(4))
                    + nl
                )
            else:
                # synopsis-only line (no help text on this row)
                m2 = re.match(r"^(\s+)(.+)$", body)
                if m2:
                    out.append(m2.group(1) + _color_option_tokens(m2.group(2)) + nl)
                else:
                    out.append(line)
            continue
        # Wrapped help text under an option (deep indent, no leading -)
        if re.match(r"^\s{10,}\S", body) and not body.lstrip().startswith("-"):
            out.append(dim(body) + nl)
            continue
        # Subcommand rows: "    list   List FTB ..." or "  {list,check,...}"
        m = re.match(r"^(\s{2,})(\{[^}]+\}|\S+)(\s{2,})(.*)$", body)
        if m and not body.lstrip().startswith("-"):
            name = m.group(2)
            name_c = yellow(name) if name.startswith("{") else yellow(name)
            out.append(m.group(1) + name_c + m.group(3) + m.group(4) + nl)
            continue
        if re.match(r"^\s{2,}\{[^}]+\}\s*$", body):
            m = re.match(r"^(\s+)(.+)$", body)
            if m:
                out.append(m.group(1) + yellow(m.group(2)) + nl)
                continue
        out.append(line)
    return "".join(out)


def banner_line(key: str, value: str) -> str:
    """Launcher-style 'Key:  value' line."""
    return f"{cyan(key + ':')}  {value}"
