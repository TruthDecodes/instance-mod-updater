"""Ed25519 (RFC 8032). Stdlib only. Public domain algorithm (ref10 / SUPERCOP).

Used to sign and verify self-update zip bytes. Not a general-purpose crypto
library; do not reuse for new protocols without review.
"""

from __future__ import annotations

import hashlib
import hmac
import os

_B = 256
_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _Q - 2, _Q) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)
_BY = 4 * pow(5, _Q - 2, _Q) % _Q


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, _Q - 2, _Q)
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * _I) % _Q
    if x % 2 != 0:
        x = _Q - x
    return x


_BX = _xrecover(_BY)
_B_POINT = (_BX % _Q, _BY % _Q)


def _edwards_add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = q
    den = _D * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * pow(1 + den, _Q - 2, _Q)
    y3 = (y1 * y2 + x1 * x2) * pow(1 - den, _Q - 2, _Q)
    return (x3 % _Q, y3 % _Q)


def _scalarmult(p: tuple[int, int], e: int) -> tuple[int, int]:
    if e == 0:
        return (0, 1)
    q = _scalarmult(p, e // 2)
    q = _edwards_add(q, q)
    if e & 1:
        q = _edwards_add(q, p)
    return q


def _encodeint(y: int) -> bytes:
    return y.to_bytes(32, "little")


def _encodepoint(p: tuple[int, int]) -> bytes:
    x, y = p
    bits = [(y >> i) & 1 for i in range(_B - 1)] + [x & 1]
    out = bytearray(32)
    for i, bit in enumerate(bits):
        out[i // 8] |= bit << (i % 8)
    return bytes(out)


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def _hint(m: bytes) -> int:
    h = hashlib.sha512(m).digest()
    return sum(2**i * _bit(h, i) for i in range(2 * _B))


def _decodeint(s: bytes) -> int:
    return int.from_bytes(s, "little")


def _isoncurve(p: tuple[int, int]) -> bool:
    x, y = p
    return (-x * x + y * y - 1 - _D * x * x * y * y) % _Q == 0


def _decodepoint(s: bytes) -> tuple[int, int]:
    if len(s) != 32:
        raise ValueError("public key must be 32 bytes")
    y = sum(2**i * _bit(s, i) for i in range(0, _B - 1))
    x = _xrecover(y)
    if x & 1 != _bit(s, _B - 1):
        x = _Q - x
    p = (x, y)
    if not _isoncurve(p):
        raise ValueError("point is not on the curve")
    return p


def publickey(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = hashlib.sha512(seed).digest()
    a = 2 ** (_B - 2) + sum(2**i * _bit(h, i) for i in range(3, _B - 2))
    return _encodepoint(_scalarmult(_B_POINT, a))


def generate_seed() -> bytes:
    return os.urandom(32)


def sign(seed: bytes, message: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = hashlib.sha512(seed).digest()
    a = 2 ** (_B - 2) + sum(2**i * _bit(h, i) for i in range(3, _B - 2))
    pk = _encodepoint(_scalarmult(_B_POINT, a))
    r = _hint(h[32:_B // 4] + message)
    r_point = _scalarmult(_B_POINT, r)
    r_enc = _encodepoint(r_point)
    s = (r + _hint(r_enc + pk + message) * a) % _L
    return r_enc + _encodeint(s)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    try:
        if len(public_key) != 32 or len(signature) != 64:
            return False
        pk = _decodepoint(public_key)
        r_enc = signature[:32]
        r_pt = _decodepoint(r_enc)
        s = _decodeint(signature[32:])
        if s >= _L:
            return False
        h = _hint(r_enc + public_key + message)
        left = _scalarmult(_B_POINT, s)
        right = _edwards_add(r_pt, _scalarmult(pk, h))
        return hmac.compare_digest(_encodepoint(left), _encodepoint(right))
    except (ValueError, TypeError):
        return False


def parse_public_key_hex(text: str) -> bytes:
    raw = "".join(text.split())
    if len(raw) != 64:
        raise ValueError("public key hex must be 64 characters")
    return bytes.fromhex(raw)


def parse_signature(data: bytes) -> bytes:
    if len(data) == 64:
        return data
    hexed = "".join(chr(b) for b in data if chr(b) in "0123456789abcdefABCDEF")
    if len(hexed) == 128:
        return bytes.fromhex(hexed)
    raise ValueError("signature must be 64 raw bytes or 128 hex characters")
