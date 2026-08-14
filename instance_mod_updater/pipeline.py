from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import curseforge, httputil, modrinth, neoforge, pack_manifest
from .app_local import Instance, bin_dir, default_ftba_root, default_work_root
from .filenames import safe_jar_filename, safe_jar_path
from .inventory import (
    PLATFORM_MODIDS,
    InstalledMod,
    min_neoforge_from_ranges,
    read_mod_metadata,
    scan_mods_dir,
)
from .progress import LineProgress, announce_transfer, format_bytes, log_line


LogFn = Callable[[str], None]


def _log(msg: str, log: LogFn | None) -> None:
    log_line(msg, log)


@dataclass
class Replacement:
    jar_name: str
    new_jar: str
    old_version: str | None
    new_version: str | None
    channel: str | None
    source: str
    reason: str
    url: str
    modid: str | None = None
    display_name: str | None = None
    project: str | None = None


@dataclass
class CheckResult:
    instance: str
    mc_version: str
    loader: str
    mod_loader: str
    checked: int = 0
    updates: list[Replacement] = field(default_factory=list)
    current: list[dict] = field(default_factory=list)
    # Jars we could not latest-check on MR/CF (structured reason codes + layman why).
    # Includes true FTB-private pack blobs and cascade failures. Not "up to date."
    pack_only: list[dict] = field(default_factory=list)
    no_source: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    min_neoforge_floor: str | None = None
    pack_neoforge: str | None = None
    # How many update jars were transferred this run vs already under work/jars
    downloaded: int = 0
    cached_jars: int = 0
    downloaded_files: list[str] = field(default_factory=list)
    cached_files: list[str] = field(default_factory=list)


def _layman_for_codes(codes: list[str], *, pack_matched: bool) -> str:
    """Short user-facing why for uncheckable jars (not \"latest\" / \"up to date\")."""
    cset = set(codes)
    if "cf_no_key" in cset:
        return (
            "Pack row has a CurseForge project, but no Core API key, so the official "
            "file list was not fetched. Latest not checked"
        )
    if "ftb_private_blob" in cset or "pack_ftb_only" in cset:
        if "pack_pin_match" in cset or pack_matched:
            return (
                "FTB pack file only. Matches pack; no public Modrinth/CurseForge project "
                "found, so latest release was not checked"
            )
        return (
            "FTB pack file only. No public Modrinth/CurseForge project; "
            "latest release was not checked"
        )
    if "mr_no_eligible_version" in cset:
        return (
            "Found a Modrinth project, but no eligible build for this Minecraft version "
            "and loader. Latest not confirmed"
        )
    if "mr_project_not_found" in cset and "fingerprint_no_key" in cset:
        return (
            "No Modrinth project for this mod id/stem; CurseForge fingerprint skipped "
            "(no API key). Latest not checked"
        )
    if "mr_project_not_found" in cset and "fingerprint_miss" in cset:
        return (
            "No Modrinth project for this mod id/stem; CurseForge fingerprint found no "
            "match. Latest not checked"
        )
    if "fingerprint_error" in cset:
        return "CurseForge fingerprint lookup failed. Latest not checked"
    if "no_modrinth_hash_and_no_pack_cf" in cset or (
        "no_mr_hash" in cset and "no_pack_cf" in cset
    ):
        return (
            "Jar hash not on Modrinth and pack row has no CurseForge project; "
            "resolve cascade did not find a public listing. Latest not checked"
        )
    if codes:
        return "Latest release not checked (" + ", ".join(codes) + ")"
    return "Latest release not checked"


