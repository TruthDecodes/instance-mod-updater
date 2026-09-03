"""Instance numbering and selection (no name matching)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from instance_mod_updater.app_local import (
    format_instance_choice,
    instance_at,
    list_instances,
    select_instances,
)
from instance_mod_updater.cli import _peel_instance_number, build_parser, main


def _write_instance(root: Path, folder: str, name: str | None = None) -> Path:
    path = root / "instances" / folder
    path.mkdir(parents=True)
    (path / "mods").mkdir()
    data = {"name": name or folder, "mcVersion": "1.21.1", "modLoader": "neoforge-21.1.0"}
    (path / "instance.json").write_text(json.dumps(data), encoding="utf-8")
    return path


class InstanceSelectTests(unittest.TestCase):
    def test_list_order_is_sorted_folder_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_instance(root, "zeta")
            _write_instance(root, "alpha")
            names = [i.path.name for i in list_instances(root)]
            self.assertEqual(names, ["alpha", "zeta"])

    def test_instance_at_is_one_based(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_instance(root, "alpha")
            _write_instance(root, "beta")
            self.assertEqual(instance_at(1, root).path.name, "alpha")
            self.assertEqual(instance_at(2, root).path.name, "beta")
            with self.assertRaises(SystemExit):
                instance_at(3, root)

    def test_select_single_no_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_instance(root, "only")

            def boom(_prompt: str) -> str:
                raise AssertionError("should not prompt")

            chosen = select_instances(None, root, input_fn=boom)
            self.assertEqual([c.path.name for c in chosen], ["only"])

    def test_select_prompt_number_and_enter_all(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_instance(root, "alpha")
            _write_instance(root, "beta")
            chosen = select_instances(None, root, input_fn=lambda _p: "2")
            self.assertEqual([c.path.name for c in chosen], ["beta"])
            chosen = select_instances(None, root, input_fn=lambda _p: "")
            self.assertEqual([c.path.name for c in chosen], ["alpha", "beta"])

    def test_format_choice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_instance(root, "folder", name="Pretty")
            inst = list_instances(root)[0]
            self.assertEqual(format_instance_choice(1, inst), "1  folder  (Pretty)")

    def test_peel_number(self):
        self.assertEqual(_peel_instance_number(["1", "--dry-run"]), (1, ["--dry-run"]))
        self.assertEqual(_peel_instance_number(["list"]), (None, ["list"]))
        with self.assertRaises(SystemExit):
            _peel_instance_number(["1", "check"])

    def test_parser_default_is_update(self):
        p = build_parser()
        args = p.parse_args([])
        self.assertEqual(args.func.__name__, "cmd_update")
        args = p.parse_args(["check", "2"])
        self.assertEqual(args.instance, 2)
        self.assertEqual(args.func.__name__, "cmd_check")

    def test_main_peels_number_for_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_instance(root, "alpha")
            _write_instance(root, "beta")
            with patch("instance_mod_updater.cli._update_one", return_value=0) as one:
                code = main(["2", "--ftba-root", str(root), "--dry-run"])
                self.assertEqual(code, 0)
                self.assertEqual(one.call_count, 1)
                inst = one.call_args[0][1]
                self.assertEqual(inst.path.name, "beta")
                args = one.call_args[0][0]
                self.assertEqual(args.instance, 2)
                self.assertTrue(args.dry_run)


if __name__ == "__main__":
    unittest.main()
