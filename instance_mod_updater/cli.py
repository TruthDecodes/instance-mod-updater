from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, term
from .app_local import (
    default_ftba_root,
    default_work_root,
    list_instances,
    resolve_instance,
)
from .pipeline import CheckResult, apply_manifest, check_updates, error_layman, upgrade_neoforge


def _count(label: str, n: int, *, hot: str | None = None) -> str:
    """label=n with optional color when n > 0 (hot=green|cyan|yellow|red)."""
    text = f"{label}: {n}"
    if n <= 0 or not hot:
        return text
    paint = {
        "green": term.green,
        "cyan": term.cyan,
        "yellow": term.yellow,
        "red": term.red,
    }.get(hot)
    return paint(text) if paint else text


def _error_line(row: dict) -> str:
    return str(row.get("layman") or error_layman(row))


def _error_detail(row: dict) -> str:
    bits: list[str] = []
    if row.get("err"):
        bits.append(str(row["err"]))
    if row.get("modid"):
        bits.append(f"need {row['modid']}")
    if row.get("range"):
        bits.append(str(row["range"]))
    if row.get("requested_by"):
        bits.append(f"from {row['requested_by']}")
    if row.get("actual") not in (None, ""):
        bits.append(f"have {row['actual']}")
    jar = row.get("jar")
    if jar:
        bits.append(str(jar))
    return "  ".join(bits)


def _fetched_tag(result: CheckResult, new_jar: str) -> str:
    if new_jar in result.downloaded_files:
        return "downloaded"
    if new_jar in result.cached_files:
        return "already staged"
    return "listed"


def _neoforge_floor_line(floor: str, current: str | None) -> str:
    """Instance loader vs required floor. Belongs with the check headline, not the file footer."""
    if current:
        from .versions import neoforge_gte

        if neoforge_gte(current, floor):
            return (
                f"NeoForge {term.yellow(current)} meets floor {term.yellow(floor)}"
            )
        return term.warn(f"NeoForge {current} is below floor {floor}")
    return f"NeoForge floor: {term.yellow(floor)}"


def print_check_summary(
    result: CheckResult, work, *, current_neoforge: str | None = None
) -> None:
    """Counts plus the lists a person actually needs: every update, every error."""
    if result.min_neoforge_floor:
        print(_neoforge_floor_line(result.min_neoforge_floor, current_neoforge))
    parts = [
        _count("updates", len(result.updates), hot="cyan"),
        _count("downloaded", result.downloaded, hot="cyan"),
        _count("cached", result.cached_jars),
        _count("current", len(result.current), hot="green"),
        _count("uncheckable", len(result.pack_only), hot="yellow"),
        _count("no_source", len(result.no_source), hot="yellow"),
        _count("errors", len(result.errors), hot="red"),
    ]
    print("  ".join(parts))
    term.blank()

    if result.updates:
        from .versions import display_version

        print(term.cyan(f"Updates ({len(result.updates)})"))
        print(
            term.dim(
                "Newer jars are in the work folder. They are not in the instance "
                "until you run apply."
            )
        )
        for u in sorted(
            result.updates, key=lambda x: (x.display_name or x.jar_name).lower()
        ):
            name = u.display_name or u.modid or u.jar_name
            how = _fetched_tag(result, u.new_jar)
            old_v = display_version(u.old_version, u.jar_name)
            new_v = display_version(u.new_version, u.new_jar)
            print(f"  {name}  {old_v} → {new_v}  [{how}]")
            print(term.dim(f"    {u.jar_name} → {u.new_jar}"))
        term.blank()

    if result.pack_only:
        print(term.yellow(f"Uncheckable ({len(result.pack_only)})"))
        print(
            term.yellow(
                "Latest was not checked on Modrinth/CurseForge. "
                "That is not the same as up to date."
            )
        )
        for row in result.pack_only:
            why = row.get("layman") or row.get("reason") or ""
            print(term.dim(f"  {row.get('jar')}: {why}"))
        term.blank()

    if result.errors:
        print(term.red(f"Errors ({len(result.errors)})"))
        print(
            term.red(
                "These are problems the check found. "
                "They are not a count of failed downloads."
            )
        )
        for row in result.errors:
            print(term.red(f"  {_error_line(row)}"))
            detail = _error_detail(row)
            if detail:
                print(term.dim(f"    {detail}"))
        term.blank()

    print(term.dim(f"Work root: {work}"))
    print(term.dim(f"Manifest:  {work / 'manifest.json'}"))
    print(term.dim(f"Report:    {work / 'report-latest.md'}"))


