from __future__ import annotations

import os
import re
import struct
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _release_mark
from . import httputil
from .versions import (
    exact_game_in_tags,
    filename_targets_other_mc,
    is_newer,
    version_in_maven_range,
)

# CF releaseType: 1=release, 2=beta, 3=alpha
RT_RELEASE, RT_BETA, RT_ALPHA = 1, 2, 3
UA = httputil.DEFAULT_UA
# Public HTTPS origin for Core-shaped ops. The published app does not send x-api-key.
PUBLISHER_ORIGIN = "https://truthimu.duckdns.org"
ENROLL_PATH = "/imu/enroll"
MIN_RELEASE_MARK_LEN = 32
MC_GAME_ID = 432
# Whitespace bytes CF strips before murmur2 fingerprinting
_CF_STRIP = {9, 10, 13, 32}
_NEOFORGE_LOADER_TYPE = 6
_PAGE_SIZE = 50
_INDEX_CAP = 10000

# allowModDistribution by project id; process memory only
_allow_mod_distribution: dict[str, Any] = {}
_allow_mod_lock = threading.Lock()
_publisher_token_lock = threading.Lock()
_publisher_token: str | None = None


def _pace() -> None:
    httputil.CURSEFORGE_LIMITER.wait()


def _core_origin(_api_key: str | None = None) -> str:
    return PUBLISHER_ORIGIN.rstrip("/")


def publisher_client_token_path() -> Path:
    """Machine-local token file. Not in the Release zip or the install root."""
    raw = (os.environ.get("IMU_PUBLISHER_CLIENT_TOKEN_FILE") or "").strip()
    if raw:
        return Path(raw)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "instance-mod-updater" / "publisher-client.token"
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "instance-mod-updater" / "publisher-client.token"


def _reset_publisher_token_cache() -> None:
    global _publisher_token
    with _publisher_token_lock:
        _publisher_token = None


def _read_stored_publisher_token() -> str | None:
    path = publisher_client_token_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    line = text.splitlines()[0].strip() if text.strip() else ""
    return line or None


def _write_publisher_token(token: str) -> None:
    path = publisher_client_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _publisher_mark() -> str | None:
    mark = str(getattr(_release_mark, "MARK", "") or "").strip()
    if len(mark) < MIN_RELEASE_MARK_LEN:
        return None
    return mark


def _enroll_publisher_token(origin: str) -> str | None:
    mark = _publisher_mark()
    if not mark:
        return None
    data = httputil.post_json(f"{origin.rstrip('/')}{ENROLL_PATH}", {"k": mark})
    if not isinstance(data, dict):
        return None
    token = str(data.get("token") or "").strip()
    return token or None


def _publisher_bearer(origin: str, *, force: bool = False) -> str | None:
    global _publisher_token
    with _publisher_token_lock:
        if not force and _publisher_token:
            return _publisher_token
        if not force:
            stored = _read_stored_publisher_token()
            if stored:
                _publisher_token = stored
                return stored
        token = _enroll_publisher_token(origin)
        if not token:
            _publisher_token = None
            return None
        _write_publisher_token(token)
        _publisher_token = token
        return token


def _request_headers(_api_key: str | None = None) -> dict[str, str] | None:
    token = _publisher_bearer(PUBLISHER_ORIGIN)
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def _cf_get_json(url: str, *, api_key: str | None = None) -> Any:
    headers = _request_headers(api_key)
    if not headers:
        return None
    try:
        return httputil.get_json(
            url, ua=UA, headers=headers, on_unauthorized="raise"
        )
    except httputil.HttpUnauthorized:
        _publisher_bearer(PUBLISHER_ORIGIN, force=True)
        headers = _request_headers()
        if not headers:
            return None
        try:
            return httputil.get_json(
                url, ua=UA, headers=headers, on_unauthorized="raise"
            )
        except httputil.HttpUnauthorized:
            return None


