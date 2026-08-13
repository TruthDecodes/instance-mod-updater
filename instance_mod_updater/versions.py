from __future__ import annotations

import re


# Leading modern Minecraft in MC-first version strings (26.1.2-1.4.97, 1.21.1-3.2.0).
_MODERN_MC_PREFIX_RE = re.compile(
    r"^((?:1\.(?:1[6-9]|2\d)|26)\.\d+(?:\.\d+)?)[\+\-_]"
)
# Trailing 2–3 component 1.x / 26.x (product-then-MC, e.g. 3.25.86-1.21.1).
_TRAILING_MC_RE = re.compile(r"[\+\-_]((?:1|26)\.\d+(?:\.\d+)?(?:\.x)?)$")


def _looks_like_modern_mc(tag: str) -> bool:
    """True for 1.16–1.2x.y or 26.x.y (2–3 numeric components, optional .x)."""
    t = (tag or "").strip().lower()
    if t.endswith(".x"):
        t = t[:-2]
    parts = _parse_mc_tuple(t)
    if not parts or not (2 <= len(parts) <= 3):
        return False
    if parts[0] >= 26:
        return True
    return parts[0] == 1 and parts[1] >= 16


def parse_ver(s: str) -> tuple[tuple[int, ...], int, int]:
    """Return (base_nums, pre_rank, pre_num). pre_rank: 0=release, 1=rc/pre, 2=beta, 3=alpha."""
    s = (s or "").strip().lower()
    s = re.sub(r"[\+\-_]?(neoforge|forge|fabric|quilt)\b.*$", "", s)
    s = re.sub(r"[\+\-]?mc[\d.]+", "", s)
    # Strip trailing Minecraft only for product-then-MC names. Do not strip
    # MC-first strings (26.1.2-1.4.97.2247) or 4-part product/builds.
    if not _MODERN_MC_PREFIX_RE.match(s):
        s = _TRAILING_MC_RE.sub(
            lambda m: "" if _looks_like_modern_mc(m.group(1)) else m.group(0),
            s,
        )
    s = s.strip(" -_+.")
    s = re.sub(r"^v", "", s)
    pre_rank = 0
    pre_num = 0
    mpre = re.search(r"[-_.]?(alpha|beta|rc|pre)[.-]?(\d*)", s)
    if mpre:
        kind = mpre.group(1)
        pre_num = int(mpre.group(2) or "0")
        pre_rank = {"rc": 1, "pre": 1, "beta": 2, "alpha": 3}[kind]
        s = s[: mpre.start()]
    nums = tuple(int(x) for x in re.findall(r"\d+", s))
    return nums, pre_rank, pre_num


def is_newer(remote_ver: str, installed_ver: str) -> bool | None:
    """True if remote > installed. None if incomparable."""
    rb, rr, rn = parse_ver(remote_ver)
    ib, ir, in_ = parse_ver(installed_ver)
    if not rb or not ib:
        return None
    n = max(len(rb), len(ib))
    rb2 = rb + (0,) * (n - len(rb))
    ib2 = ib + (0,) * (n - len(ib))
    if rb2 != ib2:
        return rb2 > ib2
    if rr != ir:
        return rr < ir
    if rn != in_:
        return rn > in_
    return False


def product_version(s: str) -> str:
    """Drop a leading modern MC prefix so Maven ranges see the product version."""
    raw = (s or "").strip()
    if not raw:
        return ""
    m = _MODERN_MC_PREFIX_RE.match(raw.lower())
    if not m:
        return raw
    return raw[m.end() :].strip(" -_+.")


def cmp_ver(a: str, b: str) -> int | None:
    """-1 / 0 / 1, or None if either side has no numeric version."""
    ab, ar, an = parse_ver(a)
    bb, br, bn = parse_ver(b)
    if not ab or not bb:
        return None
    n = max(len(ab), len(bb))
    a2 = ab + (0,) * (n - len(ab))
    b2 = bb + (0,) * (n - len(bb))
    if a2 != b2:
        return 1 if a2 > b2 else -1
    if ar != br:
        return -1 if ar > br else 1
    if an != bn:
        return 1 if an > bn else -1
    return 0


def _maven_interval_contains(ver: str, spec: str) -> bool | None:
    spec = (spec or "").strip()
    if len(spec) < 3 or spec[0] not in "[(" or spec[-1] not in "])":
        return None
    lo_inc = spec[0] == "["
    hi_inc = spec[-1] == "]"
    inner = spec[1:-1].strip()
    if "," not in inner:
        bound = inner.strip()
        if not bound:
            return None
        c = cmp_ver(ver, bound)
        return None if c is None else c == 0
    left, right = inner.split(",", 1)
    left, right = left.strip(), right.strip()
    if left:
        c = cmp_ver(ver, left)
        if c is None:
            return None
        if c < 0 or (c == 0 and not lo_inc):
            return False
    if right:
        c = cmp_ver(ver, right)
        if c is None:
            return None
        if c > 0 or (c == 0 and not hi_inc):
            return False
    return True


def version_in_maven_range(ver: str, range_s: str) -> bool | None:
    """True if ver satisfies a Forge/NeoForge Maven versionRange. None if unparseable."""
    ver_p = product_version(ver)
    range_s = (range_s or "").strip()
    if not ver_p or not range_s or ver_p.startswith("${"):
        return None
    intervals = re.findall(
        r"[\[\(][^\[\]\(\),]*,[^\[\]\(\)]*[\]\)]|[\[\(][^\[\]\(\),]+[\]\)]",
        range_s,
    )
    if not intervals:
        return None
    saw_decided = False
    for iv in intervals:
        hit = _maven_interval_contains(ver_p, iv)
        if hit is True:
            return True
        if hit is False:
            saw_decided = True
    return False if saw_decided else None