def _peek_color(argv: list[str] | None) -> str:
    """Read --color before full parse so -h / --version are tinted."""
    if not argv:
        return "auto"
    for i, a in enumerate(argv):
        if a == "--color" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--color="):
            return a.split("=", 1)[1]
    return "auto"


class _ColorArgumentParser(argparse.ArgumentParser):
    def print_help(self, file=None) -> None:
        file = file or sys.stdout
        file.write(term.colorize_help(self.format_help()))
        file.flush()

    def print_usage(self, file=None) -> None:
        file = file or sys.stdout
        file.write(term.colorize_help(self.format_usage()))
        file.flush()

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, term.red(f"{self.prog}: error: {message}") + "\n")


class _VersionAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        print(term.cyan(f"{parser.prog} {__version__}"))
        parser.exit()


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--ftba-root",
        type=Path,
        default=None,
        help="FTB App data root (default: %%LOCALAPPDATA%%\\.ftba)",
    )
    p.add_argument(
        "--work-root",
        type=Path,
        default=None,
        help="Staging dir for jars/reports (default: %%PUBLIC%%\\instance-mod-updater)",
    )
    p.add_argument(
        "--instance",
        "-i",
        default=None,
        help="Instance folder name, display name substring, or full path",
    )
    p.add_argument(
        "--no-self-update",
        action="store_true",
        help="Do not refresh app code from GitHub before this command",
    )


def cmd_list(args: argparse.Namespace) -> int:
    root = args.ftba_root or default_ftba_root()
    insts = list_instances(root)
    if not insts:
        print(term.yellow(f"No instances under {root / 'instances'}"))
        return 1
    for i, inst in enumerate(insts):
        if i:
            term.blank()
        # Bright cyan title — bold-only is invisible on default dark PS themes
        print(term.cyan(inst.path.name))
        print(f"  {term.label('name', inst.name)}")
        print(
            f"  {term.label('mc', term.green(str(inst.mc_version)))}  "
            f"{term.label('loader', term.yellow(str(inst.mod_loader)))}"
        )
        print(
            f"  {term.label('pack_version', str(inst.pack_version_name))}  "
            f"{term.label('pack_id', str(inst.pack_id))}  "
            f"{term.label('version_id', str(inst.version_id))}"
        )
        print(term.dim(f"  path={inst.path}"))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = args.ftba_root or default_ftba_root()
    work = args.work_root or default_work_root()
    inst = resolve_instance(args.instance, root)
    print(f"{term.cyan('Instance:')} {term.cyan(inst.path.name)}")
    print(term.dim(str(inst.path)))
    print(
        f"MC={term.green(str(inst.mc_version))}  "
        f"loader={term.yellow(str(inst.mod_loader))}"
    )
    term.blank()
    result, work = check_updates(
        inst,
        work_root=work,
        pack_path=args.pack_json,
        pack_id=args.pack_id,
        version_id=args.version_id,
        download=not args.no_download,
        cf_api_key=getattr(args, "cf_api_key", None),
    )
    term.blank()
    print_check_summary(result, work, current_neoforge=inst.neoforge_version)
    return 0 if not result.errors else 1


def cmd_apply(args: argparse.Namespace) -> int:
    work = args.work_root or default_work_root()
    stats = apply_manifest(work, manifest_path=args.manifest)
    return 0 if stats["failed"] == 0 else 1