def _cf_post_json(url: str, body: Any, *, api_key: str | None = None) -> Any:
    headers = _request_headers(api_key)
    if not headers:
        return None
    try:
        return httputil.post_json(
            url, body, ua=UA, headers=headers, on_unauthorized="raise"
        )
    except httputil.HttpUnauthorized:
        _publisher_bearer(PUBLISHER_ORIGIN, force=True)
        headers = _request_headers()
        if not headers:
            return None
        try:
            return httputil.post_json(
                url, body, ua=UA, headers=headers, on_unauthorized="raise"
            )
        except httputil.HttpUnauthorized:
            return None


def resolve_api_key(explicit: str | None = None, **kwargs: Any) -> None:
    """Published app does not accept a local unique CurseForge key."""
    return None


def murmur2_cf(data: bytes) -> int:
    """
    CurseForge file fingerprint: strip whitespace, MurmurHash2 (32-bit, seed 1).

    Matches the fingerprint used by the official /v1/fingerprints API.
    """
    buf = bytes(b for b in data if b not in _CF_STRIP)
    length = len(buf)
    m = 0x5BD1E995
    r = 24
    h = (1 ^ length) & 0xFFFFFFFF
    i = 0
    while length >= 4:
        k = struct.unpack_from("<I", buf, i)[0]
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
        i += 4
        length -= 4
    if length == 3:
        h ^= buf[i + 2] << 16
    if length >= 2:
        h ^= buf[i + 1] << 8
    if length >= 1:
        h ^= buf[i]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h & 0xFFFFFFFF


def fingerprint_file(path: Path | str) -> int:
    """Compute CF murmur fingerprint of a local jar."""
    return murmur2_cf(Path(path).read_bytes())


def fingerprint_lookup(
    fingerprints: list[int],
    *,
    api_key: str | None = None,
    game_id: int = MC_GAME_ID,
) -> dict[int, dict]:
    """
    Official fingerprint match: POST /v1/fingerprints/{gameId}.

    Returns map fingerprint -> match row (includes file.modId, file.id, …).
    No search endpoints. Publisher origin only.
    """
    fps = [int(f) & 0xFFFFFFFF for f in fingerprints if f is not None]
    if not fps:
        return {}
    key = resolve_api_key(api_key)
    origin = _core_origin()
    uniq = sorted(set(fps))
    _pace()
    data = _cf_post_json(
        f"{origin}/v1/fingerprints/{game_id}",
        {"fingerprints": uniq},
        api_key=key,
    )
    if not data:
        # Fallback without game id (same body)
        _pace()
        data = _cf_post_json(
            f"{origin}/v1/fingerprints",
            {"fingerprints": uniq},
            api_key=key,
        )
    if not data or not isinstance(data, dict):
        return {}
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    out: dict[int, dict] = {}
    for row in (payload or {}).get("exactMatches") or []:
        if not isinstance(row, dict):
            continue
        fp = row.get("file") or {}
        raw_fp = fp.get("fileFingerprint")
        if raw_fp is None:
            raw_fp = row.get("id")
        try:
            key = int(raw_fp) & 0xFFFFFFFF
        except (TypeError, ValueError):
            continue
        out[key] = row
    return out


def match_to_project_file(match: dict | None) -> tuple[str, int] | None:
    """Extract (project_id, file_id) from a fingerprint match row."""
    if not match:
        return None
    f = match.get("file") or {}
    mod_id = f.get("modId")
    file_id = f.get("id")
    if mod_id is None or file_id is None:
        return None
    return str(mod_id), int(file_id)


def _normalize_file_dates(f: dict) -> dict:
    if not f.get("dateCreated") and f.get("fileDate"):
        f["dateCreated"] = f["fileDate"]
    return f


def _payload_data(body: Any) -> Any:
    if isinstance(body, dict) and "data" in body:
        return body.get("data")
    return body


