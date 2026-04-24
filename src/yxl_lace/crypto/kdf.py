from __future__ import annotations

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HKDF_INFO = b"YXL-LACE-chat-v1"
HKDF_SALT = b"YXL-LACE-hkdf-salt-v1"


def derive_chat_key(r_a: bytes, r_b: bytes) -> bytes:
    r_lo, r_hi = (r_a, r_b) if r_a <= r_b else (r_b, r_a)
    ikm = r_lo + r_hi
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=HKDF_SALT, info=HKDF_INFO)
    return hkdf.derive(ikm)
