from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
from typing import Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .crypto import derive_chat_key, rsa_oaep_decrypt, rsa_oaep_encrypt

CHALLENGE_BYTES = 32
MAX_HANDSHAKE_FRAME = 512
C1_RESEND_SEC = 0.45

# 带类型字节，避免 C1 重传与后续报文混淆
KIND_C1 = 0x01
KIND_C2 = 0x02
KIND_C3 = 0x03
KIND_C4 = 0x04
# 聊天数据报文（body 为 AES-GCM blob）
KIND_CHAT = 0x10

logger = logging.getLogger(__name__)

Addr = Tuple[str, int]


class MutualAuthFailed(Exception):
    """双向 RSA 挑战–应答（UDP 阶段）失败。"""


def pack_frame(payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big") + payload


def unpack_frame(datagram: bytes) -> bytes:
    if len(datagram) < 4:
        raise MutualAuthFailed("UDP 报文过短")
    n = int.from_bytes(datagram[:4], "big")
    body = datagram[4:]
    if n <= 0 or n > MAX_HANDSHAKE_FRAME or len(body) != n:
        raise MutualAuthFailed("UDP 帧长度无效")
    return body


def pack_typed(kind: int, body: bytes) -> bytes:
    return pack_frame(bytes([kind]) + body)


def unpack_typed(datagram: bytes) -> Tuple[int, bytes]:
    inner = unpack_frame(datagram)
    if len(inner) < 2:
        raise MutualAuthFailed("报文过短")
    return inner[0], inner[1:]


class _UdpQueueProto(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue) -> None:
        self.queue = queue

    def datagram_received(self, data: bytes, addr: Addr) -> None:
        self.queue.put_nowait((data, addr))


async def _udp_recv(
    queue: asyncio.Queue,
    *,
    expect_addr: Optional[Addr],
    timeout: float,
) -> Tuple[bytes, Addr]:
    if timeout <= 0:
        raise asyncio.TimeoutError()
    while True:
        data, addr = await asyncio.wait_for(queue.get(), timeout=timeout)
        if expect_addr is not None and addr != expect_addr:
            logger.debug("ignore udp from %s (expect %s)", addr, expect_addr)
            continue
        return data, addr


async def _recv_typed(
    queue: asyncio.Queue,
    *,
    expect_kind: int,
    expect_addr: Optional[Addr],
    deadline: float,
    require_src_port: Optional[int] = None,
) -> Tuple[bytes, Addr]:
    """若 ``require_src_port`` 非空，则仅接受 UDP 源端口为该值的报文（先手等待后手从固定端口回复时）。"""
    loop = asyncio.get_running_loop()
    while loop.time() < deadline:
        rem = deadline - loop.time()
        if rem <= 0:
            break
        try:
            raw, addr = await _udp_recv(queue, expect_addr=expect_addr, timeout=rem)
        except asyncio.TimeoutError:
            raise MutualAuthFailed("握手等待超时") from None
        if require_src_port is not None and addr[1] != require_src_port:
            continue
        try:
            kind, body = unpack_typed(raw)
        except MutualAuthFailed:
            continue
        if kind != expect_kind:
            continue
        return body, addr
    raise MutualAuthFailed("握手超时或报文类型不匹配")


def pubkey_initiator_is_local(
    private_key: rsa.RSAPrivateKey,
    peer_public_key: rsa.RSAPublicKey,
) -> bool:
    """若本机公钥（DER SubjectPublicKeyInfo）按字节小于对方，则为 UDP/TCP 的「先手 / 客户端」。"""
    mine = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    peer = peer_public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if mine == peer:
        raise MutualAuthFailed("双方公钥相同，请确认未将本机公钥误贴为对方公钥")
    return mine < peer


async def handshake_udp_initiator(
    peer_host: str,
    peer_port: int,
    bind_port: int,
    private_key: rsa.RSAPrivateKey,
    peer_public_key: rsa.RSAPublicKey,
    *,
    timeout: float = 90.0,
) -> bytes:
    """先手：向 ``peer_host:peer_port`` 发 UDP 完成 RSA 握手；周期性重发 C1 直至收到 C2。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _UdpQueueProto(queue),
        local_addr=("0.0.0.0", bind_port),
    )
    peer = (peer_host, peer_port)
    deadline = loop.time() + timeout

    def send_typed(kind: int, rsa_blob: bytes) -> None:
        transport.sendto(pack_typed(kind, rsa_blob), peer)

    try:
        r_a = secrets.token_bytes(CHALLENGE_BYTES)
        c1 = rsa_oaep_encrypt(peer_public_key, r_a)

        c2: Optional[bytes] = None
        while loop.time() < deadline:
            send_typed(KIND_C1, c1)
            wait = min(C1_RESEND_SEC, deadline - loop.time())
            if wait <= 0:
                break
            try:
                raw, addr = await asyncio.wait_for(queue.get(), timeout=wait)
            except asyncio.TimeoutError:
                continue
            if addr[1] != peer_port:
                continue
            try:
                kind, body = unpack_typed(raw)
            except MutualAuthFailed:
                continue
            if kind != KIND_C2:
                continue
            c2 = body
            break

        if c2 is None:
            raise MutualAuthFailed("等待 Round1 应答超时（请确认对方已输入相同端口并已启动）")

        try:
            opened = rsa_oaep_decrypt(private_key, c2)
        except Exception as exc:
            raise MutualAuthFailed("Round1 解密失败") from exc
        if not hmac.compare_digest(opened, r_a):
            raise MutualAuthFailed("Round1 挑战不匹配")

        c3, _ = await _recv_typed(
            queue,
            expect_kind=KIND_C3,
            expect_addr=None,
            deadline=deadline,
            require_src_port=peer_port,
        )
        try:
            r_b = rsa_oaep_decrypt(private_key, c3)
        except Exception as exc:
            raise MutualAuthFailed("Round2 解密失败") from exc
        if len(r_b) != CHALLENGE_BYTES:
            raise MutualAuthFailed("挑战长度无效")

        c4 = rsa_oaep_encrypt(peer_public_key, r_b)
        send_typed(KIND_C4, c4)

        return derive_chat_key(r_a, r_b)
    finally:
        transport.close()


async def handshake_udp_responder(
    bind_port: int,
    private_key: rsa.RSAPrivateKey,
    peer_public_key: rsa.RSAPublicKey,
    *,
    timeout: float = 90.0,
) -> Tuple[bytes, str]:
    """后手：在本机 UDP ``bind_port`` 上完成握手。返回 (会话密钥, 对端 IP)。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _UdpQueueProto(queue),
        local_addr=("0.0.0.0", bind_port),
    )
    deadline = loop.time() + timeout

    try:
        c1, peer_addr = await _recv_typed(
            queue,
            expect_kind=KIND_C1,
            expect_addr=None,
            deadline=deadline,
            require_src_port=None,
        )
        peer_ip = peer_addr[0]

        try:
            r_a = rsa_oaep_decrypt(private_key, c1)
        except Exception as exc:
            raise MutualAuthFailed("Round1 解密失败") from exc
        if len(r_a) != CHALLENGE_BYTES:
            raise MutualAuthFailed("挑战长度无效")

        c2 = rsa_oaep_encrypt(peer_public_key, r_a)
        transport.sendto(pack_typed(KIND_C2, c2), peer_addr)

        r_b = secrets.token_bytes(CHALLENGE_BYTES)
        c3 = rsa_oaep_encrypt(peer_public_key, r_b)
        transport.sendto(pack_typed(KIND_C3, c3), peer_addr)

        c4, addr2 = await _recv_typed(
            queue,
            expect_kind=KIND_C4,
            expect_addr=peer_addr,
            deadline=deadline,
            require_src_port=None,
        )
        if addr2 != peer_addr:
            raise MutualAuthFailed("Round2 来源地址不一致")

        try:
            opened = rsa_oaep_decrypt(private_key, c4)
        except Exception as exc:
            raise MutualAuthFailed("Round2 解密失败") from exc
        if not hmac.compare_digest(opened, r_b):
            raise MutualAuthFailed("Round2 挑战不匹配")

        return derive_chat_key(r_a, r_b), peer_ip
    finally:
        transport.close()


