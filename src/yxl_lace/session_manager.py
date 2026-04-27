from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric import rsa

from .contacts import find_contact_by_ipv4
from .crypto import (
    aes_gcm_open,
    aes_gcm_seal,
    derive_chat_key,
    load_private_key_from_pem,
    load_public_key_from_pem,
    rsa_oaep_decrypt,
    rsa_oaep_encrypt,
)
from .udp_auth import (
    C1_RESEND_SEC,
    CHALLENGE_BYTES,
    KIND_C1,
    KIND_C2,
    KIND_C3,
    KIND_C4,
    KIND_CHAT,
    MutualAuthFailed,
    pack_typed,
    pubkey_initiator_is_local,
    unpack_typed,
)

logger = logging.getLogger(__name__)

Addr = Tuple[str, int]
OnMessage = Callable[[Addr, str], None]
OnStatus = Callable[[str], None]

MAX_CHAT_BLOB = 1200 + 64
MAX_CHAT_PLAIN = 1200


@dataclass(frozen=True)
class Session:
    peer: Addr
    key: bytes


class _UdpQueueProto(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue) -> None:
        self.queue = queue

    def datagram_received(self, data: bytes, addr: Addr) -> None:
        self.queue.put_nowait((data, addr))


class SessionManager:
    """
    Single-port UDP multiplexing for multiple peers.

    - One UDP socket bound to local_port.
    - Each peer (ip, port) has its own handshake state and session key.
    - Chat messages are typed frames: KIND_CHAT + aes_gcm blob.
    """

    def __init__(
        self,
        *,
        local_port: int,
        local_private_key_pem: bytes,
        on_message: OnMessage,
        on_status: Optional[OnStatus] = None,
    ) -> None:
        self.local_port = local_port
        self._sk: rsa.RSAPrivateKey = load_private_key_from_pem(local_private_key_pem)
        self._on_message = on_message
        self._on_status = on_status

        self._transport: asyncio.DatagramTransport | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._dispatch_task: asyncio.Task | None = None

        # per-peer typed message queues (kind, body)
        self._peer_q: dict[Addr, asyncio.Queue] = {}
        self._handshake_tasks: dict[Addr, asyncio.Task] = {}
        self._sessions: dict[Addr, Session] = {}

    @property
    def sockname(self) -> Optional[Addr]:
        if self._transport is None:
            return None
        sn = self._transport.get_extra_info("sockname")
        return sn if isinstance(sn, tuple) and len(sn) >= 2 else None

    async def start(self) -> None:
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpQueueProto(self._queue),
            local_addr=("0.0.0.0", self.local_port),
        )
        self._transport = transport
        self._dispatch_task = loop.create_task(self._dispatch_loop())
        if self._on_status:
            self._on_status(f"udp_listen {self.sockname}")

    async def close(self) -> None:
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatch_task
        for t in list(self._handshake_tasks.values()):
            t.cancel()
        for t in list(self._handshake_tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await t
        if self._transport is not None:
            self._transport.close()
        self._transport = None

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def has_session(self, peer: Addr) -> bool:
        return peer in self._sessions

    def send(self, peer: Addr, text: str) -> None:
        sess = self._sessions.get(peer)
        if sess is None:
            raise ValueError("no session for peer")
        payload = text.encode("utf-8")
        if len(payload) > MAX_CHAT_PLAIN:
            raise ValueError("message too long")
        blob = aes_gcm_seal(sess.key, payload)
        if self._transport is None:
            raise RuntimeError("manager not started")
        self._transport.sendto(pack_typed(KIND_CHAT, blob), peer)

    async def connect_peer(self, *, peer_ip: str, peer_port: int, peer_public_key_pem: bytes) -> Addr:
        """
        Establish (or reuse) a session with a peer. Always performs RSA auth if no session exists.
        """
        peer: Addr = (peer_ip, int(peer_port))
        if peer in self._sessions:
            return peer
        if self._transport is None:
            await self.start()
        # start handshake task and await result via per-peer queue
        pk = load_public_key_from_pem(peer_public_key_pem)
        if peer in self._handshake_tasks:
            await self._handshake_tasks[peer]
            return peer
        t = asyncio.create_task(self._handshake(peer, pk))
        self._handshake_tasks[peer] = t
        await t
        return peer

    # ---------------- internal ----------------
    def _get_peer_queue(self, peer: Addr) -> asyncio.Queue:
        q = self._peer_q.get(peer)
        if q is None:
            q = asyncio.Queue()
            self._peer_q[peer] = q
        return q

    async def _dispatch_loop(self) -> None:
        while True:
            raw, addr = await self._queue.get()
            try:
                kind, body = unpack_typed(raw)
            except Exception:
                continue

            if kind == KIND_CHAT:
                sess = self._sessions.get(addr)
                if sess is None:
                    continue
                if not body or len(body) > MAX_CHAT_BLOB:
                    continue
                try:
                    text = aes_gcm_open(sess.key, body).decode("utf-8", errors="replace")
                except Exception:
                    continue
                self._on_message(addr, text)
                continue

            # handshake kinds
            if kind in (KIND_C1, KIND_C2, KIND_C3, KIND_C4):
                # Auto-accept inbound handshake if C1 arrives from unknown peer and we have its public key.
                if kind == KIND_C1 and addr not in self._sessions and addr not in self._handshake_tasks:
                    c = find_contact_by_ipv4(addr[0])
                    if c is not None:
                        try:
                            pk = load_public_key_from_pem(c.public_key_pem.encode("utf-8"))
                        except Exception:
                            pk = None
                        if pk is not None:
                            self._handshake_tasks[addr] = asyncio.create_task(self._handshake_responder(addr, pk))
                self._get_peer_queue(addr).put_nowait((kind, body))

    async def _recv_kind(self, peer: Addr, expect_kind: int, *, deadline: float) -> bytes:
        q = self._get_peer_queue(peer)
        loop = asyncio.get_running_loop()
        while loop.time() < deadline:
            rem = deadline - loop.time()
            if rem <= 0:
                break
            try:
                kind, body = await asyncio.wait_for(q.get(), timeout=rem)
            except asyncio.TimeoutError:
                break
            if kind != expect_kind:
                continue
            return body
        raise MutualAuthFailed("握手超时或报文类型不匹配")

    async def _handshake(self, peer: Addr, peer_pk: rsa.RSAPublicKey, *, timeout: float = 90.0) -> None:
        # initiator or responder based on pubkey ordering
        if pubkey_initiator_is_local(self._sk, peer_pk):
            await self._handshake_initiator(peer, peer_pk, timeout=timeout)
        else:
            await self._handshake_responder(peer, peer_pk, timeout=timeout)

    async def _handshake_initiator(self, peer: Addr, peer_pk: rsa.RSAPublicKey, *, timeout: float) -> None:
        assert self._transport is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        r_a = secrets.token_bytes(CHALLENGE_BYTES)
        c1 = rsa_oaep_encrypt(peer_pk, r_a)

        # resend c1 until c2 arrives
        c2: Optional[bytes] = None
        while loop.time() < deadline:
            self._transport.sendto(pack_typed(KIND_C1, c1), peer)
            wait = min(C1_RESEND_SEC, deadline - loop.time())
            if wait <= 0:
                break
            try:
                body = await self._recv_kind(peer, KIND_C2, deadline=loop.time() + wait)
                c2 = body
                break
            except MutualAuthFailed:
                continue

        if c2 is None:
            raise MutualAuthFailed("等待 Round1 应答超时（请确认对方已启动并端口一致）")

        try:
            opened = rsa_oaep_decrypt(self._sk, c2)
        except Exception as exc:
            raise MutualAuthFailed("Round1 解密失败") from exc
        if not hmac.compare_digest(opened, r_a):
            raise MutualAuthFailed("Round1 挑战不匹配")

        c3 = await self._recv_kind(peer, KIND_C3, deadline=deadline)
        try:
            r_b = rsa_oaep_decrypt(self._sk, c3)
        except Exception as exc:
            raise MutualAuthFailed("Round2 解密失败") from exc
        if len(r_b) != CHALLENGE_BYTES:
            raise MutualAuthFailed("挑战长度无效")

        c4 = rsa_oaep_encrypt(peer_pk, r_b)
        self._transport.sendto(pack_typed(KIND_C4, c4), peer)

        key = derive_chat_key(r_a, r_b)
        self._sessions[peer] = Session(peer=peer, key=key)
        if self._on_status:
            self._on_status(f"session_established peer={peer}")

    async def _handshake_responder(self, peer: Addr, peer_pk: rsa.RSAPublicKey, *, timeout: float = 90.0) -> None:
        assert self._transport is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        c1 = await self._recv_kind(peer, KIND_C1, deadline=deadline)
        try:
            r_a = rsa_oaep_decrypt(self._sk, c1)
        except Exception as exc:
            raise MutualAuthFailed("Round1 解密失败") from exc
        if len(r_a) != CHALLENGE_BYTES:
            raise MutualAuthFailed("挑战长度无效")

        c2 = rsa_oaep_encrypt(peer_pk, r_a)
        self._transport.sendto(pack_typed(KIND_C2, c2), peer)

        r_b = secrets.token_bytes(CHALLENGE_BYTES)
        c3 = rsa_oaep_encrypt(peer_pk, r_b)
        self._transport.sendto(pack_typed(KIND_C3, c3), peer)

        c4 = await self._recv_kind(peer, KIND_C4, deadline=deadline)
        try:
            opened = rsa_oaep_decrypt(self._sk, c4)
        except Exception as exc:
            raise MutualAuthFailed("Round2 解密失败") from exc
        if not hmac.compare_digest(opened, r_b):
            raise MutualAuthFailed("Round2 挑战不匹配")

        key = derive_chat_key(r_a, r_b)
        self._sessions[peer] = Session(peer=peer, key=key)
        if self._on_status:
            self._on_status(f"session_established peer={peer}")