def cmd_upgrade_loader(args: argparse.Namespace) -> int:
    root = args.ftba_root or default_ftba_root()
    work = args.work_root or default_work_root()
    inst = resolve_instance(args.instance, root)
    floor = args.floor
    if args.floor_from_mods or floor is None:
        from .inventory import min_neoforge_from_ranges, scan_mods_dir

        mods = scan_mods_dir(inst.mods_dir, read_meta=True)
        detected = min_neoforge_from_ranges(mods)
        # also from latest report
        rep = work / "report-latest.json"
        if rep.is_file():
            data = json.loads(rep.read_text(encoding="utf-8-sig"))
            if data.get("min_neoforge_floor"):
                detected = data["min_neoforge_floor"] or detected
        floor = floor or detected
        print(f"Detected NeoForge floor: {floor}")
    if not args.force and floor:
        from .versions import neoforge_gte

        cur = inst.neoforge_version
        if cur and neoforge_gte(cur, floor):
            print(term.green(f"Already OK: NeoForge {cur} >= floor {floor}"))
            if not args.target:
                return 0
    target = upgrade_neoforge(
        inst,
        target=args.target,
        floor=floor,
        work_root=work,
        ftba_root=root,
    )
    term.blank()
    print(term.green(f"NeoForge now: {target}"))
    print(term.dim("Next: launch from FTB App; decline any offer to reinstall pack loader."))
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    """check (+download) → apply → upgrade NeoForge if floor requires it."""
    root = args.ftba_root or default_ftba_root()
    work = args.work_root or default_work_root()
    inst = resolve_instance(args.instance, root)
    print(term.section(f"=== check: {inst.path.name} ==="))
    result, work = check_updates(
        inst,
        work_root=work,
        pack_path=args.pack_json,
        pack_id=args.pack_id,
        version_id=args.version_id,
        download=True,
        cf_api_key=getattr(args, "cf_api_key", None),
    )
    term.blank()
    print_check_summary(result, work, current_neoforge=inst.neoforge_version)
    term.blank()
    if result.updates and not args.dry_run:
        print(term.section("=== apply ==="))
        stats = apply_manifest(work)
        if stats["failed"]:
            return 1
    elif result.updates and args.dry_run:
        print(term.dim(f"Dry-run: would apply {len(result.updates)} replacements"))
    else:
        print(term.dim("No mod jar updates to apply"))

    floor = result.min_neoforge_floor
    cur = inst.neoforge_version
    # reload instance after apply (loader unchanged yet)
    inst = resolve_instance(str(inst.path), root)
    cur = inst.neoforge_version
    need = False
    if floor and cur:
        from .versions import neoforge_gte

        need = not neoforge_gte(cur, floor)
    elif floor and not cur:
        need = True
    term.blank()
    if need or args.force_loader:
        if args.dry_run:
            latest = None
            try:
                from . import neoforge as nf

                latest = nf.latest_for_mc(inst.mc_version)
            except Exception:
                pass
            print(
                term.dim(
                    f"Dry-run: would upgrade NeoForge {cur} -> {latest} (floor {floor})"
                )
            )
        else:
            print(term.section("=== NeoForge upgrade ==="))
            upgrade_neoforge(
                inst,
                target=args.target,
                floor=floor,
                work_root=work,
                ftba_root=root,
            )
    else:
        print(term.green(f"NeoForge OK (current={cur}, floor={floor})"))
    term.blank()
    print(term.section("=== done ==="))
    return 0


def cmd_self_update(args: argparse.Namespace) -> int:
    from .self_update import main as self_update_main

    extra: list[str] = []
    if args.root:
        extra.extend(["--root", str(args.root)])
    if args.ref:
        extra.extend(["--ref", args.ref])
    if args.check_only:
        extra.append("--check-only")
    return self_update_main(extra)