def list_cf_files_official(
    project_id: str,
    game: str,
    *,
    api_key: str | None = None,
    loader: str | None = None,
    max_pages: int = 5,
) -> list[dict]:
    """GET /v1/mods/{modId}/files via the publisher origin."""
    key = resolve_api_key(api_key)
    origin = _core_origin()
    out: list[dict] = []
    index = 0
    page_size = _PAGE_SIZE
    for _ in range(max_pages):
        if index + page_size > _INDEX_CAP:
            break
        q: dict[str, str] = {
            "gameVersion": game,
            "index": str(index),
            "pageSize": str(page_size),
        }
        if loader and str(loader).lower() == "neoforge":
            q["modLoaderType"] = str(_NEOFORGE_LOADER_TYPE)
        url = f"{origin}/v1/mods/{project_id}/files?{urllib.parse.urlencode(q)}"
        _pace()
        data = _cf_get_json(url, api_key=key)
        if not data:
            break
        chunk = _payload_data(data)
        if not chunk:
            break
        for row in chunk:
            if isinstance(row, dict):
                out.append(_normalize_file_dates(row))
        pag = data.get("pagination") or {} if isinstance(data, dict) else {}
        total = pag.get("totalCount") or len(out)
        index += page_size
        if index >= total or len(chunk) < page_size:
            break
    return out


def list_cf_files(
    project_id: str,
    game: str,
    *,
    loader: str | None = None,
    max_pages: int = 5,
) -> list[dict]:
    """Official Core file list via the publisher origin."""
    return list_cf_files_official(
        project_id,
        game,
        loader=loader,
        max_pages=max_pages,
    )


def prefetch_files(
    project_ids: list[str],
    game: str,
    *,
    loader: str | None = None,
    max_workers: int = 4,
    on_progress: Any | None = None,
) -> dict[str, list[dict]]:
    """
    Parallel CF file lists for unique project ids (same pages as list_cf_files).
    """
    uniq = sorted({str(p) for p in project_ids if p})
    if not uniq:
        return {}

    def one(pid: str) -> tuple[str, list[dict]]:
        return pid, list_cf_files(pid, game, loader=loader)

    out: dict[str, list[dict]] = {}
    results = httputil.map_parallel(
        uniq,
        one,
        max_workers=max_workers,
        on_progress=on_progress,
    )
    for item, res in zip(uniq, results):
        if isinstance(res, BaseException):
            out[item] = []
            continue
        pid, files = res
        out[pid] = files
    return out


def _mod_allows_distribution(project_id: str, key: str | None = None) -> bool:
    """False only when allowModDistribution is explicitly False."""
    pid = str(project_id)
    with _allow_mod_lock:
        if pid in _allow_mod_distribution:
            return _allow_mod_distribution[pid] is not False
    _pace()
    data = _cf_get_json(f"{_core_origin()}/v1/mods/{pid}", api_key=key)
    allow: Any = None
    payload = _payload_data(data)
    if isinstance(payload, dict) and "allowModDistribution" in payload:
        allow = payload.get("allowModDistribution")
    with _allow_mod_lock:
        _allow_mod_distribution[pid] = allow
    return allow is not False


def _get_mod_file(project_id: str, file_id: int, key: str | None = None) -> dict | None:
    _pace()
    data = _cf_get_json(
        f"{_core_origin()}/v1/mods/{project_id}/files/{file_id}",
        api_key=key,
    )
    payload = _payload_data(data)
    return payload if isinstance(payload, dict) else None


def _nonempty_url(raw: Any) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


@dataclass(frozen=True)
class DownloadSpec:
    url: str | None
    alt_url: str | None
    ua: str


def file_download_url(project_id: str, file_id: int) -> str | None:
    """GET /v1/mods/{modId}/files/{fileId}/download-url. None if no URL."""
    _pace()
    data = _cf_get_json(
        f"{_core_origin()}/v1/mods/{project_id}/files/{file_id}/download-url",
    )
    if data is None:
        return None
    return _nonempty_url(_payload_data(data))