async def handshake_udp_symmetric(
    peer_host: str,
    peer_port: int,
    local_port: int,
    private_key: rsa.RSAPrivateKey,
    peer_public_key: rsa.RSAPublicKey,
    *,
    timeout: float = 90.0,
) -> Tuple[bytes, bool, Optional[str]]:
    """
    局域网对称启动：本机监听 ``local_port``，向对方 ``peer_host:peer_port`` 发 UDP。

    公钥 DER 较小者为先手（UDP 先发、TCP 客户端连对端 ``peer_port``）；较大者为后手（UDP 监听
    ``local_port``、TCP 在同一端口等待连接）。

    返回 ``(session_key, is_tcp_client, peer_ip)``；``peer_ip`` 仅服务端侧非空。
    """
    if pubkey_initiator_is_local(private_key, peer_public_key):
        key = await handshake_udp_initiator(
            peer_host, peer_port, local_port, private_key, peer_public_key, timeout=timeout
        )
        return key, True, None
    key, peer_ip = await handshake_udp_responder(
        local_port, private_key, peer_public_key, timeout=timeout
    )
    return key, False, peer_ip


async def handshake_udp_chat_symmetric(
    peer_host: str,
    peer_port: int,
    local_port: int,
    private_key: rsa.RSAPrivateKey,
    peer_public_key: rsa.RSAPublicKey,
    *,
    timeout: float = 90.0,
) -> Tuple[bytes, str, asyncio.DatagramTransport, asyncio.Queue]:
    """
    与 ``handshake_udp_symmetric`` 类似，但用于 UDP 聊天：握手成功后**复用同一个 UDP socket**继续收发。

    返回 ``(session_key, peer_ip, transport, queue)``：
    - ``transport/queue``：绑定在本机 ``local_port`` 上，供后续 UDP+AES 聊天直接使用（避免 close→rebind 的竞态）。
    - ``peer_ip``：用于聊天时过滤来源地址。
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _UdpQueueProto(queue),
        local_addr=("0.0.0.0", local_port),
    )

    try:
        deadline = loop.time() + timeout
        peer: Addr = (peer_host, peer_port)

        def send_typed(kind: int, rsa_blob: bytes) -> None:
            transport.sendto(pack_typed(kind, rsa_blob), peer)

        if pubkey_initiator_is_local(private_key, peer_public_key):
            # 先手：复用 transport/queue 进行握手，不关闭 socket。
            r_a = secrets.token_bytes(CHALLENGE_BYTES)
            c1 = rsa_oaep_encrypt(peer_public_key, r_a)

            c2: Optional[bytes] = None
            while loop.time() < deadline:
                send_typed(KIND_C1, c1)
                wait = min(C1_RESEND_SEC, deadline - loop.time())
                if wait <= 0:
                    break
                try:
                    raw, addr = await asyncio.wait_for(queue.get(), timeout=wait)
                except asyncio.TimeoutError:
                    continue
                if addr[1] != peer_port:
                    continue
                try:
                    kind, body = unpack_typed(raw)
                except MutualAuthFailed:
                    continue
                if kind != KIND_C2:
                    continue
                c2 = body
                break

            if c2 is None:
                raise MutualAuthFailed("等待 Round1 应答超时（请确认对方已输入相同端口并已启动）")

            try:
                opened = rsa_oaep_decrypt(private_key, c2)
            except Exception as exc:
                raise MutualAuthFailed("Round1 解密失败") from exc
            if not hmac.compare_digest(opened, r_a):
                raise MutualAuthFailed("Round1 挑战不匹配")

            c3, _ = await _recv_typed(
                queue,
                expect_kind=KIND_C3,
                expect_addr=None,
                deadline=deadline,
                require_src_port=peer_port,
            )
            try:
                r_b = rsa_oaep_decrypt(private_key, c3)
            except Exception as exc:
                raise MutualAuthFailed("Round2 解密失败") from exc
            if len(r_b) != CHALLENGE_BYTES:
                raise MutualAuthFailed("挑战长度无效")

            c4 = rsa_oaep_encrypt(peer_public_key, r_b)
            send_typed(KIND_C4, c4)

            return derive_chat_key(r_a, r_b), peer_host, transport, queue

        # 后手：同样复用 transport/queue；peer_ip 从首个 C1 的来源获得。
        c1, peer_addr = await _recv_typed(
            queue,
            expect_kind=KIND_C1,
            expect_addr=None,
            deadline=deadline,
            require_src_port=None,
        )
        peer_ip = peer_addr[0]

        try:
            r_a = rsa_oaep_decrypt(private_key, c1)
        except Exception as exc:
            raise MutualAuthFailed("Round1 解密失败") from exc
        if len(r_a) != CHALLENGE_BYTES:
            raise MutualAuthFailed("挑战长度无效")

        c2 = rsa_oaep_encrypt(peer_public_key, r_a)
        transport.sendto(pack_typed(KIND_C2, c2), peer_addr)

        r_b = secrets.token_bytes(CHALLENGE_BYTES)
        c3 = rsa_oaep_encrypt(peer_public_key, r_b)
        transport.sendto(pack_typed(KIND_C3, c3), peer_addr)

        c4, addr2 = await _recv_typed(
            queue,
            expect_kind=KIND_C4,
            expect_addr=peer_addr,
            deadline=deadline,
            require_src_port=None,
        )
        if addr2 != peer_addr:
            raise MutualAuthFailed("Round2 来源地址不一致")

        try:
            opened = rsa_oaep_decrypt(private_key, c4)
        except Exception as exc:
            raise MutualAuthFailed("Round2 解密失败") from exc
        if not hmac.compare_digest(opened, r_b):
            raise MutualAuthFailed("Round2 挑战不匹配")

        return derive_chat_key(r_a, r_b), peer_ip, transport, queue
    except Exception:
        transport.close()
        raise
