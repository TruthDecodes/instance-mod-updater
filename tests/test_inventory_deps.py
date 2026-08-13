import unittest
import tempfile
from pathlib import Path

from instance_mod_updater.inventory import (
    InstalledMod,
    _parse_toml_simple,
    read_mod_metadata,
)
from instance_mod_updater.modrinth import choose_update, pick_version_satisfying_range
from instance_mod_updater.pipeline import CheckResult, _satisfy_mandatory_deps


TOML = """
modLoader = "javafml"
loaderVersion = "[1,)"

[[mods]]
modId = "sophisticatedbackpacks"
version = "3.25.86"
displayName = "Sophisticated Backpacks"

[[dependencies.sophisticatedbackpacks]]
    modId = "neoforge"
    type = "required"
    versionRange = "[26.1.2,)"
    ordering = "NONE"
    side = "BOTH"

[[dependencies.sophisticatedbackpacks]]
    modId = "sophisticatedcore"
    type = "required"
    versionRange = "[1.4.98,)"
    ordering = "NONE"
    side = "BOTH"

[[dependencies.sophisticatedbackpacks]]
    modId = "jei"
    mandatory = false
    versionRange = "[1.0,)"
    ordering = "NONE"
    side = "BOTH"
"""


class ParseDepsTests(unittest.TestCase):
    def test_required_inter_mod_only(self):
        parsed = _parse_toml_simple(TOML)
        self.assertEqual(parsed["modid"], "sophisticatedbackpacks")
        self.assertEqual(parsed["loaderVersion"], "[26.1.2,)")
        self.assertEqual(
            parsed["dependencies"],
            [{"modid": "sophisticatedcore", "versionRange": "[1.4.98,)"}],
        )

    def test_legacy_mandatory_true(self):
        text = """
[[mods]]
modId = "foo"
version = "1"

[[dependencies.foo]]
modId = "bar"
mandatory = true
versionRange = "[2.0,)"
"""
        parsed = _parse_toml_simple(text)
        self.assertEqual(
            parsed["dependencies"],
            [{"modid": "bar", "versionRange": "[2.0,)"}],
        )


class PickSatisfyingTests(unittest.TestCase):
    def test_picks_newer_release_in_range(self):
        versions = [
            {
                "id": "old",
                "version_number": "26.1.2-1.4.97.2247",
                "version_type": "release",
                "date_published": "2026-08-01T00:00:00Z",
                "game_versions": ["26.1.2"],
                "files": [{"filename": "sophisticatedcore-26.1.2-1.4.97.2247.jar", "primary": True}],
            },
            {
                "id": "new",
                "version_number": "26.1.2-1.4.98.2256",
                "version_type": "release",
                "date_published": "2026-08-11T22:29:00Z",
                "game_versions": ["26.1.2"],
                "files": [{"filename": "sophisticatedcore-26.1.2-1.4.98.2256.jar", "primary": True}],
            },
        ]
        cand, reason = pick_version_satisfying_range(
            versions, "[1.4.98,)", game="26.1.2"
        )
        self.assertIsNotNone(cand)
        assert cand is not None
        self.assertEqual(cand["id"], "new")
        self.assertEqual(reason, "release_satisfies_dep")

    def test_choose_update_sees_core_1_4_98(self):
        versions = [
            {
                "id": "old",
                "version_number": "26.1.2-1.4.97.2247",
                "version_type": "release",
                "date_published": "2026-08-01T00:00:00Z",
                "game_versions": ["26.1.2"],
                "files": [
                    {
                        "filename": "sophisticatedcore-26.1.2-1.4.97.2247.jar",
                        "primary": True,
                    }
                ],
            },
            {
                "id": "new",
                "version_number": "26.1.2-1.4.98.2256",
                "version_type": "release",
                "date_published": "2026-08-11T22:29:00Z",
                "game_versions": ["26.1.2"],
                "files": [
                    {
                        "filename": "sophisticatedcore-26.1.2-1.4.98.2256.jar",
                        "primary": True,
                    }
                ],
            },
        ]
        cand, reason = choose_update(
            "26.1.2-1.4.97.2247",
            "old",
            versions,
            installed_filename="sophisticatedcore-26.1.2-1.4.97.2247.jar",
            game="26.1.2",
        )
        self.assertIsNotNone(cand)
        assert cand is not None
        self.assertEqual(cand["id"], "new")
        self.assertEqual(reason, "release_available")


