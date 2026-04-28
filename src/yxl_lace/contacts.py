from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from .crypto import load_public_key_from_pem


DEFAULT_KEY_DIR = Path.home() / ".yxl_lace"
DEFAULT_CONTACTS_PATH = DEFAULT_KEY_DIR / "contacts.json"

CONTACTS_VERSION = 1


_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class Contact:
    id: str
    label: str
    ipv4: str
    port: int
    public_key_pem: str


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def validate_contact_id(contact_id: str) -> str:
    s = contact_id.strip()
    if not s or not _ID_RE.match(s):
        raise ValueError("contact id must match: [a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}")
    return s


def validate_label(label: str) -> str:
    s = label.strip()
    if not s:
        raise ValueError("label is empty")
    return s


def validate_ipv4(ip: str) -> str:
    s = ip.strip()
    parts = s.split(".")
    if len(parts) != 4:
        raise ValueError("invalid ipv4")
    try:
        nums = [int(p) for p in parts]
    except ValueError as exc:
        raise ValueError("invalid ipv4") from exc
    if any(n < 0 or n > 255 for n in nums):
        raise ValueError("invalid ipv4")
    return ".".join(str(n) for n in nums)


def validate_port(port: int) -> int:
    if not (1 <= int(port) <= 65535):
        raise ValueError("port must be within 1–65535")
    return int(port)


def normalize_public_key_pem(pem: str) -> str:
    raw = pem.strip()
    if not raw:
        raise ValueError("public key pem is empty")
    # Validate parseable RSA public key
    load_public_key_from_pem(raw.encode("utf-8"))
    if not raw.endswith("\n"):
        raw += "\n"
    return raw


def load_contacts(path: Path = DEFAULT_CONTACTS_PATH) -> list[Contact]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != CONTACTS_VERSION:
        return []
    items = data.get("contacts") or []
    out: list[Contact] = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            c = Contact(
                id=validate_contact_id(str(it.get("id", ""))),
                label=validate_label(str(it.get("label", ""))),
                ipv4=validate_ipv4(str(it.get("ipv4", ""))),
                port=validate_port(int(it.get("port", 0))),
                public_key_pem=normalize_public_key_pem(str(it.get("public_key_pem", ""))),
            )
        except Exception:
            continue
        out.append(c)
    return out


def save_contacts(contacts: Iterable[Contact], path: Path = DEFAULT_CONTACTS_PATH) -> None:
    items = [asdict(c) for c in contacts]
    payload = {"version": CONTACTS_VERSION, "contacts": items}
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def upsert_contact(new_contact: Contact, path: Path = DEFAULT_CONTACTS_PATH) -> None:
    contacts = load_contacts(path)
    by_id = {c.id: c for c in contacts}
    by_id[new_contact.id] = new_contact
    save_contacts(by_id.values(), path)


def generate_contact_id(path: Path = DEFAULT_CONTACTS_PATH) -> str:
    """
    Generate a short random, file-stable contact id.
    - Hidden from UI/CLI input.
    - Must satisfy `validate_contact_id`.
    """
    existing = {c.id for c in load_contacts(path)}
    for _ in range(128):
        cid = secrets.token_hex(4)  # 8 hex chars
        try:
            cid = validate_contact_id(cid)
        except ValueError:
            continue
        if cid not in existing:
            return cid
    raise RuntimeError("failed to generate unique contact id")


def update_contact_label(contact_id: str, new_label: str, path: Path = DEFAULT_CONTACTS_PATH) -> None:
    cid = validate_contact_id(contact_id)
    label = validate_label(new_label)
    contacts = load_contacts(path)
    by_id = {c.id: c for c in contacts}
    cur = by_id.get(cid)
    if cur is None:
        raise ValueError("contact not found")
    by_id[cid] = Contact(id=cur.id, label=label, ipv4=cur.ipv4, port=cur.port, public_key_pem=cur.public_key_pem)
    save_contacts(by_id.values(), path)


def add_contact(
    *,
    label: str,
    ipv4: str,
    port: int,
    public_key_pem: str,
    path: Path = DEFAULT_CONTACTS_PATH,
) -> Contact:
    c = Contact(
        id=generate_contact_id(path),
        label=validate_label(label),
        ipv4=validate_ipv4(ipv4),
        port=validate_port(port),
        public_key_pem=normalize_public_key_pem(public_key_pem),
    )
    upsert_contact(c, path)
    return c


def find_contact_by_id(contact_id: str, path: Path = DEFAULT_CONTACTS_PATH) -> Optional[Contact]:
    cid = contact_id.strip()
    for c in load_contacts(path):
        if c.id == cid:
            return c
    return None


def find_contact_by_ipv4(ipv4: str, path: Path = DEFAULT_CONTACTS_PATH) -> Optional[Contact]:
    ip = validate_ipv4(ipv4)
    for c in load_contacts(path):
        if c.ipv4 == ip:
            return c
    return None

