from __future__ import annotations

import urllib.parse
from typing import Any

from . import httputil
from .versions import (
    exact_game_in_tags,
    filename_targets_other_mc,
    is_newer,
    is_prerelease_label,
    version_in_maven_range,
)

BASE = "https://api.modrinth.com/v2"


def _pace() -> None:
    httputil.MODRINTH_LIMITER.wait()


def filter_versions_for_game(versions: list[dict], game: str) -> list[dict]:
    """Keep only versions that list this exact Minecraft version."""
    out: list[dict] = []
    for v in versions or []:
        gvs = v.get("game_versions") or []
        if not exact_game_in_tags([str(x) for x in gvs], game):
            continue
        f = pick_primary_jar_file(v)
        if f and filename_targets_other_mc(f.get("filename") or "", game):
            continue
        out.append(v)
    return out


def version_channel(v: dict) -> str:
    t = (v.get("version_type") or "release").lower()
    base = t if t in ("release", "beta", "alpha") else "release"
    blob = f"{v.get('version_number', '')} {v.get('name', '')}"
    for f in v.get("files") or []:
        blob += " " + (f.get("filename") or "")
    bl = blob.lower()
    if re_alpha(bl) and base == "release":
        return "alpha"
    if is_prerelease_label(blob) and base == "release":
        return "beta"
    return base


def re_alpha(bl: str) -> bool:
    import re

    return bool(re.search(r"(^|[^a-z])alpha([^a-z]|$)", bl))


