import unittest
from pathlib import Path

from instance_mod_updater.inventory import InstalledMod, _parse_toml_simple
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


if __name__ == "__main__":
    unittest.main()
