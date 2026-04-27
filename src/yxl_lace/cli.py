"""命令行聊天入口（需在 ``PYTHONPATH`` 包含仓库 ``src`` 时运行，或使用 ``python -m yxl_lace``）。"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
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
from yxl_lace.udp_auth import MutualAuthFailed, handshake_udp_chat_symmetric, pubkey_initiator_is_local
from yxl_lace.udp_chat import udp_chat_loop_with_transport
from yxl_lace.contacts import (
    Contact,
    load_contacts,
    normalize_public_key_pem,
    upsert_contact,
    validate_contact_id,
    validate_ipv4,
    validate_label,
    validate_port,
)

DEFAULT_KEY_DIR = Path.home() / ".yxl_lace"
DEFAULT_PRIVATE_KEY_PATH = DEFAULT_KEY_DIR / "rsa_private.pem"
DEFAULT_PUBLIC_KEY_PATH = DEFAULT_KEY_DIR / "rsa_public.pem"
DEFAULT_COMM_PORT_FILE = DEFAULT_KEY_DIR / "default_comm_port"
DEFAULT_COMM_PORT_FALLBACK = 9001

TCP_CONNECT_RETRIES = 32
TCP_CONNECT_DELAY_S = 0.25


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


async def _tcp_connect_with_retry(host: str, port: int):
    last_exc: Exception | None = None
    for _ in range(TCP_CONNECT_RETRIES):
        try:
            return await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5.0)
        except (OSError, asyncio.TimeoutError) as exc:
            last_exc = exc
            await asyncio.sleep(TCP_CONNECT_DELAY_S)
    raise last_exc if last_exc else OSError("TCP 连接失败")


async def _run_tcp_listen(peer_ip: str, port: int, session_key: bytes) -> None:
    first_conn: asyncio.Future = asyncio.get_running_loop().create_future()

    async def _on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            peername = writer.get_extra_info("peername")
            exp = _canonical_peer_ip(peer_ip)
            obs = _canonical_peer_ip(peername[0]) if peername else ""
            if peername is None or obs != exp:
                print(
                    f"已拒绝 TCP 连接：{peername}（仅接受来自 {peer_ip}；"
                    f"规范化地址 收到 {obs!r} ≠ 期望 {exp!r}）",
                    flush=True,
                )
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                return
            if first_conn.done():
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                return
            writer.write(TCP_ROLE_ACK)
            await writer.drain()
            first_conn.set_result((reader, writer))
        except Exception as exc:
            print(f"处理入站 TCP 时出错：{exc!r}（peername={writer.get_extra_info('peername')!r}）", flush=True)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    server = await asyncio.start_server(_on_client, "0.0.0.0", port)
    async with server:
        serve_task = asyncio.create_task(server.serve_forever())
        print(
            f"等待 {peer_ip} 的 TCP 连接（本机端口 {port}）…\n"
            f"若对方已显示「TCP 已连接」而此处一直不停：请在本机执行 `lsof -i :{port}` "
            "确认是否只有当前程序在监听该端口。",
            flush=True,
        )
        try:
            reader, writer = await first_conn
        finally:
            serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await serve_task

    print("TCP 已连接。输入 /quit 退出聊天。", flush=True)
    await chat_loop(reader, writer, session_key)


async def cmd_connect_user() -> None:
    sk = _load_local_private_key()
    if sk is None:
        return

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

    try:
        session_key, peer_ip, transport, queue = await handshake_udp_chat_symmetric(
            host, peer_port, local_port, sk, peer_pk
        )
    except MutualAuthFailed as exc:
        print(t("udp_auth_fail", err=exc))
        return
    except (OSError, asyncio.TimeoutError) as exc:
        print(t("udp_handshake_fail", err=exc))
        return

    print(t("udp_auth_ok"), flush=True)
    try:
        await udp_chat_loop_with_transport(
            session_key=session_key,
            peer_ip=_canonical_peer_ip(peer_ip),
            peer_port=peer_port,
            transport=transport,
            queue=queue,
        )
    finally:
        transport.close()


def cmd_save_user_stub() -> None:
    try:
        contact_id = validate_contact_id(prompt_nonempty(t("contact_id_prompt")))
        label = validate_label(prompt_nonempty(t("contact_label_prompt")))
        ipv4 = validate_ipv4(prompt_nonempty(t("peer_ipv4_prompt")))
        port = validate_port(int(prompt_nonempty(t("peer_port_prompt"))))
        pem = prompt_peer_public_pem().decode("utf-8", errors="strict")
        pem = normalize_public_key_pem(pem)
        upsert_contact(
            Contact(
                id=contact_id,
                label=label,
                ipv4=ipv4,
                port=port,
                public_key_pem=pem,
            )
        )
        print(t("contact_saved"))
    except Exception as exc:
        print(f"{exc}")


async def cmd_connect_saved_contact() -> None:
    sk = _load_local_private_key()
    if sk is None:
        return
    contacts = load_contacts()
    if not contacts:
        print(t("contacts_empty"))
        return
    print(t("contacts_list_hdr"))
    for i, c in enumerate(contacts, start=1):
        print(f"{i}. {c.id} — {c.label} — {c.ipv4}:{c.port}")
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
    # reuse manual connect flow
    local_port = read_default_comm_port()
    peer_pk = load_public_key_from_pem(c.public_key_pem.encode("utf-8"))
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
    try:
        session_key, peer_ip, transport, queue = await handshake_udp_chat_symmetric(
            c.ipv4, c.port, local_port, sk, peer_pk
        )
    except MutualAuthFailed as exc:
        print(t("udp_auth_fail", err=exc))
        return
    except (OSError, asyncio.TimeoutError) as exc:
        print(t("udp_handshake_fail", err=exc))
        return
    print(t("udp_auth_ok"), flush=True)
    try:
        await udp_chat_loop_with_transport(
            session_key=session_key,
            peer_ip=_canonical_peer_ip(peer_ip),
            peer_port=c.port,
            transport=transport,
            queue=queue,
        )
    finally:
        transport.close()


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
        else:
            print(t("invalid_choice"))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
