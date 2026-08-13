import unittest

from instance_mod_updater.versions import (
    cmp_ver,
    is_newer,
    parse_ver,
    product_version,
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


if __name__ == "__main__":
    unittest.main()
