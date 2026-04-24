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
from yxl_lace.print import index_out, logo_out, operate_out
from yxl_lace.udp_auth import MutualAuthFailed, handshake_udp_symmetric, pubkey_initiator_is_local
from yxl_lace.udp_chat import udp_chat_loop

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
        print("输入不能为空。")


def prompt_peer_public_pem() -> bytes:
    print("请粘贴对方的 RSA 公钥（PEM）。粘贴完毕后单独一行输入一个英文句点 . 并回车结束：")
    lines: list[str] = []
    while True:
        line = input()
        if line.strip() == ".":
            break
        lines.append(line)
    raw = "\n".join(lines).strip()
    if not raw:
        raise ValueError("公钥为空")
    return raw.encode("utf-8")


def cmd_generate_rsa() -> None:
    DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
    sk = generate_rsa_keypair(2048)
    priv_pem = private_key_to_pem(sk)
    pub_pem = public_key_to_pem(sk.public_key())
    write_private_key_pem(DEFAULT_PRIVATE_KEY_PATH, priv_pem)
    write_public_key_pem(DEFAULT_PUBLIC_KEY_PATH, pub_pem)
    print("已保存私钥：", DEFAULT_PRIVATE_KEY_PATH)
    print("已保存公钥：", DEFAULT_PUBLIC_KEY_PATH)
    print("\n--- 公钥（请发给对方）---\n")
    print(pub_pem.decode("utf-8"))


def cmd_set_default_port() -> None:
    cur = read_default_comm_port()
    print(f"当前本机默认通信端口（UDP 监听 / TCP 监听）：{cur}")
    raw = input(f"新端口 (1–65535，直接回车保持 {cur})> ").strip()
    if not raw:
        print("未修改。")
        return
    try:
        p = int(raw)
    except ValueError:
        print("必须是整数。")
        return
    if not (1 <= p <= 65535):
        print("端口须在 1–65535。")
        return
    write_default_comm_port(p)
    print(f"已保存默认端口：{p}（写入 {DEFAULT_COMM_PORT_FILE}）")


def _load_local_private_key():
    if not DEFAULT_PRIVATE_KEY_PATH.is_file():
        print(f"未找到本地私钥：{DEFAULT_PRIVATE_KEY_PATH}，请先选择 (1) 生成密钥对。")
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
    print("局域网对称连接：本机使用「默认端口」收 UDP（可在菜单 (3) 修改，默认 9001）。")
    print("只需输入对方 IPv4、对方端口，以及对方公钥；可同时回车开始。")
    print("角色由 RSA 公钥自动决定：公钥（二进制序）较小的一方先发 UDP。")

    host = prompt_nonempty("对方 IPv4> ")
    try:
        peer_port = int(prompt_nonempty("对方端口> "))
    except ValueError:
        print("端口必须是整数。")
        return
    if not (1 <= peer_port <= 65535):
        print("端口须在 1–65535。")
        return

    try:
        pem = prompt_peer_public_pem()
        peer_pk = load_public_key_from_pem(pem)
    except Exception as exc:
        print(f"公钥无效：{exc}")
        return

    try:
        is_initiator = pubkey_initiator_is_local(sk, peer_pk)
    except MutualAuthFailed as exc:
        print(f"{exc}")
        return

    print(f"本机默认端口：{local_port}；对端：{host}:{peer_port}")
    print(
        "本机角色："
        + (
            "先手（UDP 发往对方端口）" if is_initiator else f"后手（UDP 监听本机 {local_port}）"
        )
    )
    print("正在进行 UDP 认证…")

    try:
        session_key, tcp_client, peer_ip = await handshake_udp_symmetric(
            host, peer_port, local_port, sk, peer_pk
        )
    except MutualAuthFailed as exc:
        print(f"认证失败：{exc}")
        return
    except (OSError, asyncio.TimeoutError) as exc:
        print(f"UDP 握手失败：{exc}")
        return

    print("UDP 认证成功。正在进入 UDP + AES-GCM 加密聊天…", flush=True)
    final_peer_ip = peer_ip or host
    await udp_chat_loop(
        session_key=session_key,
        local_port=local_port,
        peer_ip=_canonical_peer_ip(final_peer_ip),
        peer_port=peer_port,
    )


def cmd_save_user_stub() -> None:
    print("(4) save user — 暂未实现。")


async def async_main() -> None:
    logo_out()
    index_out()
    while True:
        operate_out()
        choice = input("select> ").strip()
        if choice == "0":
            print("再见。")
            break
        if choice == "1":
            cmd_generate_rsa()
        elif choice == "2":
            await cmd_connect_user()
        elif choice == "3":
            cmd_set_default_port()
        elif choice == "4":
            cmd_save_user_stub()
        else:
            print("无效选项，请输入 0–4。")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
