import unittest

from instance_mod_updater import _ed25519


class Rfc8032Tests(unittest.TestCase):
    def test_vector_1_empty_message(self):
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        pk = _ed25519.publickey(seed)
        self.assertEqual(
            pk.hex(),
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        )
        sig = _ed25519.sign(seed, b"")
        self.assertEqual(
            sig.hex(),
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
        )
        self.assertTrue(_ed25519.verify(pk, b"", sig))
        self.assertFalse(_ed25519.verify(pk, b"x", sig))

    def test_roundtrip_random_message(self):
        seed = _ed25519.generate_seed()
        pk = _ed25519.publickey(seed)
        msg = b"instance-mod-updater release zip"
        sig = _ed25519.sign(seed, msg)
        self.assertTrue(_ed25519.verify(pk, msg, sig))
        self.assertFalse(_ed25519.verify(pk, msg + b".", sig))
        tampered = bytearray(sig)
        tampered[0] ^= 1
        self.assertFalse(_ed25519.verify(pk, msg, bytes(tampered)))

    def test_parse_hex_signature(self):
        seed = _ed25519.generate_seed()
        pk = _ed25519.publickey(seed)
        msg = b"abc"
        raw = _ed25519.sign(seed, msg)
        parsed = _ed25519.parse_signature((raw.hex() + "\n").encode("ascii"))
        self.assertEqual(parsed, raw)
        self.assertTrue(_ed25519.verify(pk, msg, parsed))


if __name__ == "__main__":
    unittest.main()