def is_prerelease_label(s: str) -> bool:
    s = (s or "").lower()
    return bool(
        re.search(
            r"(^|[^a-z])(alpha|beta|rc\d*|snapshot|pre|preview|nightly|wip|experimental)([^a-z]|$)",
            s,
        )
    )


def neoforge_tuple(ver: str) -> tuple[int, ...] | None:
    """Parse NeoForge version like 26.1.2.94 -> (26,1,2,94)."""
    m = re.match(r"^(\d+(?:\.\d+)+)$", (ver or "").strip())
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split("."))


def neoforge_gte(a: str, b: str) -> bool:
    ta, tb = neoforge_tuple(a), neoforge_tuple(b)
    if not ta or not tb:
        return False
    n = max(len(ta), len(tb))
    ta2 = ta + (0,) * (n - len(ta))
    tb2 = tb + (0,) * (n - len(tb))
    return ta2 >= tb2


def neoforge_gt(a: str, b: str) -> bool:
    ta, tb = neoforge_tuple(a), neoforge_tuple(b)
    if not ta or not tb:
        return False
    n = max(len(ta), len(tb))
    ta2 = ta + (0,) * (n - len(ta))
    tb2 = tb + (0,) * (n - len(tb))
    return ta2 > tb2


def matches_mc_line(nf_ver: str, mc_version: str) -> bool:
    """NeoForge 26.1.2.x matches MC 26.1.2; do not pull 26.2.x for 26.1.2."""
    nf = (nf_ver or "").strip()
    mc = (mc_version or "").strip()
    if not nf or not mc:
        return False
    # exact prefix: 26.1.2.94 for mc 26.1.2
    if nf == mc or nf.startswith(mc + "."):
        return True
    # also allow 26.1.x style when mc is 26.1.2 if first two match and third is same
    parts_nf = nf.split(".")
    parts_mc = mc.split(".")
    if len(parts_mc) >= 3 and len(parts_nf) >= 3:
        return parts_nf[:3] == parts_mc[:3]
    return False


# Minecraft game versions that appear in jar names / CF tags (not mod product versions).
_MC_TAG_RE = re.compile(
    r"(?<![\d.])((?:1\.\d+\.\d+)|(?:2[0-9]\.\d+(?:\.\d+)?))(?![\d.])"
)


def exact_game_in_tags(tags: list[str] | None, game: str) -> bool:
    """True if metadata lists this exact Minecraft version (no 1.20 ≈ 1.20.4)."""
    g = (game or "").strip()
    if not g:
        return False
    for t in tags or []:
        if str(t).strip() == g:
            return True
    return False


def _parse_mc_tuple(ver: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(x) for x in (ver or "").split("."))
    except ValueError:
        return None


def _is_conflicting_mc_tag(tag: str, game: str) -> bool:
    """
    True if `tag` is a different Minecraft version that can confuse selection for `game`.

    Product versions often look like 1.x.y (e.g. Towns and Towers 1.13.1 in
    t_and_t-1.13.1b.jar). Those must not be treated as Minecraft 1.13.1 when the
    instance is on 1.20.4. Only flag tags that are plausible MC conflicts:
    same 1.XX line different patch, another modern 1.16–1.21 line, or 26.x.
    """
    if tag == game:
        return False
    # Broad prefix only (1.20 vs 1.20.4) is not a hard conflict by itself
    if game.startswith(tag + ".") or tag.startswith(game + "."):
        return False
    t, g = _parse_mc_tuple(tag), _parse_mc_tuple(game)
    if not t or not g:
        return False

    # New Minecraft numbering (26.x) vs classic 1.x, or different 26 lines
    if t[0] >= 26 or g[0] >= 26:
        return t != g

    if t[0] != 1 or g[0] != 1 or len(t) < 2 or len(g) < 2:
        return False

    t_minor, g_minor = t[1], g[1]
    # Same minor line, different patch: 1.20.1 vs 1.20.4
    if t_minor == g_minor:
        return t != g
    # Different minor: only modern MC minors (1.16+) — not product 1.5 / 1.12 / 1.13
    if t_minor >= 16 and g_minor >= 16:
        return True
    return False


def filename_targets_other_mc(filename: str, game: str) -> bool:
    """
    True if the jar name clearly names a different Minecraft version than `game`.
    e.g. game=1.20.4 and name has 1.20.1 / 1.20.6 / 1.21.8 → reject.
    Does not treat product versions like 1.13.1b as Minecraft 1.13.1.
    """
    g = (game or "").strip()
    fn = filename or ""
    if not g or not fn:
        return False
    for m in _MC_TAG_RE.finditer(fn):
        tag = m.group(1)
        if _is_conflicting_mc_tag(tag, g):
            return True
    return False


def neoforge_floor_for_mc(floor: str | None, mc_version: str) -> str | None:
    """Drop NeoForge floors that cannot apply to this MC line (e.g. 21.6 on 1.20.4)."""
    if not floor:
        return None
    if matches_mc_line(floor, mc_version):
        return floor
    # Classic NeoForge: 20.4.x for MC 1.20.4 (leading 1. stripped from MC)
    mc = (mc_version or "").strip()
    if mc.startswith("1.") and matches_mc_line(floor, mc[2:]):
        return floor
    return None
