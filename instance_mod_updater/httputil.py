from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, TypeVar

from .progress import ProgressBar, announce_transfer

DEFAULT_UA = "instance-mod-updater/0.1.1 (+https://github.com/TruthDecodes/instance-mod-updater)"

# Only show a progress bar for transfers at least this large
PROGRESS_MIN_BYTES = 256 * 1024

T = TypeVar("T")
R = TypeVar("R")


class RateLimiter:
    """Thread-safe minimum spacing between API calls (shared across workers)."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait_for = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.min_interval
        if wait_for > 0:
            time.sleep(wait_for)


# Shared limiters: polite defaults; 429 paths still back off harder.
MODRINTH_LIMITER = RateLimiter(0.05)
CURSEFORGE_LIMITER = RateLimiter(0.08)


def map_parallel(
    items: list[T],
    fn: Callable[[T], R],
    *,
    max_workers: int = 8,
    on_progress: Callable[[int, int, T], None] | None = None,
) -> list[R | BaseException]:
    """
    Run fn over items with a thread pool. Returns results in input order.
    Exceptions are returned as values (not raised) so callers keep thoroughness.
    """
    if not items:
        return []
    workers = max(1, min(max_workers, len(items)))
    results: list[R | BaseException | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, item): i for i, item in enumerate(items)}
        done = 0
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = fut.result()
            except BaseException as e:  # noqa: BLE001 — surface to caller per item
                results[i] = e
            done += 1
            if on_progress:
                on_progress(done, len(items), items[i])
    return [r if r is not None else RuntimeError("missing result") for r in results]


def get_json(
    url: str,
    *,
    ua: str = DEFAULT_UA,
    timeout: float = 60,
    retries: int = 3,
    label: str | None = None,
    headers: dict[str, str] | None = None,
) -> Any | None:
    last_err: Exception | None = None
    for attempt in range(retries):
        hdrs = {"User-Agent": ua, "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = _read_body(resp, label=label or "download", show=True)
                return json.loads(raw.decode())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404:
                return None
            if e.code == 429:
                time.sleep(2.5 * (attempt + 1))
                continue
            if attempt + 1 < retries and e.code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None
        except Exception as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    if last_err:
        raise last_err
    return None


def post_json(
    url: str,
    body: Any,
    *,
    ua: str = DEFAULT_UA,
    timeout: float = 60,
    headers: dict[str, str] | None = None,
) -> Any | None:
    data = json.dumps(body).encode()
    hdrs = {
        "User-Agent": ua,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers=hdrs,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # batch responses are small; no progress bar
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(2.5)
            return post_json(url, body, ua=ua, timeout=timeout, headers=headers)
        return None


def _content_length(resp) -> int | None:
    cl = resp.headers.get("Content-Length") if hasattr(resp, "headers") else None
    if cl is None:
        return None
    try:
        n = int(cl)
        return n if n > 0 else None
    except ValueError:
        return None


def _should_show_progress(total: int | None) -> bool:
    return total is not None and total >= PROGRESS_MIN_BYTES


def _read_body(resp, *, label: str, show: bool = True) -> bytes:
    total = _content_length(resp)
    use_bar = show and _should_show_progress(total)
    if not use_bar:
        return resp.read()
    bar = ProgressBar(label=label, total=total)
    chunks: list[bytes] = []
    try:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            bar.update(len(chunk))
        bar.finish(True)
    except Exception:
        bar.finish(False)
        raise
    return b"".join(chunks)


def download(
    url: str,
    dest_path: str,
    *,
    ua: str = DEFAULT_UA,
    timeout: float = 300,
    label: str | None = None,
    show_progress: bool = True,
) -> int:
    """Download URL to dest_path. Live bar for large files; every jar gets a result line."""
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    name = label or os.path.basename(dest_path) or "download"
    size = 0
    bar: ProgressBar | None = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest_path, "wb") as f:
            total = _content_length(resp)
            if show_progress and (total is None or total >= PROGRESS_MIN_BYTES):
                # unknown size: still show running byte count for jar downloads
                bar = ProgressBar(label=name, total=total)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
                if bar:
                    bar.update(len(chunk))
        if bar:
            bar.finish(True)
        elif show_progress:
            announce_transfer(name, size, ok=True)
    except Exception:
        if bar:
            bar.finish(False)
        elif show_progress:
            announce_transfer(name, size, ok=False)
        raise
    return size


def get_text(url: str, *, ua: str = DEFAULT_UA, timeout: float = 60) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
