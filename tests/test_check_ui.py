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


if __name__ == "__main__":
    unittest.main()
