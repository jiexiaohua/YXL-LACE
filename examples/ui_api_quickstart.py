from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yxl_lace.ui_api import ChatUiApi, MessageEvent, StateEvent  # noqa: E402


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    api = ChatUiApi(peer_id="alice", psk="demo-key", bind_port=9001)

    async def on_message(event: MessageEvent) -> None:
        print(f"[recv] from {event.from_peer.host}:{event.from_peer.port} => {event.text}")

    def on_state(event: StateEvent) -> None:
        print(f"[state] {event.state}: {event.detail}")

    def on_error(exc: Exception) -> None:
        print(f"[error] {exc}")

    api.set_message_callback(on_message)
    api.set_state_callback(on_state)
    api.set_error_callback(on_error)

    await api.start()
    await api.set_peer("127.0.0.1", 9002)
    await api.send("hello from ui api")

    await asyncio.sleep(1)
    await api.stop()


if __name__ == "__main__":
    asyncio.run(main())