def lookup_versions_by_hashes(sha1_list: list[str]) -> dict[str, dict]:
    """Map sha1 -> version object (batch)."""
    out: dict[str, dict] = {}
    # API accepts up to ~1000; larger batches = fewer round trips
    chunk = 128
    n_batches = max(1, (len(sha1_list) + chunk - 1) // chunk) if sha1_list else 0
    from .progress import LineProgress

    line = LineProgress()
    for bi, i in enumerate(range(0, len(sha1_list), chunk), start=1):
        batch = sha1_list[i : i + chunk]
        line.set(f"  Modrinth hashes batch {bi}/{n_batches} ({len(batch)} ids)")
        _pace()
        data = httputil.post_json(
            f"{BASE}/version_files",
            {"hashes": batch, "algorithm": "sha1"},
        )
        if not data:
            for j, h in enumerate(batch, start=1):
                if j == 1 or j == len(batch) or j % 16 == 0:
                    line.set(
                        f"  Modrinth hashes batch {bi}/{n_batches} fallback {j}/{len(batch)}"
                    )
                _pace()
                one = httputil.get_json(f"{BASE}/version_file/{h}?algorithm=sha1")
                if one:
                    out[h] = one
            continue
        if isinstance(data, dict):
            for h, ver in data.items():
                if isinstance(ver, dict):
                    out[h] = ver
    line.end()
    return out


def project(project_id: str) -> dict | None:
    _pace()
    return httputil.get_json(f"{BASE}/project/{urllib.parse.quote(project_id)}")


def exact_slug_candidates(modid: str | None, jar_name: str) -> list[str]:
    """
    Slug/id candidates for exact GET /project/{id-or-slug} only.

    Uses installed modid and jar product stem. No free-text search; no invented
    hyphenation beyond what those two already contain.
    """
    from .pack_manifest import product_stem

    out: list[str] = []
    seen: set[str] = set()
    for raw in (modid or "", product_stem(jar_name or "")):
        s = (raw or "").strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def resolve_project_exact(
    candidates: list[str],
    *,
    cache: dict[str, dict | None] | None = None,
) -> tuple[dict | None, str | None, str]:
    """
    Exact Modrinth project resolution.

    Returns (project, matched_candidate, status) where status is:
      found | not_found | no_candidates
    """
    if not candidates:
        return None, None, "no_candidates"
    store = cache if cache is not None else {}
    for cand in candidates:
        if cand in store:
            proj = store[cand]
        else:
            proj = project(cand)
            store[cand] = proj
        if proj and proj.get("id"):
            return proj, cand, "found"
    return None, None, "not_found"


def project_versions(project_id: str, loader: str, game: str) -> list[dict]:
    """
    Versions for this loader + exact Minecraft version only.

    Do not fall back to a broader game line (e.g. 1.20): that mixed 1.20.1/1.20.4/1.20.6
    and chose wrong jars for NeoTech.
    """
    q = (
        f"{BASE}/project/{urllib.parse.quote(project_id)}/version?"
        f"loaders={urllib.parse.quote(__import__('json').dumps([loader]))}&"
        f"game_versions={urllib.parse.quote(__import__('json').dumps([game]))}"
    )
    _pace()
    data = httputil.get_json(q) or []
    return filter_versions_for_game(data if isinstance(data, list) else [], game)


def prefetch_versions(
    project_ids: list[str],
    loader: str,
    game: str,
    *,
    max_workers: int = 8,
    on_progress: Any | None = None,
) -> dict[str, list[dict]]:
    """
    Parallel project version lists for unique Modrinth project ids.
    Same payloads as sequential project_versions(); shared rate limiter.
    """
    uniq = sorted({p for p in project_ids if p})
    if not uniq:
        return {}

    def one(pid: str) -> tuple[str, list[dict]]:
        return pid, project_versions(pid, loader, game)

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
        pid, versions = res
        out[pid] = versions
    return out


def prefetch_projects(
    project_ids: list[str],
    *,
    max_workers: int = 6,
) -> dict[str, dict]:
    """Parallel project metadata (title/slug) for ids that need display names."""
    uniq = sorted({p for p in project_ids if p})
    if not uniq:
        return {}

    def one(pid: str) -> tuple[str, dict]:
        return pid, project(pid) or {}

    out: dict[str, dict] = {}
    results = httputil.map_parallel(uniq, one, max_workers=max_workers)
    for item, res in zip(uniq, results):
        if isinstance(res, BaseException):
            out[item] = {}
            continue
        pid, data = res
        out[pid] = data
    return out


def pick_primary_jar_file(v: dict) -> dict | None:
    files = v.get("files") or []
    if not files:
        return None
    usable = []
    for f in files:
        fn = (f.get("filename") or "").lower()
        if fn.endswith("-sources.jar") or fn.endswith("-data.jar") or "javadoc" in fn:
            continue
        usable.append(f)
    if not usable:
        return None
    for f in usable:
        if f.get("primary"):
            return f
    return usable[0]


def newest_in_channel(versions: list[dict], channel: str) -> dict | None:
    cands = [v for v in versions if version_channel(v) == channel]
    if not cands:
        return None
    cands.sort(key=lambda v: v.get("date_published") or "", reverse=True)
    return cands[0]


def choose_update(
    installed_ver: str | None,
    installed_version_id: str | None,
    versions: list[dict],
    installed_filename: str | None = None,
    game: str | None = None,
) -> tuple[dict | None, str]:
    if game:
        versions = filter_versions_for_game(versions, game)
    if not versions:
        return None, "no_versions"

    versions = sorted(versions, key=lambda v: v.get("date_published") or "", reverse=True)
    has_release = any(version_channel(v) == "release" for v in versions)
    has_beta = any(version_channel(v) == "beta" for v in versions)
    has_alpha = any(version_channel(v) == "alpha" for v in versions)

    if has_release:
        cand = newest_in_channel(versions, "release")
        reason = "release_available"
    elif has_beta:
        cand = newest_in_channel(versions, "beta")
        reason = "beta_is_normal_channel"
    elif has_alpha:
        cand = newest_in_channel(versions, "alpha")
        reason = "alpha_is_only_channel"
    else:
        return None, "no_usable_channel"

    if not cand:
        return None, "no_candidate"

    if installed_version_id and cand.get("id") == installed_version_id:
        return None, "same_modrinth_version"

    f = pick_primary_jar_file(cand)
    if f and installed_filename and f.get("filename") == installed_filename:
        return None, "same_filename"

    remote = cand.get("version_number") or ""
    if installed_ver:
        newer = is_newer(remote, installed_ver)
        if newer is True:
            return cand, reason
        if newer is False:
            return None, "already_newest_or_newer_local"
        # incomparable: use date vs installed version object
        inst_hits = [v for v in versions if v.get("id") == installed_version_id]
        if not inst_hits and installed_filename:
            for v in versions:
                for ff in v.get("files") or []:
                    if ff.get("filename") == installed_filename:
                        inst_hits.append(v)
        if inst_hits:
            inst_date = max(v.get("date_published") or "" for v in inst_hits)
            if (cand.get("date_published") or "") > inst_date:
                return cand, reason + "_by_date"
            return None, "not_newer_by_date"
        return None, "incomparable_skip"

    return cand, reason + "_no_installed_ver"


def pick_version_satisfying_range(
    versions: list[dict],
    range_s: str,
    game: str | None = None,
) -> tuple[dict | None, str]:
    """Newest eligible build (release, then beta, then alpha) that fits versionRange."""
    if game:
        versions = filter_versions_for_game(versions, game)
    if not versions:
        return None, "no_versions"
    versions = sorted(versions, key=lambda v: v.get("date_published") or "", reverse=True)

    def ok(v: dict) -> bool:
        return version_in_maven_range(v.get("version_number") or "", range_s) is True

    for channel, reason in (
        ("release", "release_satisfies_dep"),
        ("beta", "beta_satisfies_dep"),
        ("alpha", "alpha_satisfies_dep"),
    ):
        hits = [v for v in versions if version_channel(v) == channel and ok(v)]
        if hits:
            return hits[0], reason
    return None, "no_version_satisfies_range"