def resolve_download(project_id: str, file_id: int, filename: str) -> DownloadSpec:
    """Official download-url via the publisher origin."""
    empty = DownloadSpec(url=None, alt_url=None, ua=UA)
    if not _mod_allows_distribution(project_id):
        return empty
    row = _get_mod_file(project_id, file_id)
    if row is not None and row.get("isAvailable") is False:
        return empty
    url = file_download_url(project_id, file_id)
    if not url and row is not None:
        url = _nonempty_url(row.get("downloadUrl"))
    return DownloadSpec(url=url, alt_url=None, ua=UA)


def channel_of_file(f: dict) -> str:
    rt = f.get("releaseType")
    if rt == RT_RELEASE:
        ch = "release"
    elif rt == RT_BETA:
        ch = "beta"
    elif rt == RT_ALPHA:
        ch = "alpha"
    else:
        ch = "release"
    blob = f"{f.get('displayName', '')} {f.get('fileName', '')}".lower()
    if re.search(r"(^|[^a-z])alpha([^a-z]|$)", blob) and ch == "release":
        return "alpha"
    if re.search(r"(^|[^a-z])(beta|rc)([^a-z]|$)", blob) and ch == "release":
        return "beta"
    return ch


def is_loader_game_match(f: dict, game: str, loader: str) -> bool:
    """
    Exact Minecraft version + loader match.

    Loose matching (1.20 ≈ 1.20.4, higher CF file id across MC lines) was selecting
    1.20.1 / 1.20.6 / 1.21 jars for a 1.20.4 NeoTech instance.
    """
    gvs = [str(x) for x in (f.get("gameVersions") or [])]
    gvl = [x.lower() for x in gvs]
    fn = f.get("fileName") or ""
    fn_l = fn.lower()

    has_game = exact_game_in_tags(gvs, game)
    if not has_game:
        # Allow filename only when tags omit MC but name has the exact version token
        if game not in fn and game not in (f.get("displayName") or ""):
            return False
        if filename_targets_other_mc(fn, game):
            return False
        has_game = True
    elif filename_targets_other_mc(fn, game):
        return False

    loader_l = loader.lower()
    if loader_l == "neoforge":
        # Pure Fabric → no
        if "fabric" in gvl and "neoforge" not in gvl and "forge" not in gvl:
            return False
        # Filename: -forge- without neoforge is almost always Minecraft Forge, not NeoForge
        forge_only_name = (
            bool(re.search(r"(^|[^a-z])forge([^a-z]|$)", fn_l)) and "neoforge" not in fn_l
        )
        if forge_only_name:
            return False
        if "neoforge" in gvl or "neoforge" in fn_l:
            return has_game
        # CF sometimes tags only "Forge" for dual-listed mods
        if "forge" in gvl and "neoforge" not in gvl:
            return False
        # No loader tag at all: only accept if filename claims neoforge
        return False
    if loader_l in gvl:
        return has_game
    return has_game and loader_l in fn_l


def version_guess(file_name: str, display: str) -> str:
    for s in (display, file_name):
        s = s or ""
        m = re.search(
            r"(\d+(?:\.\d+)+(?:[-.]?(?:alpha|beta|rc)\.?\d*)?(?:\+[^\s]*)?)",
            s,
            re.I,
        )
        if m:
            return m.group(1)
    return file_name or display or ""


