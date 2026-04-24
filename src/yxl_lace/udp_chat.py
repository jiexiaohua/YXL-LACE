from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional, Tuple

from .crypto import aes_gcm_open, aes_gcm_seal

logger = logging.getLogger(__name__)

Addr = Tuple[str, int]

# UDP 单报文建议保持较小，避免 IP 分片导致丢包概率上升。
MAX_UDP_PLAIN = 1200
# AESGCM nonce(12) + tag(16) + 少量开销；这里只做粗略上限，主要限制明文长度。
MAX_UDP_BLOB = MAX_UDP_PLAIN + 64


class _UdpQueueProto(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue) -> None:
        self.queue = queue

    def datagram_received(self, data: bytes, addr: Addr) -> None:
        self.queue.put_nowait((data, addr))


async def udp_chat_loop(
    *,
    session_key: bytes,
    local_port: int,
    peer_ip: str,
    peer_port: int,
) -> None:
    """
    UDP + AES-GCM 全双工聊天。

    - 本机固定绑定 local_port（与 UDP 握手端口一致，便于对端回包）。
    - 仅接受来自 (peer_ip, peer_port) 的报文，避免局域网噪声干扰。
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _UdpQueueProto(queue),
        local_addr=("0.0.0.0", local_port),
    )
    peer: Addr = (peer_ip, peer_port)

    async def recv_task() -> None:
        try:
            while True:
                raw, addr = await queue.get()
                if addr != peer:
                    continue
                if not raw or len(raw) > MAX_UDP_BLOB:
                    continue
                try:
                    text = aes_gcm_open(session_key, raw).decode("utf-8", errors="replace")
                except Exception as exc:
                    logger.debug("udp decrypt failed from %s: %r", addr, exc)
                    continue
                print(f"\n[peer] {text}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("udp recv loop stopped: %r", exc)

    recv = asyncio.create_task(recv_task())
    try:
        print(
            f"UDP 加密聊天已就绪：本机 0.0.0.0:{local_port} ↔ 对端 {peer_ip}:{peer_port}\n"
            "输入 /quit 退出。",
            flush=True,
        )
        while True:
            line = await asyncio.to_thread(input, "> ")
            line = line.rstrip("\n\r")
            if line == "/quit":
                break
            payload = line.encode("utf-8")
            if len(payload) > MAX_UDP_PLAIN:
                print(f"消息过长（>{MAX_UDP_PLAIN} bytes），请分段发送。", flush=True)
                continue
            blob = aes_gcm_seal(session_key, payload)
            transport.sendto(blob, peer)
    finally:
        recv.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await recv
        transport.close()
