"""命令行聊天入口（需在 ``PYTHONPATH`` 包含仓库 ``src`` 时运行，或使用 ``python -m yxl_lace``）。"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import sys
from pathlib import Path

from yxl_lace.crypto import (
    generate_rsa_keypair,
    load_private_key_from_pem,
    load_public_key_from_pem,
    private_key_to_pem,
    public_key_to_pem,
    write_private_key_pem,
    write_public_key_pem,
)
from yxl_lace.print import get_lang, index_out, logo_out, operate_out, set_lang, t
from yxl_lace.udp_auth import MutualAuthFailed, pubkey_initiator_is_local
from yxl_lace.contacts import (
    Contact,
    add_contact,
    load_contacts,
    normalize_public_key_pem,
    upsert_contact,
    update_contact_label,
    validate_ipv4,
    validate_label,
    validate_port,
)
from yxl_lace.session_manager import SessionManager

DEFAULT_KEY_DIR = Path.home() / ".yxl_lace"
DEFAULT_PRIVATE_KEY_PATH = DEFAULT_KEY_DIR / "rsa_private.pem"
DEFAULT_PUBLIC_KEY_PATH = DEFAULT_KEY_DIR / "rsa_public.pem"
DEFAULT_COMM_PORT_FILE = DEFAULT_KEY_DIR / "default_comm_port"
DEFAULT_COMM_PORT_FALLBACK = 9001

def _canonical_peer_ip(addr: object) -> str:
    """与 UDP 记录的 IPv4 和 TCP peername（可能为 ::ffff:x.x.x.x）统一成可比较形式。"""
    if addr is None:
        return ""
    ip = ipaddress.ip_address(str(addr))
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return str(mapped)
    return str(ip)


def read_default_comm_port() -> int:
    if not DEFAULT_COMM_PORT_FILE.is_file():
        return DEFAULT_COMM_PORT_FALLBACK
    try:
        p = int(DEFAULT_COMM_PORT_FILE.read_text(encoding="utf-8").strip())
        if 1 <= p <= 65535:
            return p
    except (ValueError, OSError):
        pass
    return DEFAULT_COMM_PORT_FALLBACK


def write_default_comm_port(port: int) -> None:
    DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_COMM_PORT_FILE.write_text(str(port), encoding="utf-8")


def prompt_nonempty(prompt: str) -> str:
    while True:
        s = input(prompt).strip()
        if s:
            return s
        print(t("input_empty"))


def prompt_peer_public_pem() -> bytes:
    print(t("peer_pubkey_paste"))
    lines: list[str] = []
    while True:
        line = input()
        if line.strip() == ".":
            break
        lines.append(line)
    raw = "\n".join(lines).strip()
    if not raw:
        raise ValueError(t("peer_pubkey_empty"))
    return raw.encode("utf-8")


def cmd_generate_rsa() -> None:
    DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
    sk = generate_rsa_keypair(2048)
    priv_pem = private_key_to_pem(sk)
    pub_pem = public_key_to_pem(sk.public_key())
    write_private_key_pem(DEFAULT_PRIVATE_KEY_PATH, priv_pem)
    write_public_key_pem(DEFAULT_PUBLIC_KEY_PATH, pub_pem)
    print(t("rsa_saved_priv", path=DEFAULT_PRIVATE_KEY_PATH))
    print(t("rsa_saved_pub", path=DEFAULT_PUBLIC_KEY_PATH))
    print("\n" + t("rsa_pub_share_hdr") + "\n")
    print(pub_pem.decode("utf-8"))


def cmd_set_default_port() -> None:
    cur = read_default_comm_port()
    print(t("default_port_current", port=cur))
    raw = input(t("default_port_prompt", port=cur)).strip()
    if not raw:
        print(t("default_port_unchanged"))
        return
    try:
        p = int(raw)
    except ValueError:
        print(t("port_int_required"))
        return
    if not (1 <= p <= 65535):
        print(t("port_range"))
        return
    write_default_comm_port(p)
    print(t("default_port_saved", port=p, file=DEFAULT_COMM_PORT_FILE))


def _load_local_private_key():
    if not DEFAULT_PRIVATE_KEY_PATH.is_file():
        print(t("need_generate_key", path=DEFAULT_PRIVATE_KEY_PATH))
        return None
    return load_private_key_from_pem(DEFAULT_PRIVATE_KEY_PATH.read_bytes())


#
# NOTE:
# TCP chat has been deprecated/removed in favor of single-port UDP SessionManager.
#


async def cmd_connect_user() -> None:
    local_port = read_default_comm_port()
    # 这些提示信息的详细版可以后续扩展；这里保持简洁并走 i18n。

    host = prompt_nonempty(t("peer_ipv4_prompt"))
    try:
        peer_port = int(prompt_nonempty(t("peer_port_prompt")))
    except ValueError:
        print(t("port_int_required"))
        return
    if not (1 <= peer_port <= 65535):
        print(t("port_range"))
        return

    try:
        pem = prompt_peer_public_pem()
        peer_pk = load_public_key_from_pem(pem)
    except Exception as exc:
        print(t("pubkey_invalid", err=exc))
        return

    if not DEFAULT_PRIVATE_KEY_PATH.is_file():
        print(t("need_generate_key", path=DEFAULT_PRIVATE_KEY_PATH))
        return
    local_priv_pem = DEFAULT_PRIVATE_KEY_PATH.read_bytes()
    sk = load_private_key_from_pem(local_priv_pem)

    try:
        is_initiator = pubkey_initiator_is_local(sk, peer_pk)
    except MutualAuthFailed as exc:
        # pubkey_initiator_is_local 抛的消息本身已在 i18n 表中覆盖主要情况
        msg = t("pubkey_same") if "公钥相同" in str(exc) or "identical" in str(exc) else str(exc)
        print(msg)
        return

    print(t("local_port_show", local_port=local_port, host=host, peer_port=peer_port))
    role = t("role_initiator") if is_initiator else t("role_responder", local_port=local_port)
    print(t("role_prefix") + role)
    print(t("udp_auth_start"))

    peer_closed = asyncio.Event()

    def _on_msg(peer: tuple[str, int], text: str) -> None:
        print(f"\n[peer {peer[0]}:{peer[1]}] {text}", flush=True)

    def _on_peer_closed(peer: tuple[str, int]) -> None:
        print(f"\n[peer {peer[0]}:{peer[1]}] closed.", flush=True)
        peer_closed.set()

    mgr = SessionManager(
        local_port=local_port,
        local_private_key_pem=local_priv_pem,
        on_message=_on_msg,
        on_peer_closed=_on_peer_closed,
        on_status=lambda s: print(f"[status] {s}", flush=True),
    )
    try:
        await mgr.start()
        peer = await mgr.connect_peer(peer_ip=host, peer_port=peer_port, peer_public_key_pem=pem)
        print(t("udp_auth_ok"), flush=True)

        # stdin non-blocking reader (allows exit on peer close)
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        print(t("chat_ready", local=f"0.0.0.0:{local_port}", peer_ip=peer[0], peer_port=peer[1]), flush=True)
        while True:
            if peer_closed.is_set():
                break
            print("> ", end="", flush=True)
            t_line = asyncio.create_task(reader.readline())
            t_closed = asyncio.create_task(peer_closed.wait())
            done, pending = await asyncio.wait(
                {t_line, t_closed}, return_when=asyncio.FIRST_COMPLETED
            )
            for p in pending:
                p.cancel()
            if t_closed in done:
                break
            raw = t_line.result()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
            if line == "/quit":
                await mgr.close_peer(peer)
                break
            mgr.send(peer, line)
    finally:
        with contextlib.suppress(Exception):
            await mgr.close()


def cmd_save_user_stub() -> None:
    try:
        label = validate_label(prompt_nonempty(t("contact_label_prompt")))
        ipv4 = validate_ipv4(prompt_nonempty(t("peer_ipv4_prompt")))
        port = validate_port(int(prompt_nonempty(t("peer_port_prompt"))))
        pem = prompt_peer_public_pem().decode("utf-8", errors="strict")
        pem = normalize_public_key_pem(pem)
        add_contact(label=label, ipv4=ipv4, port=port, public_key_pem=pem)
        print(t("contact_saved"))
    except Exception as exc:
        print(f"{exc}")


def cmd_edit_contact_label() -> None:
    contacts = load_contacts()
    if not contacts:
        print(t("contacts_empty"))
        return
    print(t("contacts_list_hdr"))
    for i, c in enumerate(contacts, start=1):
        print(f"{i}. {c.label} — {c.ipv4}:{c.port}")
    try:
        idx = int(prompt_nonempty(t("contact_choose_prompt")))
    except ValueError:
        print(t("port_int_required"))
        return
    if not (1 <= idx <= len(contacts)):
        print(t("invalid_choice"))
        return
    c = contacts[idx - 1]
    try:
        new_label = validate_label(prompt_nonempty(t("contact_label_prompt")))
        update_contact_label(c.id, new_label)
        print(t("contact_saved"))
    except Exception as exc:
        print(f"{exc}")


async def cmd_connect_saved_contact() -> None:
    contacts = load_contacts()
    if not contacts:
        print(t("contacts_empty"))
        return
    print(t("contacts_list_hdr"))
    for i, c in enumerate(contacts, start=1):
        print(f"{i}. {c.label} — {c.ipv4}:{c.port}")
    try:
        idx = int(prompt_nonempty(t("contact_choose_prompt")))
    except ValueError:
        print(t("port_int_required"))
        return
    if not (1 <= idx <= len(contacts)):
        print(t("invalid_choice"))
        return
    c = contacts[idx - 1]
    print(t("contact_connecting"))
    local_port = read_default_comm_port()
    peer_pem = c.public_key_pem.encode("utf-8")
    peer_pk = load_public_key_from_pem(peer_pem)
    if not DEFAULT_PRIVATE_KEY_PATH.is_file():
        print(t("need_generate_key", path=DEFAULT_PRIVATE_KEY_PATH))
        return
    local_priv_pem = DEFAULT_PRIVATE_KEY_PATH.read_bytes()
    sk = load_private_key_from_pem(local_priv_pem)
    try:
        is_initiator = pubkey_initiator_is_local(sk, peer_pk)
    except MutualAuthFailed as exc:
        msg = t("pubkey_same") if "公钥相同" in str(exc) or "identical" in str(exc) else str(exc)
        print(msg)
        return
    print(t("local_port_show", local_port=local_port, host=c.ipv4, peer_port=c.port))
    role = t("role_initiator") if is_initiator else t("role_responder", local_port=local_port)
    print(t("role_prefix") + role)
    print(t("udp_auth_start"))

    peer_closed = asyncio.Event()

    def _on_msg(peer: tuple[str, int], text: str) -> None:
        print(f"\n[peer {peer[0]}:{peer[1]}] {text}", flush=True)

    def _on_peer_closed(peer: tuple[str, int]) -> None:
        print(f"\n[peer {peer[0]}:{peer[1]}] closed.", flush=True)
        peer_closed.set()

    mgr = SessionManager(
        local_port=local_port,
        local_private_key_pem=local_priv_pem,
        on_message=_on_msg,
        on_peer_closed=_on_peer_closed,
        on_status=lambda s: print(f"[status] {s}", flush=True),
    )
    try:
        await mgr.start()
        peer = await mgr.connect_peer(peer_ip=c.ipv4, peer_port=c.port, peer_public_key_pem=peer_pem)
        print(t("udp_auth_ok"), flush=True)

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        print(t("chat_ready", local=f"0.0.0.0:{local_port}", peer_ip=peer[0], peer_port=peer[1]), flush=True)
        while True:
            if peer_closed.is_set():
                break
            print("> ", end="", flush=True)
            t_line = asyncio.create_task(reader.readline())
            t_closed = asyncio.create_task(peer_closed.wait())
            done, pending = await asyncio.wait(
                {t_line, t_closed}, return_when=asyncio.FIRST_COMPLETED
            )
            for p in pending:
                p.cancel()
            if t_closed in done:
                break
            raw = t_line.result()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
            if line == "/quit":
                await mgr.close_peer(peer)
                break
            mgr.send(peer, line)
    finally:
        with contextlib.suppress(Exception):
            await mgr.close()


def cmd_switch_language() -> None:
    cur = get_lang()
    print(t("lang_current", lang=cur))
    raw = input(t("lang_prompt", lang=cur)).strip().lower()
    if not raw:
        return
    try:
        set_lang(raw)
    except ValueError:
        print(t("lang_invalid"))
        return
    print(t("lang_saved", lang=raw))


async def async_main() -> None:
    logo_out()
    index_out()
    while True:
        operate_out()
        choice = input(t("select_prompt")).strip()
        if choice == "0":
            print(t("bye"))
            break
        if choice == "1":
            cmd_generate_rsa()
        elif choice == "2":
            await cmd_connect_user()
        elif choice == "3":
            cmd_set_default_port()
        elif choice == "4":
            cmd_save_user_stub()
        elif choice == "5":
            await cmd_connect_saved_contact()
        elif choice == "6":
            cmd_switch_language()
        elif choice == "7":
            cmd_edit_contact_label()
        else:
            print(t("invalid_choice"))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