def _uncheckable_row(
    *,
    jar: str,
    modid: str | None,
    codes: list[str],
    pack_matched: bool,
    pack_file: str | None = None,
    version: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    primary = codes[0] if codes else "uncheckable"
    # Prefer a stable primary reason for true FTB-private blobs
    if "ftb_private_blob" in codes:
        primary = "ftb_private_blob"
    elif "pack_ftb_only" in codes:
        primary = "pack_ftb_only"
    elif "cf_no_key" in codes:
        primary = "cf_no_key"
    elif "mr_no_eligible_version" in codes:
        primary = "mr_no_eligible_version"
    elif "mr_project_not_found" in codes:
        primary = "mr_project_not_found"
    row: dict[str, Any] = {
        "jar": jar,
        "modid": modid,
        "reason": primary,
        "reasons": codes,
        "layman": _layman_for_codes(codes, pack_matched=pack_matched),
        "status": "uncheckable",
        "version": version,
        "pack_file": pack_file,
        "pack_matched": pack_matched,
    }
    if extra:
        row.update(extra)
    return row


def _provided_ids(
    *,
    modid: str | None,
    provides: list[str] | None,
    mod_versions: dict[str, str] | None,
) -> set[str]:
    out: set[str] = set()
    if modid:
        out.add(modid.lower())
    for p in provides or []:
        if p:
            out.add(str(p).lower())
    for k in mod_versions or {}:
        if k:
            out.add(str(k).lower())
    return out


def _planned_dep_sources(
    mods: list[InstalledMod],
    updates: list[Replacement],
    jars_dir: Path,
) -> list[tuple[str, str | None, list[dict[str, str]], set[str]]]:
    """(label, requester_modid, required deps, ids this jar already provides)."""
    by_old = {u.jar_name: u for u in updates}
    out: list[tuple[str, str | None, list[dict[str, str]], set[str]]] = []
    for mod in mods:
        upd = by_old.get(mod.jar_name)
        if upd:
            staged = safe_jar_path(jars_dir, upd.new_jar)
            if staged is None or not staged.is_file():
                continue
            meta = read_mod_metadata(staged)
            deps = list(meta.get("dependencies") or [])
            label = upd.display_name or upd.modid or upd.new_jar
            provided = _provided_ids(
                modid=meta.get("modid") or upd.modid or mod.modid,
                provides=list(meta.get("provides") or []),
                mod_versions=dict(meta.get("mod_versions") or {}),
            )
            out.append((label, upd.modid or mod.modid, deps, provided))
            continue
        if mod.dependencies:
            label = mod.display_name or mod.modid or mod.jar_name
            provided = _provided_ids(
                modid=mod.modid,
                provides=mod.provides,
                mod_versions=mod.mod_versions,
            )
            out.append((label, mod.modid, list(mod.dependencies), provided))
    return out


def _effective_companion_version(
    companion: InstalledMod,
    upd: Replacement | None,
    jars_dir: Path,
    need_id: str = "",
) -> str:
    need = (need_id or companion.modid or "").lower()
    if upd:
        staged = safe_jar_path(jars_dir, upd.new_jar)
        if staged is not None and staged.is_file():
            meta = read_mod_metadata(staged)
            versions = meta.get("mod_versions") or {}
            ver = versions.get(need) or meta.get("version")
            if ver and not str(ver).startswith("${"):
                return str(ver)
        if upd.new_version:
            return upd.new_version
    if need and companion.mod_versions.get(need):
        ver = companion.mod_versions[need]
        if ver and not ver.startswith("${"):
            return ver
    if companion.version and not companion.version.startswith("${"):
        return companion.version
    return ""


def _index_by_modid(mods: list[InstalledMod]) -> dict[str, InstalledMod]:
    """Primary modid wins; extra [[mods]] ids in the same jar fill gaps."""
    by: dict[str, InstalledMod] = {}
    for m in mods:
        if m.modid:
            by[m.modid.lower()] = m
    for m in mods:
        for mid in m.mod_versions:
            by.setdefault(mid.lower(), m)
        for mid in m.provides:
            by.setdefault(mid.lower(), m)
    return by


def error_layman(row: dict[str, Any]) -> str:
    """Plain-language explanation for one check error (console + report)."""
    err = str(row.get("err") or "unknown")
    jar = str(row.get("jar") or "A mod")
    need = str(row.get("modid") or "a required companion")
    rng = str(row.get("range") or "").strip()
    rng_s = f" ({rng})" if rng else ""
    actual = row.get("actual")
    if err == "missing_mandatory_dep":
        return (
            f"{jar} lists {need}{rng_s} as required. That companion is not a "
            f"separate jar in this instance and is not bundled inside {jar}. "
            f"This tool does not download new mods. If the game already runs, "
            f"the checker missed a bundled library. If the game will not "
            f"start, install {need} and run check again."
        )
    if err == "mandatory_dep_unsatisfied":
        if actual:
            have = f" The installed version is {actual}."
        else:
            have = " Its version on disk could not be read."
        return (
            f"{jar} requires {need}{rng_s}.{have} "
            f"No matching update was found on Modrinth or CurseForge."
        )
    if err == "tiny_download":
        return (
            f"The file downloaded for {jar} was too small to be a real jar. "
            f"The transfer may have failed."
        )
    if err == "no_file":
        return (
            f"Found an update listing for {jar}, but it had no downloadable jar."
        )
    if err == "cf_no_key":
        return (
            f"A CurseForge API key is required to download the update for {jar}."
        )
    if err == "cf_no_download_url":
        return f"CurseForge did not give a download link for {jar}."
    extra = str(err)
    return f"{jar}: {extra}"


def _attach_error_layman(result: CheckResult) -> None:
    for row in result.errors:
        if not row.get("layman"):
            row["layman"] = error_layman(row)


def _satisfy_mandatory_deps(
    *,
    mods: list[InstalledMod],
    result: CheckResult,
    jars_dir: Path,
    by_hash: dict[str, Any],
    versions_cache: dict[str, list[dict]],
    cf_files_cache: dict[str, list[dict]],
    cf_pid_for_mod: dict[str, tuple[str, int]],
    fp_cf_for: dict[str, tuple[str, int]],
    mr_exact_for: dict[str, tuple[dict, str]],
    mc: str,
    loader: str,
    download: bool,
    stage_jar: Callable[..., bool],
    pending_mr_titles: list[tuple[Replacement, str]],
    log: LogFn | None,
) -> None:
    """If a planned jar requires a newer installed companion, stage that companion."""
    from .versions import version_in_maven_range

    by_modid = _index_by_modid(mods)
    failed: set[tuple[str, str]] = set()
    queued = 0

    def updates_by_modid() -> dict[str, Replacement]:
        return {(u.modid or "").lower(): u for u in result.updates if u.modid}

    def forget_current(jar_name: str) -> None:
        result.current[:] = [c for c in result.current if c.get("jar") != jar_name]

    def replace_update(rep: Replacement) -> None:
        result.updates[:] = [u for u in result.updates if u.jar_name != rep.jar_name]
        forget_current(rep.jar_name)
        result.updates.append(rep)

    for _ in range(8):
        changed = False
        by_id = updates_by_modid()
        for requester, req_modid, deps, provided in _planned_dep_sources(
            mods, result.updates, jars_dir
        ):
            for dep in deps:
                need_id = (dep.get("modid") or "").lower()
                rng = dep.get("versionRange") or ""
                if not need_id or not rng:
                    continue
                if need_id in PLATFORM_MODIDS:
                    continue
                # Same jar already ships this id (extra [[mods]] or JarJar).
                if need_id in provided:
                    continue
                companion = by_modid.get(need_id)
                if companion is None:
                    key = (need_id, "missing")
                    if key in failed:
                        continue
                    failed.add(key)
                    result.errors.append(
                        {
                            "jar": requester,
                            "err": "missing_mandatory_dep",
                            "modid": need_id,
                            "range": rng,
                            "requested_by": req_modid,
                        }
                    )
                    continue
                upd = by_id.get(need_id)
                eff = _effective_companion_version(companion, upd, jars_dir, need_id)
                if version_in_maven_range(eff, rng) is True:
                    continue
                if version_in_maven_range(eff, rng) is None and eff:
                    continue
                key = (companion.jar_name, rng)
                if key in failed:
                    continue

                pid = ""
                mr_hit = by_hash.get(companion.sha1) or {}
                if mr_hit.get("project_id"):
                    pid = str(mr_hit["project_id"])
                elif companion.jar_name in mr_exact_for:
                    proj, _slug = mr_exact_for[companion.jar_name]
                    pid = str(proj.get("id") or "")

                staged_ok = False
                if pid:
                    versions = versions_cache.get(pid)
                    if versions is None:
                        versions = modrinth.project_versions(pid, loader, mc)
                        versions_cache[pid] = versions
                    cand, reason = modrinth.pick_version_satisfying_range(
                        versions, rng, game=mc
                    )
                    f = modrinth.pick_primary_jar_file(cand) if cand else None
                    if cand and f:
                        new_name = safe_jar_filename(f["filename"])
                        if not new_name:
                            failed.add(key)
                            result.errors.append(
                                {
                                    "jar": companion.jar_name,
                                    "err": "unsafe_filename",
                                    "reason": "mandatory_dep",
                                }
                            )
                            continue
                        url = f["url"]
                        if new_name != companion.jar_name and (
                            not upd or upd.new_jar != new_name
                        ):
                            if download:
                                dest = safe_jar_path(jars_dir, new_name)
                                if dest is None:
                                    failed.add(key)
                                    result.errors.append(
                                        {
                                            "jar": companion.jar_name,
                                            "err": "unsafe_filename",
                                            "reason": "mandatory_dep",
                                        }
                                    )
                                    continue
                                if not stage_jar(
                                    url, dest, ua=httputil.DEFAULT_UA, label=new_name
                                ):
                                    failed.add(key)
                                    result.errors.append(
                                        {
                                            "jar": companion.jar_name,
                                            "err": "tiny_download",
                                            "url": url,
                                            "reason": "mandatory_dep",
                                        }
                                    )
                                    continue
                            rep = Replacement(
                                jar_name=companion.jar_name,
                                new_jar=new_name,
                                old_version=companion.version,
                                new_version=cand.get("version_number"),
                                channel=modrinth.version_channel(cand),
                                source="modrinth",
                                reason=reason,
                                url=url,
                                modid=companion.modid,
                                display_name=companion.display_name,
                                project=pid,
                            )
                            replace_update(rep)
                            pending_mr_titles.append((rep, pid))
                            staged_ok = True
                            queued += 1
                            _log(
                                f"  Mandatory dep {need_id} {rng} required by {requester}. "
                                f"Staging {new_name}",
                                log,
                            )

                if not staged_ok:
                    cf_info = cf_pid_for_mod.get(companion.jar_name) or fp_cf_for.get(
                        companion.jar_name
                    )
                    if cf_info:
                        project_id, _file_id = cf_info
                        files = cf_files_cache.get(project_id)
                        if files is None:
                            files = curseforge.list_cf_files(
                                project_id, mc, loader=loader
                            )
                            cf_files_cache[project_id] = files
                        cand_f, reason = curseforge.pick_file_satisfying_range(
                            files, game=mc, loader=loader, range_s=rng
                        )
                        if cand_f:
                            new_name = safe_jar_filename(cand_f["fileName"])
                            if not new_name:
                                failed.add(key)
                                result.errors.append(
                                    {
                                        "jar": companion.jar_name,
                                        "err": "unsafe_filename",
                                        "reason": "mandatory_dep",
                                    }
                                )
                                continue
                            new_id = int(cand_f["id"])
                            got = curseforge.resolve_download(
                                project_id, new_id, new_name
                            )
                            if not got.url:
                                failed.add(key)
                                result.errors.append(
                                    {
                                        "jar": companion.jar_name,
                                        "err": (
                                            "cf_no_key"
                                            if not curseforge.resolve_api_key()
                                            else "cf_no_download_url"
                                        ),
                                        "reason": "mandatory_dep",
                                    }
                                )
                                continue
                            url = got.url
                            if new_name != companion.jar_name and (
                                not upd or upd.new_jar != new_name
                            ):
                                if download:
                                    dest = safe_jar_path(jars_dir, new_name)
                                    if dest is None:
                                        failed.add(key)
                                        result.errors.append(
                                            {
                                                "jar": companion.jar_name,
                                                "err": "unsafe_filename",
                                                "reason": "mandatory_dep",
                                            }
                                        )
                                        continue
                                    try:
                                        ok = stage_jar(
                                            url,
                                            dest,
                                            ua=got.ua,
                                            label=new_name,
                                            alt_url=got.alt_url,
                                        )
                                    except Exception as e:
                                        failed.add(key)
                                        result.errors.append(
                                            {
                                                "jar": companion.jar_name,
                                                "err": str(e),
                                                "url": url,
                                                "reason": "mandatory_dep",
                                            }
                                        )
                                        continue
                                    if not ok:
                                        failed.add(key)
                                        result.errors.append(
                                            {
                                                "jar": companion.jar_name,
                                                "err": "tiny_download",
                                                "url": url,
                                                "reason": "mandatory_dep",
                                            }
                                        )
                                        continue
                                replace_update(
                                    Replacement(
                                        jar_name=companion.jar_name,
                                        new_jar=new_name,
                                        old_version=companion.version,
                                        new_version=curseforge.version_guess(
                                            new_name, cand_f.get("displayName") or ""
                                        ),
                                        channel=curseforge.channel_of_file(cand_f),
                                        source="curseforge",
                                        reason=reason,
                                        url=url,
                                        modid=companion.modid,
                                        display_name=companion.display_name,
                                        project=f"cf:{project_id}",
                                    )
                                )
                                staged_ok = True
                                queued += 1
                                _log(
                                    f"  Mandatory dep {need_id} {rng} required by "
                                    f"{requester}. Staging {new_name}",
                                    log,
                                )

                if staged_ok:
                    changed = True
                    by_id = updates_by_modid()
                    continue
                failed.add(key)
                result.errors.append(
                    {
                        "jar": companion.jar_name,
                        "err": "mandatory_dep_unsatisfied",
                        "requested_by": req_modid or requester,
                        "modid": need_id,
                        "range": rng,
                        "actual": eff or None,
                    }
                )
        if not changed:
            break
    if queued:
        _log(f"  Mandatory deps: staged {queued} companion jar(s)", log)


def check_updates(
    inst: Instance,
    *,
    work_root: Path | None = None,
    pack: dict | None = None,
    pack_path: Path | None = None,
    pack_id: int | None = None,
    version_id: int | None = None,
    download: bool = True,
    cf_api_key: str | None = None,
    log: LogFn | None = None,
) -> tuple[CheckResult, Path]:
    work = work_root or default_work_root()
    work.mkdir(parents=True, exist_ok=True)
    jars_dir = work / "jars"
    jars_dir.mkdir(parents=True, exist_ok=True)

    if cf_api_key and str(cf_api_key).strip():
        os.environ["CURSEFORGE_API_KEY"] = str(cf_api_key).strip()

    mc = inst.mc_version
    loader = inst.loader_kind
    if not mc:
        raise SystemExit("instance.json missing mcVersion")

    # Load FTB pack for CF project IDs
    if pack is None and pack_path and pack_path.is_file():
        pack = pack_manifest.load_pack_file(pack_path)
        _log(f"Loaded pack file {pack_path}", log)
    if pack is None:
        pid = pack_id or inst.pack_id
        vid = version_id or inst.version_id
        if pid and vid:
            _log(f"Fetching FTB pack {pid}/{vid} ...", log)
            pack = pack_manifest.fetch_pack(pid, vid)
            if pack:
                cache = work / f"pack-{pid}-{vid}.json"
                cache.write_text(json.dumps(pack), encoding="utf-8")
                _log(f"Cached pack to {cache}", log)
        else:
            _log(
                "No pack id/versionId on instance; pass --pack-id and --version-id "
                "(or a pack JSON) so pack rows can supply CurseForge project ids. "
                "Modrinth still runs for hash hits. CurseForge file lists still need "
                "a Core API key.",
                log,
            )

    pack_index = pack_manifest.index_pack_mods(pack) if pack else {"by_sha1": {}, "by_name": {}}
    pack_targets = pack_manifest.pack_targets(pack) if pack else {}
    pack_nf = pack_targets.get("neoforge")

    _log(f"Scanning mods under {inst.mods_dir} ...", log)
    t_scan = time.monotonic()
    scan_line = LineProgress()

    def _scan_prog(i: int, total: int, name: str) -> None:
        pct = 100.0 * i / total if total else 0
        scan_line.set(f"  Scan [{i}/{total}] {pct:5.1f}%  {name}")

    mods = scan_mods_dir(inst.mods_dir, read_meta=True, on_progress=_scan_prog)
    scan_line.end(
        f"  Scan done: {len(mods)} jars in {time.monotonic() - t_scan:.1f}s "
        f"({format_bytes(sum(m.size for m in mods))})"
    )

    result = CheckResult(
        instance=str(inst.path),
        mc_version=mc,
        loader=loader,
        mod_loader=inst.mod_loader,
        checked=len(mods),
        min_neoforge_floor=min_neoforge_from_ranges(mods),
        pack_neoforge=pack_nf,
    )

    hashes = [m.sha1 for m in mods]
    _log(f"Modrinth: looking up {len(hashes)} jars by SHA1...", log)
    t_mr = time.monotonic()
    by_hash = modrinth.lookup_versions_by_hashes(hashes)
    _log(
        f"Modrinth: {len(by_hash)}/{len(hashes)} known jars in {time.monotonic() - t_mr:.1f}s",
        log,
    )

    # Unique Modrinth project ids → parallel version list prefetch (same data as before)
    mr_pids: list[str] = []
    for m in mods:
        ver = by_hash.get(m.sha1)
        if ver and ver.get("project_id"):
            mr_pids.append(str(ver["project_id"]))
    uniq_mr = sorted(set(mr_pids))
    versions_cache: dict[str, list[dict]] = {}
    if uniq_mr:
        _log(f"Modrinth: fetching version lists for {len(uniq_mr)} projects...", log)
        t_pv = time.monotonic()
        pref_line = LineProgress()

        def _mr_prog(done: int, total: int, _item: str) -> None:
            pref_line.set(f"  Modrinth versions {done}/{total}")

        versions_cache = modrinth.prefetch_versions(
            uniq_mr, loader, mc, max_workers=8, on_progress=_mr_prog
        )
        pref_line.end(
            f"  Modrinth versions: {len(versions_cache)} projects in "
            f"{time.monotonic() - t_pv:.1f}s"
        )

    # Unique CF project ids for jars not on Modrinth → parallel file list prefetch
    # Pack match may inherit CF project from an older pack pin (same modid/stem).
    cf_pid_for_mod: dict[str, tuple[str, int]] = {}  # jar_name -> (project_id, file_id)
    cf_pids: list[str] = []
    # Cascade candidates: no MR hash and no pack CF project
    cascade_mods: list[Any] = []
    pack_entry_for: dict[str, dict | None] = {}
    for m in mods:
        if m.sha1 in by_hash:
            continue
        entry = pack_manifest.match_pack_entry(
            pack_index, sha1=m.sha1, jar_name=m.jar_name, modid=m.modid
        )
        pack_entry_for[m.jar_name] = entry
        if entry and pack_manifest.has_curseforge_project(entry):
            project_id = str(entry["curseforge"]["project"])
            file_id = int(entry["curseforge"]["file"])
            cf_pid_for_mod[m.jar_name] = (project_id, file_id)
            cf_pids.append(project_id)
            continue
        cascade_mods.append(m)
    uniq_cf = sorted(set(cf_pids))
    cf_files_cache: dict[str, list[dict]] = {}
    if uniq_cf:
        _log(f"CurseForge: fetching file lists for {len(uniq_cf)} projects...", log)
        t_cf = time.monotonic()
        cf_line = LineProgress()

        def _cf_prog(done: int, total: int, _item: str) -> None:
            cf_line.set(f"  CurseForge files {done}/{total}")

        cf_files_cache = curseforge.prefetch_files(
            uniq_cf, mc, loader=loader, max_workers=4, on_progress=_cf_prog
        )
        cf_line.end(
            f"  CurseForge files: {len(cf_files_cache)} projects in "
            f"{time.monotonic() - t_cf:.1f}s"
        )

    # Spec 6 cascade (no MR hash + no pack CF): exact Modrinth GET, then optional CF fingerprint
    api_key = curseforge.resolve_api_key(cf_api_key)
    mr_project_cache: dict[str, dict | None] = {}
    # jar_name -> (project_dict, matched_slug) when exact GET hits
    mr_exact_for: dict[str, tuple[dict, str]] = {}
    # jar_name -> (project_id, file_id) from fingerprint
    fp_cf_for: dict[str, tuple[str, int]] = {}
    # jar_name -> cascade reason codes accumulated during resolve
    cascade_notes: dict[str, list[str]] = {}

    if cascade_mods:
        _log(
            f"Resolve cascade: {len(cascade_mods)} jar(s) without MR hash / pack CF "
            f"(exact Modrinth GET"
            + ("; CF fingerprint on" if api_key else "; CF fingerprint off. No API key")
            + ")...",
            log,
        )
        # Prefetch unique exact slug candidates
        slug_to_jars: dict[str, list[str]] = {}
        jar_slugs: dict[str, list[str]] = {}
        for m in cascade_mods:
            slugs = modrinth.exact_slug_candidates(m.modid, m.jar_name)
            jar_slugs[m.jar_name] = slugs
            for s in slugs:
                slug_to_jars.setdefault(s, []).append(m.jar_name)
        uniq_slugs = sorted(slug_to_jars)
        if uniq_slugs:
            t_ex = time.monotonic()
            ex_line = LineProgress()

            def _ex_one(slug: str) -> tuple[str, dict | None]:
                return slug, modrinth.project(slug)

            def _ex_prog(done: int, total: int, _item: str) -> None:
                ex_line.set(f"  Modrinth exact GET {done}/{total}")

            ex_results = httputil.map_parallel(
                uniq_slugs, _ex_one, max_workers=6, on_progress=_ex_prog
            )
            for item, res in zip(uniq_slugs, ex_results):
                if isinstance(res, BaseException):
                    mr_project_cache[item] = None
                else:
                    slug, proj = res
                    mr_project_cache[slug] = proj if proj and proj.get("id") else None
            ex_line.end(
                f"  Modrinth exact GET: {len(uniq_slugs)} candidate(s) in "
                f"{time.monotonic() - t_ex:.1f}s"
            )

        need_fp: list[Any] = []
        for m in cascade_mods:
            notes = ["no_mr_hash", "no_pack_cf"]
            proj, matched, status = modrinth.resolve_project_exact(
                jar_slugs.get(m.jar_name) or [],
                cache=mr_project_cache,
            )
            if status == "found" and proj is not None and matched:
                mr_exact_for[m.jar_name] = (proj, matched)
                notes.append("mr_exact_hit")
            elif status == "no_candidates":
                notes.append("mr_project_not_found")
                need_fp.append(m)
            else:
                notes.append("mr_project_not_found")
                need_fp.append(m)
            cascade_notes[m.jar_name] = notes

        # Prefetch versions for exact MR hits
        exact_pids = [
            str(proj["id"]) for proj, _ in mr_exact_for.values() if proj.get("id")
        ]
        for pid in sorted(set(exact_pids)):
            if pid not in versions_cache:
                versions_cache[pid] = modrinth.project_versions(pid, loader, mc)

        # Fingerprint also when exact project exists but has no eligible versions
        # for this MC+loader (e.g. almostunified 1.20.4 only on CF/FTB).
        for m in cascade_mods:
            if m.jar_name not in mr_exact_for:
                continue
            proj, _matched = mr_exact_for[m.jar_name]
            pid = str(proj.get("id") or "")
            vers = versions_cache.get(pid) or []
            if not vers:
                notes = cascade_notes.setdefault(m.jar_name, ["no_mr_hash", "no_pack_cf"])
                if "mr_no_eligible_version" not in notes:
                    notes.append("mr_no_eligible_version")
                if m not in need_fp:
                    need_fp.append(m)

        # Optional CF fingerprint for remaining jars
        if need_fp and api_key:
            fp_values: list[int] = []
            jar_fp: dict[str, int] = {}
            for m in need_fp:
                entry = pack_entry_for.get(m.jar_name)
                fp = pack_manifest.pack_file_cf_murmur(entry)
                if fp is None:
                    try:
                        fp = curseforge.fingerprint_file(m.path)
                    except OSError:
                        cascade_notes.setdefault(m.jar_name, []).append("fingerprint_error")
                        continue
                jar_fp[m.jar_name] = fp
                fp_values.append(fp)
            if fp_values:
                t_fp = time.monotonic()
                _log(
                    f"CurseForge: fingerprint lookup for {len(jar_fp)} jar(s)...",
                    log,
                )
                try:
                    matches = curseforge.fingerprint_lookup(fp_values, api_key=api_key)
                except Exception:
                    matches = {}
                    for m in need_fp:
                        cascade_notes.setdefault(m.jar_name, []).append("fingerprint_error")
                hit = 0
                for m in need_fp:
                    fp = jar_fp.get(m.jar_name)
                    if fp is None:
                        continue
                    match = matches.get(fp)
                    pf = curseforge.match_to_project_file(match)
                    if pf:
                        fp_cf_for[m.jar_name] = pf
                        cf_pids.append(pf[0])
                        hit += 1
                        cascade_notes.setdefault(m.jar_name, []).append("fingerprint_hit")
                    else:
                        cascade_notes.setdefault(m.jar_name, []).append("fingerprint_miss")
                _log(
                    f"  CurseForge fingerprint: {hit}/{len(jar_fp)} hit(s) in "
                    f"{time.monotonic() - t_fp:.1f}s",
                    log,
                )
                # Prefetch CF files for fingerprint projects
                new_cf = sorted({pid for pid, _ in fp_cf_for.values() if pid not in cf_files_cache})
                if new_cf:
                    more = curseforge.prefetch_files(
                        new_cf, mc, loader=loader, max_workers=4
                    )
                    cf_files_cache.update(more)
        elif need_fp and not api_key:
            for m in need_fp:
                cascade_notes.setdefault(m.jar_name, []).append("fingerprint_no_key")

    total_mods = len(mods)
    t_check = time.monotonic()
    check_line = LineProgress()
    last_ui = 0.0
    # Defer Modrinth project title/slug fetch until we know which updates need them
    pending_mr_titles: list[tuple[Replacement, str]] = []  # (rep, project_id)

    def _status(idx: int, short: str) -> None:
        nonlocal last_ui
        now = time.monotonic()
        if idx != total_mods and (now - last_ui) < 0.25:
            return
        last_ui = now
        pct = 100.0 * idx / total_mods if total_mods else 0
        check_line.set(
            f"  Check [{idx}/{total_mods}] {pct:5.1f}%  "
            f"upd={len(result.updates)} dl={result.downloaded} "
            f"cached={result.cached_jars} ok={len(result.current)} "
            f"pack_only={len(result.pack_only)} "
            f"miss={len(result.no_source)} err={len(result.errors)}  | {short}"
        )

    def _stage_jar(
        url: str,
        dest: Path | None,
        *,
        ua: str,
        label: str,
        alt_url: str | None = None,
    ) -> bool:
        """Download if missing; count dl vs cached. False if result unusable."""
        if dest is None:
            return False
        dest = safe_jar_path(jars_dir, dest.name)
        if dest is None:
            return False
        check_line.park()
        if dest.exists() and dest.stat().st_size > 0:
            result.cached_jars += 1
            result.cached_files.append(dest.name)
            announce_transfer(label, dest.stat().st_size, cached=True)
            return True
        try:
            httputil.download(url, str(dest), ua=ua, label=label)
        except Exception:
            if not alt_url:
                raise
            httputil.download(alt_url, str(dest), ua=ua, label=label)
        if dest.stat().st_size < 100:
            dest.unlink(missing_ok=True)
            return False
        result.downloaded += 1
        result.downloaded_files.append(dest.name)
        return True

    for idx, mod in enumerate(mods, start=1):
        short = mod.display_name or mod.modid or mod.jar_name
        _status(idx, short)
        try:
            mr_ver = by_hash.get(mod.sha1)
            if mr_ver:
                pid = mr_ver.get("project_id")
                if not pid:
                    result.no_source.append({"jar": mod.jar_name, "reason": "modrinth_no_project"})
                    continue
                pid = str(pid)
                versions = versions_cache.get(pid) or []
                # Prefer Modrinth version for this exact hash; jar mods.toml is often stale
                # (Towns and Towers 1.13.1b still ships version="1.12.1" in metadata).
                installed_ver = mr_ver.get("version_number") or mod.version
                upd, reason = modrinth.choose_update(
                    installed_ver,
                    mr_ver.get("id"),
                    versions,
                    installed_filename=mod.jar_name,
                    game=mc,
                )
                if not upd:
                    result.current.append(
                        {
                            "jar": mod.jar_name,
                            "source": "modrinth",
                            "project": pid,
                            "reason": reason,
                            "version": installed_ver,
                        }
                    )
                    continue
                f = modrinth.pick_primary_jar_file(upd)
                if not f:
                    result.errors.append({"jar": mod.jar_name, "err": "no_file"})
                    continue
                new_name = safe_jar_filename(f["filename"])
                if not new_name:
                    result.errors.append({"jar": mod.jar_name, "err": "unsafe_filename"})
                    continue
                url = f["url"]
                if new_name == mod.jar_name:
                    result.current.append(
                        {"jar": mod.jar_name, "source": "modrinth", "reason": "same_filename"}
                    )
                    continue
                if download:
                    dest = safe_jar_path(jars_dir, new_name)
                    if dest is None:
                        result.errors.append({"jar": mod.jar_name, "err": "unsafe_filename"})
                        continue
                    if not _stage_jar(url, dest, ua=httputil.DEFAULT_UA, label=new_name):
                        result.errors.append(
                            {"jar": mod.jar_name, "err": "tiny_download", "url": url}
                        )
                        continue

                rep = Replacement(
                    jar_name=mod.jar_name,
                    new_jar=new_name,
                    old_version=installed_ver,
                    new_version=upd.get("version_number"),
                    channel=modrinth.version_channel(upd),
                    source="modrinth",
                    reason=reason,
                    url=url,
                    modid=mod.modid,
                    display_name=mod.display_name,
                    project=pid,
                )
                result.updates.append(rep)
                pending_mr_titles.append((rep, pid))
                continue

            # CurseForge via FTB pack project IDs, or Spec 6 cascade
            # (exact Modrinth GET, then optional CF fingerprint) when pack has no CF.
            cf_info = cf_pid_for_mod.get(mod.jar_name) or fp_cf_for.get(mod.jar_name)
            entry = pack_entry_for.get(mod.jar_name)
            if entry is None and mod.jar_name not in pack_entry_for:
                entry = pack_manifest.match_pack_entry(
                    pack_index,
                    sha1=mod.sha1,
                    jar_name=mod.jar_name,
                    modid=mod.modid,
                )

            # Exact Modrinth project resolve (cascade step 1)
            if not cf_info and mod.jar_name in mr_exact_for:
                proj, matched_slug = mr_exact_for[mod.jar_name]
                pid = str(proj["id"])
                versions = versions_cache.get(pid)
                if versions is None:
                    versions = modrinth.project_versions(pid, loader, mc)
                    versions_cache[pid] = versions
                if not versions:
                    notes = list(cascade_notes.get(mod.jar_name) or ["no_mr_hash", "no_pack_cf"])
                    if "mr_no_eligible_version" not in notes:
                        notes.append("mr_no_eligible_version")
                    # Fall through to fingerprint if available
                    if mod.jar_name in fp_cf_for:
                        cf_info = fp_cf_for[mod.jar_name]
                        cascade_notes[mod.jar_name] = notes
                    else:
                        pack_matched = bool(entry)
                        notes = [c for c in notes if c != "mr_exact_hit"]
                        if "mr_no_eligible_version" not in notes:
                            notes.append("mr_no_eligible_version")
                        row = _uncheckable_row(
                            jar=mod.jar_name,
                            modid=mod.modid,
                            codes=notes,
                            pack_matched=pack_matched,
                            pack_file=str((entry or {}).get("name") or "") or None,
                            version=mod.version,
                            extra={
                                "source": "modrinth_exact",
                                "project": matched_slug or pid,
                            },
                        )
                        if pack_matched:
                            result.pack_only.append(row)
                        else:
                            result.no_source.append(row)
                        continue
                else:
                    installed_ver = mod.version
                    # Prefer version object that lists our filename if present
                    installed_vid = None
                    for v in versions:
                        for ff in v.get("files") or []:
                            if (ff.get("filename") or "") == mod.jar_name:
                                installed_vid = v.get("id")
                                installed_ver = v.get("version_number") or installed_ver
                                break
                    upd, reason = modrinth.choose_update(
                        installed_ver,
                        installed_vid,
                        versions,
                        installed_filename=mod.jar_name,
                        game=mc,
                    )
                    if not upd:
                        result.current.append(
                            {
                                "jar": mod.jar_name,
                                "source": "modrinth",
                                "project": matched_slug or pid,
                                "reason": reason,
                                "version": installed_ver,
                                "resolve": "exact_modid_or_stem",
                            }
                        )
                        continue
                    f = modrinth.pick_primary_jar_file(upd)
                    if not f:
                        result.errors.append({"jar": mod.jar_name, "err": "no_file"})
                        continue
                    new_name = safe_jar_filename(f["filename"])
                    if not new_name:
                        result.errors.append({"jar": mod.jar_name, "err": "unsafe_filename"})
                        continue
                    url = f["url"]
                    if new_name == mod.jar_name:
                        result.current.append(
                            {
                                "jar": mod.jar_name,
                                "source": "modrinth",
                                "reason": "same_filename",
                                "resolve": "exact_modid_or_stem",
                            }
                        )
                        continue
                    if download:
                        dest = safe_jar_path(jars_dir, new_name)
                        if dest is None:
                            result.errors.append({"jar": mod.jar_name, "err": "unsafe_filename"})
                            continue
                        if not _stage_jar(url, dest, ua=httputil.DEFAULT_UA, label=new_name):
                            result.errors.append(
                                {"jar": mod.jar_name, "err": "tiny_download", "url": url}
                            )
                            continue
                    rep = Replacement(
                        jar_name=mod.jar_name,
                        new_jar=new_name,
                        old_version=installed_ver,
                        new_version=upd.get("version_number"),
                        channel=modrinth.version_channel(upd),
                        source="modrinth",
                        reason=reason + "_exact_project",
                        url=url,
                        modid=mod.modid,
                        display_name=mod.display_name or proj.get("title"),
                        project=proj.get("slug") or matched_slug or pid,
                    )
                    result.updates.append(rep)
                    pending_mr_titles.append((rep, pid))
                    continue

            if not cf_info:
                # Cascade failed. Structured uncheckable (never claim current/latest).
                notes = list(
                    cascade_notes.get(mod.jar_name)
                    or ["no_mr_hash", "no_pack_cf", "mr_project_not_found"]
                )
                notes = [c for c in notes if c not in ("mr_exact_hit", "fingerprint_hit")]
                if not api_key and "fingerprint_no_key" not in notes:
                    notes.append("fingerprint_no_key")
                pack_matched = bool(entry) and not pack_manifest.has_curseforge_project(entry)
                if pack_matched:
                    pack_sha = pack_manifest.pack_file_sha1(entry)
                    pack_name = str(entry.get("name") or "")
                    pack_url = pack_manifest.pack_file_url(entry)
                    # True FTB-private heuristic: FTB-prefixed modid/stem + no public resolve.
                    # Public mirrors (e.g. rgp-client) stay uncheckable without this label.
                    stem = pack_manifest.product_stem(mod.jar_name)
                    looks_ftb = any(
                        (s or "").lower().startswith("ftb")
                        for s in (mod.modid, stem, pack_name)
                    )
                    if looks_ftb and "mr_project_not_found" in notes:
                        if "ftb_private_blob" not in notes:
                            notes.append("ftb_private_blob")
                        if "pack_ftb_only" not in notes:
                            notes.append("pack_ftb_only")
                    if pack_sha and mod.sha1.lower() == pack_sha:
                        if "pack_pin_match" not in notes:
                            notes.append("pack_pin_match")
                        result.pack_only.append(
                            _uncheckable_row(
                                jar=mod.jar_name,
                                modid=mod.modid,
                                codes=notes,
                                pack_matched=True,
                                pack_file=pack_name or None,
                                version=mod.version,
                                extra={"source": "pack_ftb", "status": "pack_pin_match"},
                            )
                        )
                        continue
                    # Local SHA differs. Optional re-sync to pack URL only (not latest).
                    if pack_url and pack_name:
                        pack_name = safe_jar_filename(pack_name) or ""
                        if not pack_name:
                            result.errors.append(
                                {
                                    "jar": mod.jar_name,
                                    "err": "unsafe_filename",
                                    "reason": "pack_ftb_only",
                                }
                            )
                            continue
                        if download:
                            dest = safe_jar_path(jars_dir, pack_name)
                            if dest is None:
                                result.errors.append(
                                    {
                                        "jar": mod.jar_name,
                                        "err": "unsafe_filename",
                                        "reason": "pack_ftb_only",
                                    }
                                )
                                continue
                            try:
                                ok = _stage_jar(
                                    pack_url,
                                    dest,
                                    ua=httputil.DEFAULT_UA,
                                    label=pack_name,
                                )
                            except Exception as e:
                                result.errors.append(
                                    {
                                        "jar": mod.jar_name,
                                        "err": str(e),
                                        "url": pack_url,
                                        "reason": "pack_ftb_only",
                                    }
                                )
                                continue
                            if not ok:
                                result.errors.append(
                                    {
                                        "jar": mod.jar_name,
                                        "err": "tiny_download",
                                        "url": pack_url,
                                        "reason": "pack_ftb_only",
                                    }
                                )
                                continue
                        pin_ver = str(entry.get("version") or "")
                        if pin_ver in ("", "0"):
                            pin_ver = mod.version or pin_ver
                        result.updates.append(
                            Replacement(
                                jar_name=mod.jar_name,
                                new_jar=pack_name,
                                old_version=mod.version,
                                new_version=pin_ver or None,
                                channel=None,
                                source="pack_ftb",
                                reason="pack_ftb_only_pin_refresh",
                                url=pack_url,
                                modid=mod.modid,
                                display_name=mod.display_name,
                                project="pack:ftb",
                            )
                        )
                        continue
                    result.pack_only.append(
                        _uncheckable_row(
                            jar=mod.jar_name,
                            modid=mod.modid,
                            codes=notes + ["pack_pin_unresolved"],
                            pack_matched=True,
                            pack_file=pack_name or None,
                            version=mod.version,
                            extra={
                                "source": "pack_ftb",
                                "status": "pack_pin_unresolved",
                                "note": "sha_differs_from_pack_pin",
                            },
                        )
                    )
                    continue
                # No pack row either
                if "no_modrinth_hash_and_no_pack_cf" not in notes:
                    notes.append("no_modrinth_hash_and_no_pack_cf")
                result.no_source.append(
                    _uncheckable_row(
                        jar=mod.jar_name,
                        modid=mod.modid,
                        codes=notes,
                        pack_matched=False,
                        version=mod.version,
                    )
                )
                continue

            project_id, file_id = cf_info
            files = cf_files_cache.get(project_id)
            if files is None:
                files = curseforge.list_cf_files(project_id, mc, loader=loader)
                cf_files_cache[project_id] = files
            if not files:
                no_key = not curseforge.resolve_api_key()
                codes = ["cf_no_key"] if no_key else ["no_files"]
                result.pack_only.append(
                    _uncheckable_row(
                        jar=mod.jar_name,
                        modid=mod.modid,
                        codes=codes,
                        pack_matched=bool(
                            entry and pack_manifest.has_curseforge_project(entry)
                        ),
                        version=mod.version,
                        extra={"source": "curseforge", "project": project_id},
                    )
                )
                continue
            # Prefer the CF file id for the jar actually installed (not only pack pin).
            for f in files:
                if (f.get("fileName") or "") == mod.jar_name:
                    file_id = int(f["id"])
                    break
            upd, reason = curseforge.pick_update(
                files,
                game=mc,
                loader=loader,
                installed_file_id=file_id,
                installed_name=mod.jar_name,
                installed_ver=mod.version,
            )
            if not upd:
                result.current.append(
                    {
                        "jar": mod.jar_name,
                        "source": "curseforge",
                        "project": project_id,
                        "reason": reason,
                        "resolve": "fingerprint" if mod.jar_name in fp_cf_for else "pack_cf",
                    }
                )
                continue
            new_name = safe_jar_filename(upd["fileName"])
            if not new_name:
                result.errors.append({"jar": mod.jar_name, "err": "unsafe_filename"})
                continue
            new_id = int(upd["id"])
            got = curseforge.resolve_download(project_id, new_id, new_name)
            if not got.url:
                codes = (
                    ["cf_no_key"]
                    if not curseforge.resolve_api_key()
                    else ["cf_no_download_url"]
                )
                result.pack_only.append(
                    _uncheckable_row(
                        jar=mod.jar_name,
                        modid=mod.modid,
                        codes=codes,
                        pack_matched=bool(
                            entry and pack_manifest.has_curseforge_project(entry)
                        ),
                        version=mod.version,
                        extra={"source": "curseforge", "project": project_id},
                    )
                )
                continue
            url = got.url
            if download:
                dest = safe_jar_path(jars_dir, new_name)
                if dest is None:
                    result.errors.append({"jar": mod.jar_name, "err": "unsafe_filename"})
                    continue
                try:
                    ok = _stage_jar(
                        url,
                        dest,
                        ua=got.ua,
                        label=new_name,
                        alt_url=got.alt_url,
                    )
                except Exception as e:
                    result.errors.append({"jar": mod.jar_name, "err": str(e), "url": url})
                    continue
                if not ok:
                    result.errors.append(
                        {"jar": mod.jar_name, "err": "tiny_download", "url": url}
                    )
                    continue
            src_reason = reason
            if mod.jar_name in fp_cf_for and mod.jar_name not in cf_pid_for_mod:
                src_reason = reason + "_fingerprint"
            result.updates.append(
                Replacement(
                    jar_name=mod.jar_name,
                    new_jar=new_name,
                    old_version=mod.version,
                    new_version=curseforge.version_guess(
                        new_name, upd.get("displayName") or ""
                    ),
                    channel=curseforge.channel_of_file(upd),
                    source="curseforge",
                    reason=src_reason,
                    url=url,
                    modid=mod.modid,
                    display_name=mod.display_name,
                    project=f"cf:{project_id}",
                )
            )
        except Exception as e:
            result.errors.append({"jar": mod.jar_name, "err": str(e)})

    _satisfy_mandatory_deps(
        mods=mods,
        result=result,
        jars_dir=jars_dir,
        by_hash=by_hash,
        versions_cache=versions_cache,
        cf_files_cache=cf_files_cache,
        cf_pid_for_mod=cf_pid_for_mod,
        fp_cf_for=fp_cf_for,
        mr_exact_for=mr_exact_for,
        mc=mc,
        loader=loader,
        download=download,
        stage_jar=_stage_jar,
        pending_mr_titles=pending_mr_titles,
        log=log,
    )

    # Titles/slugs only for Modrinth updates (not every known jar)
    if pending_mr_titles:
        need = sorted({pid for _, pid in pending_mr_titles})
        proj_meta = modrinth.prefetch_projects(need, max_workers=6)
        for rep, pid in pending_mr_titles:
            proj = proj_meta.get(pid) or {}
            if proj.get("title") and not rep.display_name:
                rep.display_name = proj.get("title")
            if proj.get("slug"):
                rep.project = proj["slug"]

    _attach_error_layman(result)
    check_line.end(f"  Check done in {time.monotonic() - t_check:.1f}s")

    # After staging, re-read downloaded jars for higher NeoForge floors
    from .versions import neoforge_floor_for_mc, neoforge_tuple

    floors: list[str] = []
    base_floor = neoforge_floor_for_mc(result.min_neoforge_floor, mc)
    if base_floor:
        floors.append(base_floor)
    for rep in result.updates:
        p = safe_jar_path(jars_dir, rep.new_jar)
        if p is None or not p.is_file():
            continue
        meta = read_mod_metadata(p)
        rng = meta.get("loaderVersion")
        if not rng:
            continue
        probe = InstalledMod(
            jar_name=rep.new_jar,
            path=p,
            sha1="",
            size=p.stat().st_size,
            loader_version_range=rng,
        )
        f = neoforge_floor_for_mc(min_neoforge_from_ranges([probe]), mc)
        if f:
            floors.append(f)
    if floors:
        floors.sort(key=lambda v: neoforge_tuple(v) or (0,))
        result.min_neoforge_floor = floors[-1]
    else:
        result.min_neoforge_floor = None

    # write artifacts
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = work / f"report-{stamp}.json"
    manifest_path = work / "manifest.json"
    report_md = work / f"report-{stamp}.md"

    report_obj = {
        "instance": result.instance,
        "mc_version": result.mc_version,
        "loader": result.loader,
        "mod_loader": result.mod_loader,
        "checked": result.checked,
        "updates": [asdict(u) for u in result.updates],
        "downloaded": result.downloaded,
        "downloaded_files": result.downloaded_files,
        "cached_jars": result.cached_jars,
        "cached_files": result.cached_files,
        "current": result.current,
        "pack_only": result.pack_only,
        "no_source": result.no_source,
        "errors": result.errors,
        "min_neoforge_floor": result.min_neoforge_floor,
        "pack_neoforge": result.pack_neoforge,
        "policy": (
            "Prefer release for this MC+loader. Beta/alpha only when that is the only channel. "
            "CurseForge uses the official Core API when CURSEFORGE_API_KEY / --cf-api-key is "
            "set (file list, download URL, optional fingerprint). Project ids may come from "
            "the FTB pack JSON or a fingerprint hit. current = checked Modrinth/CurseForge "
            "and already on the newest eligible build. pack_only / uncheckable = latest was "
            "not checked: cascade was exact Modrinth GET by modid/stem, then optional CF "
            "fingerprint; failures carry reason codes (not free-text search). Matching the "
            "pack pin is never treated as up to date. Optional pack re-sync when local SHA "
            "differs restores the pack file only. After per-jar picks, mandatory inter-mod "
            "versionRange on staged and remaining installed jars can pull a newer eligible "
            "companion already in the instance."
        ),
        "cascade": (
            "no_mr_hash + no_pack_cf → exact Modrinth GET /project/{modid|stem} → "
            "optional CF fingerprint (API key) → uncheckable with why"
        ),
    }
    report_path.write_text(json.dumps(report_obj, indent=2), encoding="utf-8")
    (work / "report-latest.json").write_text(json.dumps(report_obj, indent=2), encoding="utf-8")

    manifest = {
        "instance_mods": str(inst.mods_dir),
        "work_root": str(work),
        "new_jars_dir": str(jars_dir),
        "backup_dir": str(work / "backup"),
        "game": mc,
        "loader": loader,
        "replacements": [
            {
                "modid": u.modid,
                "name": u.display_name or u.jar_name,
                "old_jar": u.jar_name,
                "new_jar": u.new_jar,
                "old_version": u.old_version,
                "new_version": u.new_version,
                "channel": u.channel,
                "source": u.source,
            }
            for u in result.updates
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        f"# FTB instance update report",
        "",
        f"- Instance: `{result.instance}`",
        f"- MC / loader: {result.mc_version} / {result.mod_loader}",
        f"- Checked: {result.checked}",
        f"- **Updates: {len(result.updates)}** "
        f"(downloaded this run: {result.downloaded}, already in work/jars: {result.cached_jars})",
        f"- Already on latest checked (Modrinth/CurseForge): {len(result.current)}",
        f"- Uncheckable (latest not checked): {len(result.pack_only)}",
        f"- No Modrinth/CF source: {len(result.no_source)}",
        f"- Errors: {len(result.errors)}",
        f"- Min NeoForge floor (from mod metadata): {result.min_neoforge_floor or 'n/a'}",
        f"- Pack NeoForge: {result.pack_neoforge or 'n/a'}",
        "",
        "## Updates",
    ]
    from .versions import display_version

    for u in sorted(result.updates, key=lambda x: (x.display_name or x.jar_name).lower()):
        old_v = display_version(u.old_version, u.jar_name)
        new_v = display_version(u.new_version, u.new_jar)
        if u.reason == "pack_ftb_only_pin_refresh":
            lines.append(
                f"- **{u.display_name or u.jar_name}** [FTB pack re-sync, not a latest check]: "
                f"`{old_v}` → pack `{new_v}`  \n"
                f"  `{u.jar_name}` → `{u.new_jar}` ({u.reason})"
            )
        else:
            lines.append(
                f"- **{u.display_name or u.jar_name}** [{u.source}/{u.channel}]: "
                f"`{old_v}` → `{new_v}`  \n"
                f"  `{u.jar_name}` → `{u.new_jar}` ({u.reason})"
            )
    lines += [
        "",
        "## Uncheckable (latest not checked)",
        "",
        "These jars were not confirmed current on Modrinth or CurseForge. "
        "After a missing Modrinth hash and no pack CurseForge project id, the tool "
        "tries exact Modrinth GET /project/{modid-or-stem} (no search), then optional "
        "CurseForge fingerprint when an API key is set. Matching the pack pin is not "
        "\"up to date.\"",
        "",
    ]
    if not result.pack_only:
        lines.append("- (none)")
    else:
        for n in result.pack_only:
            note = n.get("layman") or n.get("reason") or "latest not checked"
            codes = n.get("reasons") or ([n.get("reason")] if n.get("reason") else [])
            code_s = ", ".join(str(c) for c in codes if c)
            extra = f"  codes: `{code_s}`" if code_s else ""
            lines.append(f"- `{n.get('jar')}`: {note}" + (f"\n  {extra}" if extra else ""))
    lines += ["", "## No source"]
    for n in result.no_source[:50]:
        note = n.get("layman") or n.get("reason")
        codes = n.get("reasons") or ([n.get("reason")] if n.get("reason") else [])
        code_s = ", ".join(str(c) for c in codes if c)
        lines.append(
            f"- `{n.get('jar')}`: {note}" + (f" (`{code_s}`)" if code_s else "")
        )
    if len(result.no_source) > 50:
        lines.append(f"- ... and {len(result.no_source) - 50} more")
    lines += [
        "",
        "## Errors",
        "",
        "Problems found during check. This is not a count of failed downloads. "
        "This tool does not add mods that are not already in the instance.",
        "",
    ]
    if not result.errors:
        lines.append("- (none)")
    else:
        for e in result.errors:
            note = e.get("layman") or error_layman(e)
            jar = e.get("jar") or "?"
            err = e.get("err") or "?"
            bits = [f"`{err}`"]
            if e.get("modid"):
                bits.append(f"need `{e['modid']}`")
            if e.get("range"):
                bits.append(f"`{e['range']}`")
            if e.get("requested_by"):
                bits.append(f"from `{e['requested_by']}`")
            if e.get("actual") not in (None, ""):
                bits.append(f"have `{e['actual']}`")
            lines.append(f"- {note}")
            lines.append(f"  `{jar}` ({', '.join(bits)})")
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (work / "report-latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result, work


def _file_locked(path: Path) -> bool:
    """True if another process holds the file (Windows sharing violation)."""
    if not path.is_file():
        return False
    try:
        # exclusive open. Fails with WinError 32 when Minecraft/FTB has the jar mapped
        with open(path, "r+b"):
            pass
        return False
    except OSError as e:
        win = getattr(e, "winerror", None)
        if win == 32 or e.errno in (11, 13, 16):  # EAGAIN / EACCES / EBUSY
            return True
        # Permission denied can also mean lock on some setups
        if isinstance(e, PermissionError):
            return True
        return False


def _locking_process_hints() -> list[str]:
    """Best-effort list of Java/FTB process names that often lock mod jars."""
    import subprocess
    import sys

    hints: list[str] = []
    if sys.platform != "win32":
        return hints
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        text = (r.stdout or "").lower()
        for name in (
            "javaw.exe",
            "java.exe",
            "ftbapp.exe",
            "ftb app.exe",
            "minecraft",
        ):
            if name.replace(" ", "") in text.replace(" ", "") or name in text:
                hints.append(name)
    except Exception:
        pass
    return sorted(set(hints))


def apply_manifest(
    work_root: Path | None = None,
    *,
    manifest_path: Path | None = None,
    log: LogFn | None = None,
    retries: int = 3,
    retry_delay_s: float = 1.5,
) -> dict[str, int]:
    work = work_root or default_work_root()
    mp = manifest_path or (work / "manifest.json")
    if not mp.is_file():
        raise SystemExit(f"Missing manifest: {mp}")
    manifest = json.loads(mp.read_text(encoding="utf-8-sig"))
    mods_dir = Path(manifest["instance_mods"])
    jars_dir = Path(manifest["new_jars_dir"])
    backup_root = Path(manifest.get("backup_dir") or (work / "backup"))

    replacements = list(manifest.get("replacements") or [])
    if not replacements:
        _log("APPLY: nothing in manifest", log)
        return {"applied": 0, "skipped": 0, "failed": 0}

    # Preflight: any locked jar → stop before partial apply
    locked = []
    for rep in replacements:
        for name in (rep.get("old_jar"), rep.get("new_jar")):
            if not name:
                continue
            p = safe_jar_path(mods_dir, name)
            if p is None:
                continue
            if _file_locked(p):
                locked.append(str(p))
    if locked:
        hints = _locking_process_hints()
        _log(
            "APPLY blocked: mod jars are locked by another process "
            "(usually Minecraft or FTB App with the instance open).",
            log,
        )
        if hints:
            _log(f"  Possible holders: {', '.join(hints)}", log)
        _log("  Close the game (and FTB App if it keeps files open), then run:", log)
        _log("    .\\run.cmd apply", log)
        _log(f"  Locked examples ({min(5, len(locked))} of {len(locked)}):", log)
        for p in locked[:5]:
            _log(f"    {p}", log)
        return {"applied": 0, "skipped": 0, "failed": len(replacements), "blocked_locked": len(locked)}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_root / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    applied = skipped = failed = 0
    for rep in replacements:
        old_name = safe_jar_filename(rep["old_jar"])
        new_name = safe_jar_filename(rep["new_jar"])
        if not old_name or not new_name:
            _log(f"SKIP unsafe jar name in manifest: {rep.get('old_jar')!r} -> {rep.get('new_jar')!r}", log)
            failed += 1
            continue
        old_path = safe_jar_path(mods_dir, old_name)
        new_path = safe_jar_path(jars_dir, new_name)
        dest_path = safe_jar_path(mods_dir, new_name)
        if old_path is None or new_path is None or dest_path is None:
            _log(f"SKIP unsafe jar path: {old_name} -> {new_name}", log)
            failed += 1
            continue
        if not new_path.is_file():
            _log(f"MISSING new jar: {new_name}", log)
            failed += 1
            continue
        if not old_path.is_file():
            if dest_path.is_file():
                _log(f"SKIP already present: {new_name}", log)
                skipped += 1
                continue
            try:
                shutil.copy2(new_path, dest_path)
                _log(f"INSTALL only: {new_name}", log)
                applied += 1
            except Exception as e:
                _log(f"FAIL install {new_name}: {e}", log)
                failed += 1
            continue

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                shutil.move(str(old_path), str(backup_dir / old_name))
                if dest_path.is_file() and dest_path.resolve() != old_path.resolve():
                    shutil.move(str(dest_path), str(backup_dir / f"collide-{new_name}"))
                shutil.copy2(new_path, dest_path)
                _log(f"OK {rep.get('name') or old_name}: {old_name} -> {new_name}", log)
                applied += 1
                last_err = None
                break
            except Exception as e:
                last_err = e
                # restore if we moved old and failed mid-way
                bak = backup_dir / old_name
                if bak.is_file() and not old_path.is_file():
                    try:
                        shutil.move(str(bak), str(old_path))
                    except Exception:
                        pass
                win = getattr(e, "winerror", None)
                if win == 32 or _file_locked(old_path):
                    if attempt < retries:
                        time.sleep(retry_delay_s)
                        continue
                break
        if last_err is not None:
            _log(f"FAIL {old_name}: {last_err}", log)
            failed += 1

    _log(
        f"APPLY done applied={applied} skipped={skipped} failed={failed} backup={backup_dir}",
        log,
    )
    if failed and applied == 0:
        _log(
            "Hint: close Minecraft / leave the instance, then: .\\run.cmd apply",
            log,
        )
    return {"applied": applied, "skipped": skipped, "failed": failed}


def upgrade_neoforge(
    inst: Instance,
    *,
    target: str | None = None,
    floor: str | None = None,
    work_root: Path | None = None,
    ftba_root: Path | None = None,
    log: LogFn | None = None,
) -> str:
    root = ftba_root or default_ftba_root()
    work = work_root or default_work_root()
    work.mkdir(parents=True, exist_ok=True)
    mc = inst.mc_version
    current = inst.neoforge_version
    if not target:
        target = neoforge.latest_for_mc(mc)
    if not target:
        raise SystemExit(f"No NeoForge release found on Maven for MC {mc}")
    if floor and not neoforge.needs_upgrade(current, floor, target):
        # still ensure target >= floor
        from .versions import neoforge_gte

        if current and neoforge_gte(current, floor):
            _log(f"NeoForge {current} already satisfies floor {floor}", log)
            return current or target
    if current == target:
        _log(f"Already on NeoForge {target}; re-installing client profile if needed", log)

    _log(f"NeoForge upgrade: {current} -> {target} (floor={floor})", log)
    installer = work / f"neoforge-{target}-installer.jar"
    if not installer.is_file() or installer.stat().st_size < 1000:
        _log(f"Downloading installer {target}...", log)
        neoforge.download_installer(target, installer)
    java = neoforge.find_java(root)
    _log(f"Java: {java}", log)
    bdir = bin_dir(root)
    # backup instance metadata
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = work / f"neoforge-backup-{stamp}"
    bak.mkdir(parents=True, exist_ok=True)
    shutil.copy2(inst.instance_json, bak / "instance.json")
    if inst.modifications_json.is_file():
        shutil.copy2(inst.modifications_json, bak / "modifications.json")
    ver_json = neoforge.install_client(
        java=java,
        installer_jar=installer,
        bin_dir=bdir,
        work_dir=work / "neoforge-install",
        mc_version=mc,
    )
    _log(f"Installed profile: {ver_json}", log)
    neoforge.patch_instance_loader(inst.instance_json, f"neoforge-{target}", target)
    _log(f"Patched instance.json modLoader -> neoforge-{target}", log)
    _log(f"Backup: {bak}", log)
    return target
