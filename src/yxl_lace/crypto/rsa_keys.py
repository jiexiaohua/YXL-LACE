from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_rsa_keypair(key_size: int = 2048) -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=key_size)


def private_key_to_pem(private_key: rsa.RSAPrivateKey, password: bytes | None = None) -> bytes:
    enc = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=enc,
    )


def public_key_to_pem(public_key: rsa.RSAPublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def load_private_key_from_pem(data: bytes, password: bytes | None = None) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(data, password=password)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("PEM is not an RSA private key")
    return key


def load_public_key_from_pem(data: bytes) -> rsa.RSAPublicKey:
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, rsa.RSAPublicKey):
        raise TypeError("PEM is not an RSA public key")
    return key


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_private_key_pem(path: Path, pem: bytes) -> None:
    ensure_dir(path.parent)
    path.write_bytes(pem)
    os.chmod(path, 0o600)


def write_public_key_pem(path: Path, pem: bytes) -> None:
    ensure_dir(path.parent)
    path.write_bytes(pem)
    os.chmod(path, 0o644)
