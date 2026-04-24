from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AAD = b"yxl-lace-tcp-v1"
NONCE_LEN = 12


def aes_gcm_seal(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    aes = AESGCM(key)
    ciphertext = aes.encrypt(nonce, plaintext, AAD)
    return nonce + ciphertext


def aes_gcm_open(key: bytes, blob: bytes) -> bytes:
    if len(blob) < NONCE_LEN:
        raise ValueError("truncated message")
    nonce, ct = blob[:NONCE_LEN], blob[NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ct, AAD)