def build_parser() -> argparse.ArgumentParser:
    p = _ColorArgumentParser(
        prog="instance-mod-updater",
        description=(
            "Unfinished experimental tool (not a release). Not an official Feed the Beast "
            "product. Update mods on an existing FTB App instance (pre-existing modlist). "
            "Modrinth public API. CurseForge official Core API when a key is set "
            "(file list, download URL, optional fingerprint). Optional NeoForge client "
            "install into FTB App bin."
        ),
    )
    p.add_argument("--version", action=_VersionAction, help="show program version and exit")
    p.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="ANSI colors: auto (default), always, never. Also NO_COLOR / FORCE_COLOR.",
    )
    p.add_argument(
        "--no-self-update",
        action="store_true",
        help="Do not refresh app code from GitHub before this command",
    )
    # required=False so bare `run.cmd` / no-args shows colored help instead of a hard error
    sub = p.add_subparsers(dest="cmd", required=False)

    pl = sub.add_parser("list", help="List FTB App instances")
    _add_common(pl)
    pl.set_defaults(func=cmd_list)

    pc = sub.add_parser("check", help="Scan instance mods; stage updates under work root")
    _add_common(pc)
    pc.add_argument("--pack-id", type=int, default=None, help="FTB modpack id (e.g. 132)")
    pc.add_argument("--version-id", type=int, default=None, help="FTB pack version id (e.g. 100392)")
    pc.add_argument("--pack-json", type=Path, default=None, help="Local FTB pack JSON instead of API")
    pc.add_argument(
        "--cf-api-key",
        default=None,
        help=(
            "CurseForge Core API key for file lists, download URLs, and fingerprint "
            "resolve. Env CURSEFORGE_API_KEY / CF_API_KEY also work. Without a key, "
            "CurseForge-only jars stay uncheckable."
        ),
    )
    pc.add_argument(
        "--no-download",
        action="store_true",
        help="Only write report/manifest; do not download jars",
    )
    pc.set_defaults(func=cmd_check)

    pa = sub.add_parser("apply", help="Apply staged replacements from manifest.json")
    _add_common(pa)
    pa.add_argument("--manifest", type=Path, default=None, help="Path to manifest.json")
    pa.set_defaults(func=cmd_apply)

    pu = sub.add_parser(
        "upgrade-loader",
        help="Install latest NeoForge for this MC into FTB bin and retarget instance",
    )
    _add_common(pu)
    pu.add_argument("--target", default=None, help="Exact NeoForge version (default: latest for MC)")
    pu.add_argument("--floor", default=None, help="Minimum NeoForge version required")
    pu.add_argument(
        "--floor-from-mods",
        action="store_true",
        help="Derive floor from installed/staged mod metadata and latest report",
    )
    pu.add_argument("--force", action="store_true", help="Install even if floor already met")
    pu.set_defaults(func=cmd_upgrade_loader)

    pall = sub.add_parser(
        "all",
        help="Check + download + apply + upgrade NeoForge if mod floor requires it",
    )
    _add_common(pall)
    pall.add_argument("--pack-id", type=int, default=None)
    pall.add_argument("--version-id", type=int, default=None)
    pall.add_argument("--pack-json", type=Path, default=None)
    pall.add_argument(
        "--cf-api-key",
        default=None,
        help="CurseForge Core API key (see check)",
    )
    pall.add_argument("--target", default=None, help="Pin NeoForge version")
    pall.add_argument("--dry-run", action="store_true", help="Check only; no apply/loader write")
    pall.add_argument(
        "--force-loader",
        action="store_true",
        help="Always run NeoForge install even if floor already met",
    )
    pall.set_defaults(func=cmd_all)

    ps = sub.add_parser(
        "self-update",
        help="Refresh app code from GitHub; leave runtime and work files alone",
    )
    ps.add_argument("--root", type=Path, default=None, help="Install folder (default: this checkout)")
    ps.add_argument("--ref", default=None, help="Branch, tag, or commit (default: GitHub default branch)")
    ps.add_argument("--check-only", action="store_true", help="Print status only")
    ps.set_defaults(func=cmd_self_update)

    return p


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # Before parse so -h / --version / usage errors are already tinted
    term.init(color=_peek_color(raw))
    parser = build_parser()
    try:
        args = parser.parse_args(raw)
    except SystemExit as e:
        # argparse already printed help/usage; preserve exit code
        code = e.code
        return int(code) if isinstance(code, int) else (0 if code is None else 1)

    term.init(color=getattr(args, "color", "auto"))
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print(term.yellow("Interrupted"), file=sys.stderr)
        return 130
    except SystemExit as e:
        code = e.code
        return int(code) if isinstance(code, int) else (0 if code is None else 1)
    except Exception as e:
        print(term.red(f"ERROR: {e}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
