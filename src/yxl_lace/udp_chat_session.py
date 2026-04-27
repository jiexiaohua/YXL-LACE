from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .crypto import aes_gcm_open, aes_gcm_seal, load_private_key_from_pem, load_public_key_from_pem
from .udp_auth import MutualAuthFailed, handshake_udp_chat_symmetric

logger = logging.getLogger(__name__)

Addr = Tuple[str, int]
OnMessage = Callable[[str], None]
OnStatus = Callable[[str], None]

MAX_UDP_PLAIN = 1200
MAX_UDP_BLOB = MAX_UDP_PLAIN + 64


@dataclass(frozen=True)
class ChatPeer:
    ip: str
    port: int


class UdpChatSession:
    """
    UDP + AES-GCM chat session, designed for GUI usage.

    - No blocking input()/print().
    - Receive loop decrypts messages and calls `on_message`.
    - `send(text)` encrypts and sends to the peer.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        session_key: bytes,
        peer: ChatPeer,
        transport: asyncio.DatagramTransport,
        queue: asyncio.Queue,
        on_message: OnMessage,
        on_status: Optional[OnStatus] = None,
    ) -> None:
        self._loop = loop
        self._key = session_key
        self._peer = peer
        self._transport = transport
        self._queue = queue
        self._on_message = on_message
        self._on_status = on_status
        self._recv_task: asyncio.Task | None = None
        self._closed = False

    @property
    def peer(self) -> ChatPeer:
        return self._peer

    @property
    def local_sockname(self) -> Optional[Addr]:
        sn = self._transport.get_extra_info("sockname")
        return sn if isinstance(sn, tuple) and len(sn) >= 2 else None

    @classmethod
    async def connect(
        cls,
        *,
        peer_host: str,
        peer_port: int,
        local_port: int,
        local_private_key_pem: bytes,
        peer_public_key_pem: bytes,
        on_message: OnMessage,
        on_status: Optional[OnStatus] = None,
    ) -> "UdpChatSession":
        """
        Perform RSA+UDP mutual authentication, derive AES key, then return a ready session.
        """
        sk = load_private_key_from_pem(local_private_key_pem)
        pk = load_public_key_from_pem(peer_public_key_pem)
        loop = asyncio.get_running_loop()

        if on_status:
            on_status("udp_auth_start")
        session_key, peer_ip, transport, queue = await handshake_udp_chat_symmetric(
            peer_host, peer_port, local_port, sk, pk
        )
        sess = cls(
            loop=loop,
            session_key=session_key,
            peer=ChatPeer(ip=peer_ip, port=peer_port),
            transport=transport,
            queue=queue,
            on_message=on_message,
            on_status=on_status,
        )
        sess._start_recv()
        if on_status:
            sn = sess.local_sockname
            on_status(f"udp_ready local={sn} peer=({peer_ip},{peer_port})")
        return sess

    def _start_recv(self) -> None:
        if self._recv_task is not None:
            return

        async def _recv_loop() -> None:
            peer_addr: Addr = (self._peer.ip, self._peer.port)
            try:
                while True:
                    raw, addr = await self._queue.get()
                    if addr != peer_addr:
                        continue
                    if not raw or len(raw) > MAX_UDP_BLOB:
                        continue
                    try:
                        text = aes_gcm_open(self._key, raw).decode("utf-8", errors="replace")
                    except Exception as exc:
                        logger.debug("udp decrypt failed from %s: %r", addr, exc)
                        continue
                    self._on_message(text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.info("udp recv loop stopped: %r", exc)

        self._recv_task = self._loop.create_task(_recv_loop())

    def send(self, text: str) -> None:
        if self._closed:
            return
        payload = text.encode("utf-8")
        if len(payload) > MAX_UDP_PLAIN:
            raise ValueError(f"message too long (> {MAX_UDP_PLAIN} bytes)")
        blob = aes_gcm_seal(self._key, payload)
        self._transport.sendto(blob, (self._peer.ip, self._peer.port))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._recv_task is not None:
            self._recv_task.cancel()
        with contextlib.suppress(Exception):
            self._transport.close()

    async def wait_closed(self) -> None:
        if self._recv_task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await self._recv_task