def pick_update(
    files: list[dict],
    *,
    game: str,
    loader: str,
    installed_file_id: int | None,
    installed_name: str,
    installed_ver: str | None,
) -> tuple[dict | None, str]:
    cands = [
        f
        for f in files
        if is_loader_game_match(f, game, loader) and f.get("isEarlyAccessContent") is not True
    ]
    if not cands:
        return None, "no_matching_files"

    by: dict[str, list[dict]] = {"release": [], "beta": [], "alpha": []}
    for f in cands:
        by[channel_of_file(f)].append(f)

    def newest(lst: list[dict]) -> dict | None:
        if not lst:
            return None
        return sorted(lst, key=lambda x: x.get("dateCreated") or "", reverse=True)[0]

    if by["release"]:
        cand = newest(by["release"])
        reason = "release_available"
    elif by["beta"]:
        cand = newest(by["beta"])
        reason = "beta_is_normal_channel"
    elif by["alpha"]:
        cand = newest(by["alpha"])
        reason = "alpha_is_only_channel"
    else:
        return None, "no_channel"

    assert cand is not None
    ch = channel_of_file(cand)
    pool = [f for f in cands if channel_of_file(f) == ch]

    def rank_file(f: dict) -> tuple:
        fn = (f.get("fileName") or "").lower()
        # Prefer exact game token in name; never rank on truncated "1.20"
        name_ok = 1 if game.lower() in fn else 0
        return (name_ok, f.get("dateCreated") or "", int(f.get("id") or 0))

    pool.sort(key=rank_file, reverse=True)
    cand = pool[0]

    if installed_file_id and int(cand["id"]) == int(installed_file_id):
        return None, "same_file_id"
    # Prefer a same-MC pool member newer than installed file id when cand is older id
    if installed_file_id and int(cand["id"]) < int(installed_file_id):
        better = [f for f in pool if int(f["id"]) > int(installed_file_id)]
        if not better:
            return None, "no_newer_file_id"
        cand = sorted(better, key=rank_file, reverse=True)[0]
    if (cand.get("fileName") or "") == installed_name:
        return None, "same_filename"

    remote_ver = version_guess(cand.get("fileName") or "", cand.get("displayName") or "")
    fn = cand.get("fileName") or ""
    # product version after mc prefix in name
    m = re.search(rf"{re.escape(game)}[-_.](.+)\.jar$", fn, re.I)
    if m:
        remote_ver = m.group(1)

    if installed_ver and not installed_ver.startswith("${"):
        newer = is_newer(remote_ver, installed_ver)
        if newer is False:
            # Same MC pool only: allow higher file id + newer date as tie-break
            if installed_file_id and int(cand["id"]) > int(installed_file_id):
                inst = next(
                    (f for f in pool if int(f["id"]) == int(installed_file_id)),
                    None,
                )
                if inst and (cand.get("dateCreated") or "") > (inst.get("dateCreated") or ""):
                    return cand, reason + "_by_file_id_date"
            return None, "not_newer"
        if newer is True:
            return cand, reason

    if installed_file_id and int(cand["id"]) > int(installed_file_id):
        return cand, reason + "_higher_file_id"
    # Incomparable versions (${file.jarVersion}) but different name and same MC → offer
    if (cand.get("fileName") or "") != installed_name:
        return cand, reason
    return None, "not_clearly_newer"


def pick_file_satisfying_range(
    files: list[dict],
    *,
    game: str,
    loader: str,
    range_s: str,
) -> tuple[dict | None, str]:
    """Newest eligible CF file (release, then beta, then alpha) that fits versionRange."""
    cands = [
        f
        for f in files
        if is_loader_game_match(f, game, loader) and f.get("isEarlyAccessContent") is not True
    ]
    if not cands:
        return None, "no_matching_files"

    def file_ver(f: dict) -> str:
        fn = f.get("fileName") or ""
        remote_ver = version_guess(fn, f.get("displayName") or "")
        m = re.search(rf"{re.escape(game)}[-_.](.+)\.jar$", fn, re.I)
        if m:
            remote_ver = m.group(1)
        return remote_ver

    by: dict[str, list[dict]] = {"release": [], "beta": [], "alpha": []}
    for f in cands:
        if version_in_maven_range(file_ver(f), range_s) is True:
            by[channel_of_file(f)].append(f)

    def newest(lst: list[dict]) -> dict | None:
        if not lst:
            return None
        return sorted(lst, key=lambda x: x.get("dateCreated") or "", reverse=True)[0]

    if by["release"]:
        return newest(by["release"]), "release_satisfies_dep"
    if by["beta"]:
        return newest(by["beta"]), "beta_satisfies_dep"
    if by["alpha"]:
        return newest(by["alpha"]), "alpha_satisfies_dep"
    return None, "no_file_satisfies_range"
