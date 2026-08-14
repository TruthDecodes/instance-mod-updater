import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from instance_mod_updater import term
from instance_mod_updater.cli import print_check_summary
from instance_mod_updater.pipeline import CheckResult, Replacement, error_layman


class ErrorLaymanTests(unittest.TestCase):
    def test_missing_dep_says_not_downloaded(self):
        text = error_layman(
            {
                "err": "missing_mandatory_dep",
                "jar": "Advanced AE",
                "modid": "ae2addonlib",
                "range": "*",
            }
        )
        self.assertIn("ae2addonlib", text)
        self.assertIn("does not download new mods", text)
        self.assertIn("not bundled", text)

    def test_unsatisfied_includes_installed_version(self):
        text = error_layman(
            {
                "err": "mandatory_dep_unsatisfied",
                "jar": "Foo",
                "modid": "bar",
                "range": "[2.0,)",
                "actual": "1.0",
            }
        )
        self.assertIn("1.0", text)
        self.assertIn("bar", text)


class CheckSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        term.init(color="never")

    def test_lists_every_update_and_error(self):
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge",
            checked=3,
            downloaded=2,
            downloaded_files=["new-a.jar", "new-b.jar"],
        )
        result.updates = [
            Replacement(
                jar_name="old-a.jar",
                new_jar="new-a.jar",
                old_version="1.0",
                new_version="1.1",
                channel="release",
                source="modrinth",
                reason="release_available",
                url="https://example.invalid/a",
                display_name="Mod A",
            ),
            Replacement(
                jar_name="old-b.jar",
                new_jar="new-b.jar",
                old_version="2.0",
                new_version="2.1",
                channel="release",
                source="modrinth",
                reason="release_available",
                url="https://example.invalid/b",
                display_name="Mod B",
            ),
        ]
        result.errors = [
            {
                "jar": "Advanced AE",
                "err": "missing_mandatory_dep",
                "modid": "ae2addonlib",
                "range": "*",
                "layman": error_layman(
                    {
                        "err": "missing_mandatory_dep",
                        "jar": "Advanced AE",
                        "modid": "ae2addonlib",
                        "range": "*",
                    }
                ),
            },
            {
                "jar": "Chisels",
                "err": "missing_mandatory_dep",
                "modid": "scena",
                "range": "[1,)",
                "layman": error_layman(
                    {
                        "err": "missing_mandatory_dep",
                        "jar": "Chisels",
                        "modid": "scena",
                        "range": "[1,)",
                    }
                ),
            },
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_check_summary(result, Path("/tmp/work"))
        out = buf.getvalue()
        self.assertIn("Updates (2)", out)
        self.assertIn("Mod A  1.0", out)
        self.assertIn("Mod B  2.0", out)
        self.assertIn("[downloaded]", out)
        self.assertIn("Errors (2)", out)
        self.assertIn("ae2addonlib", out)
        self.assertIn("scena", out)
        self.assertIn("does not download new mods", out)
        self.assertNotIn("and 1 more", out)
        self.assertNotIn("DONE updates=", out)

    def test_update_line_shows_product_version_not_minecraft(self):
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge",
            downloaded=1,
            downloaded_files=["ConstructionSticks-26.1.2-3.1.4.jar"],
        )
        result.updates = [
            Replacement(
                jar_name="ConstructionSticks-26.1.2-3.1.3.jar",
                new_jar="ConstructionSticks-26.1.2-3.1.4.jar",
                old_version="3.1.3",
                new_version="26.1.2",
                channel="release",
                source="modrinth",
                reason="release_available",
                url="https://example.invalid/cs",
                display_name="Construction Sticks",
            ),
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_check_summary(result, Path("/tmp/work"))
        out = buf.getvalue()
        self.assertIn("3.1.3 → 3.1.4", out)
        self.assertNotIn("3.1.3 → 26.1.2", out)

    def test_downloaded_word_is_magenta_not_cyan(self):
        import os

        old_no_color = os.environ.pop("NO_COLOR", None)
        term.init(color="always")

        def _restore() -> None:
            if old_no_color is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = old_no_color
            term.init(color="never")

        self.addCleanup(_restore)
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge",
            downloaded=1,
            downloaded_files=["new-a.jar"],
        )
        result.updates = [
            Replacement(
                jar_name="old-a.jar",
                new_jar="new-a.jar",
                old_version="1.0",
                new_version="1.1",
                channel="release",
                source="modrinth",
                reason="release_available",
                url="https://example.invalid/a",
                display_name="Mod A",
            ),
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_check_summary(result, Path("/tmp/work"))
        out = buf.getvalue()
        painted = term.magenta("downloaded")
        self.assertIn(painted, out)
        self.assertTrue(painted.startswith("\033[95m"))
        self.assertNotIn("\033[96mdownloaded", out)
        self.assertNotIn("\033[94mdownloaded", out)

    def test_neoforge_floor_leads_summary_not_footer(self):
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge-26.1.2.94",
            min_neoforge_floor="26.1.2.94",
        )
        result.updates = [
            Replacement(
                jar_name="old-a.jar",
                new_jar="new-a.jar",
                old_version="1.0",
                new_version="1.1",
                channel="release",
                source="modrinth",
                reason="release_available",
                url="https://example.invalid/a",
                display_name="Mod A",
            ),
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_check_summary(
                result, Path("/tmp/work"), current_neoforge="26.1.2.94"
            )
        out = buf.getvalue()
        floor_at = out.find("meets floor")
        updates_at = out.find("Updates (1)")
        work_at = out.find("Work root:")
        self.assertNotEqual(floor_at, -1)
        self.assertLess(floor_at, updates_at)
        self.assertLess(updates_at, work_at)
        self.assertNotIn("Min NeoForge floor", out)
        self.assertNotIn("satisfies floor", out)

    def test_neoforge_below_floor_is_a_warning(self):
        result = CheckResult(
            instance="x",
            mc_version="26.1.2",
            loader="neoforge",
            mod_loader="neoforge-26.1.2.80",
            min_neoforge_floor="26.1.2.94",
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_check_summary(
                result, Path("/tmp/work"), current_neoforge="26.1.2.80"
            )
        out = buf.getvalue()
        self.assertIn("is below floor", out)
        self.assertNotIn("meets floor", out)


if __name__ == "__main__":
    unittest.main()