CORE_VERSIONS = [
    {
        "id": "old",
        "version_number": "26.1.2-1.4.97.2247",
        "version_type": "release",
        "date_published": "2026-08-01T00:00:00Z",
        "game_versions": ["26.1.2"],
        "files": [
            {
                "filename": "sophisticatedcore-26.1.2-1.4.97.2247.jar",
                "primary": True,
                "url": "https://example.invalid/old.jar",
            }
        ],
    },
    {
        "id": "new",
        "version_number": "26.1.2-1.4.98.2256",
        "version_type": "release",
        "date_published": "2026-08-11T22:29:00Z",
        "game_versions": ["26.1.2"],
        "files": [
            {
                "filename": "sophisticatedcore-26.1.2-1.4.98.2256.jar",
                "primary": True,
                "url": "https://example.invalid/new.jar",
            }
        ],
    },
]


class MandatoryDepPassTests(unittest.TestCase):
    def test_installed_backpacks_pulls_core(self):
        mods = [
            InstalledMod(
                jar_name="sophisticatedbackpacks-26.1.2-3.25.86.2066.jar",
                path=Path("bp.jar"),
                sha1="bp",
                size=1,
                modid="sophisticatedbackpacks",
                version="3.25.86",
                dependencies=[
                    {"modid": "sophisticatedcore", "versionRange": "[1.4.98,)"}
                ],
            ),
            InstalledMod(
                jar_name="sophisticatedcore-26.1.2-1.4.97.2247.jar",
                path=Path("core.jar"),
                sha1="corehash",
                size=1,
                modid="sophisticatedcore",
                version="1.4.97",
            ),
        ]
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge",
            checked=2,
        )
        pending: list = []
        _satisfy_mandatory_deps(
            mods=mods,
            result=result,
            jars_dir=Path("/tmp"),
            by_hash={"corehash": {"project_id": "nmoq"}},
            versions_cache={"nmoq": CORE_VERSIONS},
            cf_files_cache={},
            cf_pid_for_mod={},
            fp_cf_for={},
            mr_exact_for={},
            mc="26.1.2",
            loader="neoforge",
            download=False,
            stage_jar=lambda *a, **k: True,
            pending_mr_titles=pending,
            log=None,
        )
        self.assertEqual(len(result.updates), 1)
        self.assertEqual(
            result.updates[0].new_jar,
            "sophisticatedcore-26.1.2-1.4.98.2256.jar",
        )
        self.assertEqual(result.updates[0].reason, "release_satisfies_dep")
        self.assertEqual(len(pending), 1)


MULTI_MODS = """
[[mods]]
modId = "moogs_end_structures"
version = "2.0.3"
displayName = "Moog's End Structures"

[[mods]]
modId = "moogs_structures"
version = "1.2.0"
displayName = "Moog's Structures"

[[dependencies.moogs_end_structures]]
modId = "moogs_structures"
type = "required"
versionRange = "[1.1.0,)"

[[dependencies.moogs_end_structures]]
modId = "neoforge"
type = "required"
versionRange = "[26.1.2,)"
"""


class MultiModJarTests(unittest.TestCase):
    def test_indexes_secondary_modid(self):
        parsed = _parse_toml_simple(MULTI_MODS)
        self.assertEqual(parsed["modid"], "moogs_end_structures")
        self.assertEqual(parsed["provides"], ["moogs_structures"])
        self.assertEqual(parsed["mod_versions"]["moogs_structures"], "1.2.0")
        self.assertEqual(
            parsed["dependencies"],
            [{"modid": "moogs_structures", "versionRange": "[1.1.0,)"}],
        )


