import unittest

from instance_mod_updater.versions import (
    cmp_ver,
    display_version,
    is_newer,
    parse_ver,
    product_version,
    version_from_jar_name,
    version_in_maven_range,
)


class ParseVerTests(unittest.TestCase):
    def test_mc_first_sophisticated_core_keeps_product(self):
        old = parse_ver("26.1.2-1.4.97.2247")
        new = parse_ver("26.1.2-1.4.98.2256")
        self.assertEqual(old[0][:5], (26, 1, 2, 1, 4))
        self.assertEqual(old[0][5], 97)
        self.assertEqual(new[0][5], 98)
        self.assertTrue(is_newer("26.1.2-1.4.98.2256", "26.1.2-1.4.97.2247"))
        self.assertFalse(is_newer("26.1.2-1.4.97.2247", "26.1.2-1.4.98.2256"))

    def test_product_then_mc_still_strips_trailing_game(self):
        self.assertEqual(parse_ver("3.25.86-1.21.1")[0][:3], (3, 25, 86))
        self.assertEqual(parse_ver("1.13.1-1.20.4")[0][:3], (1, 13, 1))
        self.assertTrue(is_newer("3.25.86-26.1.2", "3.25.84-26.1.2"))

    def test_same_mc_first_not_newer(self):
        self.assertFalse(is_newer("26.1.2-1.4.97.2247", "26.1.2-1.4.97.2247"))


class MavenRangeTests(unittest.TestCase):
    def test_product_version_strips_leading_mc(self):
        self.assertEqual(product_version("26.1.2-1.4.97.2247"), "1.4.97.2247")
        self.assertEqual(product_version("1.4.97"), "1.4.97")

    def test_sophisticated_core_floor(self):
        self.assertTrue(version_in_maven_range("1.4.98", "[1.4.98,)"))
        self.assertTrue(version_in_maven_range("26.1.2-1.4.98.2256", "[1.4.98,)"))
        self.assertFalse(version_in_maven_range("1.4.97", "[1.4.98,)"))
        self.assertFalse(version_in_maven_range("26.1.2-1.4.97.2247", "[1.4.98,)"))

    def test_bounded_and_exact(self):
        self.assertTrue(version_in_maven_range("1.5.0", "[1.0,2.0)"))
        self.assertFalse(version_in_maven_range("2.0", "[1.0,2.0)"))
        self.assertTrue(version_in_maven_range("1.4.98", "[1.4.98]"))
        self.assertFalse(version_in_maven_range("1.4.97", "[1.4.98]"))

    def test_cmp_ver_pre_rank(self):
        self.assertEqual(cmp_ver("1.0.0", "1.0.0-beta.1"), 1)
        self.assertEqual(cmp_ver("1.0.0-beta.2", "1.0.0-beta.1"), 1)


class DisplayVersionTests(unittest.TestCase):
    def test_mc_first_string_drops_game(self):
        self.assertEqual(display_version("26.1.2-2.0.3"), "2.0.3")
        self.assertEqual(display_version("26.1.2-1.4.99.2266"), "1.4.99.2266")

    def test_already_product_stays(self):
        self.assertEqual(display_version("3.1.3"), "3.1.3")
        self.assertEqual(display_version("2.8.0"), "2.8.0")

    def test_mc_only_version_uses_jar_name(self):
        self.assertEqual(
            display_version("26.1.2", "ConstructionSticks-26.1.2-3.1.4.jar"),
            "3.1.4",
        )
        self.assertEqual(
            version_from_jar_name("appliedsticks-26.1.2-2.0.4.jar"),
            "2.0.4",
        )

    def test_missing_falls_back_to_question(self):
        self.assertEqual(display_version(None), "?")
        self.assertEqual(display_version(""), "?")


if __name__ == "__main__":
    unittest.main()
