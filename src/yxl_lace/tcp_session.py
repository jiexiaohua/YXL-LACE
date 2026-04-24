from __future__ import annotations

import asyncio
import contextlib
import logging

from .crypto import aes_gcm_open, aes_gcm_seal

MAX_CHAT_PLAIN = 256 * 1024

logger = logging.getLogger(__name__)


async def _read_chat_frame(reader: asyncio.StreamReader) -> bytes:
    hdr = await reader.readexactly(4)
    n = int.from_bytes(hdr, "big")
    if n <= 0 or n > MAX_CHAT_PLAIN + 64:
        raise ValueError("invalid chat frame size")
    return await reader.readexactly(n)


async def _write_chat_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    writer.write(len(payload).to_bytes(4, "big") + payload)
    await writer.drain()


async def chat_loop(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    session_key: bytes,
) -> None:
    """TCP 全双工聊天：一行一条消息，UTF-8，AES-GCM 封装。"""

    async def recv_task() -> None:
        try:
            while True:
                blob = await _read_chat_frame(reader)
                text = aes_gcm_open(session_key, blob).decode("utf-8", errors="replace")
                print(f"\n[peer] {text}")
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            logger.info("receive side closed: %s", exc)
        except Exception as exc:
            logger.warning("receive error: %s", exc)
        finally:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    recv = asyncio.create_task(recv_task())
    try:
        while True:
            line = await asyncio.to_thread(input, "> ")
            line = line.rstrip("\n\r")
            if recv.done():
                print("连接已结束。")
                break
            if line == "/quit":
                break
            blob = aes_gcm_seal(session_key, line.encode("utf-8"))
            await _write_chat_frame(writer, blob)
    finally:
        recv.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await recv
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()