class MissingDepNotDownloadedTests(unittest.TestCase):
    def test_missing_companion_is_error_not_download(self):
        mods = [
            InstalledMod(
                jar_name="advanced_ae.jar",
                path=Path("aae.jar"),
                sha1="aae",
                size=1,
                modid="advanced_ae",
                version="1.0",
                display_name="Advanced AE",
                dependencies=[{"modid": "ae2addonlib", "versionRange": "*"}],
            )
        ]
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge",
            checked=1,
        )
        staged: list = []
        _satisfy_mandatory_deps(
            mods=mods,
            result=result,
            jars_dir=Path("/tmp"),
            by_hash={},
            versions_cache={},
            cf_files_cache={},
            cf_pid_for_mod={},
            fp_cf_for={},
            mr_exact_for={},
            mc="26.1.2",
            loader="neoforge",
            download=True,
            stage_jar=lambda *a, **k: staged.append(a) or True,
            pending_mr_titles=[],
            log=None,
        )
        self.assertEqual(staged, [])
        self.assertEqual(len(result.updates), 0)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0]["err"], "missing_mandatory_dep")
        self.assertEqual(result.errors[0]["modid"], "ae2addonlib")

    def test_platform_dep_is_not_an_error(self):
        mods = [
            InstalledMod(
                jar_name="evilcraft.jar",
                path=Path("ec.jar"),
                sha1="ec",
                size=1,
                modid="evilcraft",
                version="1.0",
                dependencies=[{"modid": "neoforge", "versionRange": "[26.1.2.22-beta,)"}],
            )
        ]
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge",
            checked=1,
        )
        _satisfy_mandatory_deps(
            mods=mods,
            result=result,
            jars_dir=Path("/tmp"),
            by_hash={},
            versions_cache={},
            cf_files_cache={},
            cf_pid_for_mod={},
            fp_cf_for={},
            mr_exact_for={},
            mc="26.1.2",
            loader="neoforge",
            download=False,
            stage_jar=lambda *a, **k: True,
            pending_mr_titles=[],
            log=None,
        )
        self.assertEqual(result.errors, [])

    def test_secondary_modid_in_same_jar_is_present(self):
        mods = [
            InstalledMod(
                jar_name="MoogsEndStructures.jar",
                path=Path("mes.jar"),
                sha1="mes",
                size=1,
                modid="moogs_end_structures",
                version="2.0.3",
                display_name="Moog's End Structures",
                dependencies=[{"modid": "moogs_structures", "versionRange": "[1.1.0,)"}],
                provides=["moogs_structures"],
                mod_versions={
                    "moogs_end_structures": "2.0.3",
                    "moogs_structures": "1.2.0",
                },
            )
        ]
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge",
            checked=1,
        )
        _satisfy_mandatory_deps(
            mods=mods,
            result=result,
            jars_dir=Path("/tmp"),
            by_hash={},
            versions_cache={},
            cf_files_cache={},
            cf_pid_for_mod={},
            fp_cf_for={},
            mr_exact_for={},
            mc="26.1.2",
            loader="neoforge",
            download=False,
            stage_jar=lambda *a, **k: True,
            pending_mr_titles=[],
            log=None,
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(result.updates, [])


MOOGS_INLINE = """
modLoader = 'javafml'
loaderVersion = '[1,)'
mods = [
{ modId = 'mes', version = '2.0.3', displayName = "MoogsEndStructures", description = 'x' },
]
[[dependencies.mes]]
modId = "moogs_structures"
mandatory = true
versionRange = "[1.1.0,)"
"""

MOOGS_DEPS_ONLY = """
modLoader = 'javafml'
loaderVersion = '[1,)'
[[dependencies.mes]]
modId = "moogs_structures"
mandatory = true
versionRange = "[1.1.0,)"
"""


class InlineModsTableTests(unittest.TestCase):
    def test_inline_mods_array(self):
        parsed = _parse_toml_simple(MOOGS_INLINE)
        self.assertEqual(parsed["modid"], "mes")
        self.assertEqual(parsed["version"], "2.0.3")
        self.assertEqual(parsed["displayname"], "MoogsEndStructures")
        self.assertEqual(
            parsed["dependencies"],
            [{"modid": "moogs_structures", "versionRange": "[1.1.0,)"}],
        )

    def test_does_not_treat_dep_modid_as_primary(self):
        parsed = _parse_toml_simple(MOOGS_DEPS_ONLY)
        self.assertIsNone(parsed.get("modid"))
        self.assertEqual(
            parsed["dependencies"],
            [{"modid": "moogs_structures", "versionRange": "[1.1.0,)"}],
        )


def _write_jar(path: Path, files: dict[str, bytes | str]) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            raw = data.encode("utf-8") if isinstance(data, str) else data
            zf.writestr(name, raw)


class JarMetadataTests(unittest.TestCase):
    def test_jarjar_nested_mod_counts_as_provided(self):
        import zipfile
        from io import BytesIO

        inner_buf = BytesIO()
        with zipfile.ZipFile(inner_buf, "w") as inner:
            inner.writestr(
                "META-INF/neoforge.mods.toml",
                """
[[mods]]
modId = "ae2addonlib"
version = "26.1.3-alpha"
displayName = "AE2AddonLib"
""",
            )
        tmp = Path(tempfile.mkdtemp()) / "advanced_ae.jar"
        _write_jar(
            tmp,
            {
                "META-INF/neoforge.mods.toml": """
[[mods]]
modId = "advanced_ae"
version = "26.1.7"
displayName = "Advanced AE"

[[dependencies.advanced_ae]]
modId = "ae2addonlib"
type = "required"
versionRange = "*"
""",
                "META-INF/jarjar/ae2addonlib-26.1.3-alpha.jar": inner_buf.getvalue(),
            },
        )
        meta = read_mod_metadata(tmp)
        self.assertEqual(meta["modid"], "advanced_ae")
        self.assertIn("ae2addonlib", [p.lower() for p in meta["provides"]])
        self.assertEqual(meta["mod_versions"].get("ae2addonlib"), "26.1.3-alpha")

        mods = [
            InstalledMod(
                jar_name="AdvancedAE.jar",
                path=tmp,
                sha1="aae",
                size=1,
                modid=meta["modid"],
                version=meta["version"],
                display_name=meta["displayname"],
                dependencies=list(meta["dependencies"]),
                provides=list(meta["provides"]),
                mod_versions=dict(meta["mod_versions"]),
            )
        ]
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge",
            checked=1,
        )
        _satisfy_mandatory_deps(
            mods=mods,
            result=result,
            jars_dir=Path("/tmp"),
            by_hash={},
            versions_cache={},
            cf_files_cache={},
            cf_pid_for_mod={},
            fp_cf_for={},
            mr_exact_for={},
            mc="26.1.2",
            loader="neoforge",
            download=False,
            stage_jar=lambda *a, **k: True,
            pending_mr_titles=[],
            log=None,
        )
        self.assertEqual(result.errors, [])

    def test_jar_version_placeholder_from_manifest(self):
        tmp = Path(tempfile.mkdtemp()) / "moogs_lib.jar"
        _write_jar(
            tmp,
            {
                "META-INF/neoforge.mods.toml": """
[[mods]]
modId = "moogs_structures"
version = "${file.jarVersion}"
displayName = "Moog's Structures"
""",
                "META-INF/MANIFEST.MF": (
                    "Manifest-Version: 1.0\n"
                    "Implementation-Version: 3.0.1\n"
                ),
            },
        )
        meta = read_mod_metadata(tmp)
        self.assertEqual(meta["modid"], "moogs_structures")
        self.assertEqual(meta["version"], "3.0.1")
        self.assertEqual(meta["mod_versions"]["moogs_structures"], "3.0.1")

    def test_fabric_json_when_toml_has_no_mods_table(self):
        tmp = Path(tempfile.mkdtemp()) / "mes.jar"
        _write_jar(
            tmp,
            {
                "META-INF/neoforge.mods.toml": MOOGS_DEPS_ONLY,
                "fabric.mod.json": '{"id":"mes","version":"2.0.3","name":"MoogsEndStructures"}',
            },
        )
        meta = read_mod_metadata(tmp)
        self.assertEqual(meta["modid"], "mes")
        self.assertEqual(meta["version"], "2.0.3")
        self.assertEqual(
            meta["dependencies"],
            [{"modid": "moogs_structures", "versionRange": "[1.1.0,)"}],
        )


if __name__ == "__main__":
    unittest.main()
