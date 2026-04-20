from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Tuple

from .peer import UdpPeer

Addr = Tuple[str, int]


@dataclass(frozen=True)
class PeerEndpoint:
    host: str
    port: int

    def as_addr(self) -> Addr:
        return (self.host, self.port)


@dataclass(frozen=True)
class MessageEvent:
    text: str
    from_peer: PeerEndpoint


@dataclass(frozen=True)
class StateEvent:
    state: str
    detail: str


MessageCallback = Callable[[MessageEvent], Optional[Awaitable[None]]]
StateCallback = Callable[[StateEvent], Optional[Awaitable[None]]]
ErrorCallback = Callable[[Exception], Optional[Awaitable[None]]]


class ChatUiApi:
    """UI-friendly async API wrapper for the UDP chat transport.

    Typical UI lifecycle:
    1. create api
    2. register callbacks
    3. await start()
    4. await set_peer(...)
    5. await send(...)
    6. optional: await set_peer(...) to switch target
    7. await stop()
    """

    def __init__(
        self,
        *,
        peer_id: str,
        psk: str,
        bind_port: int,
        bind_host: str = "0.0.0.0",
        connect_timeout: float = 30.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.peer_id = peer_id
        self.psk = psk
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.connect_timeout = connect_timeout

        self.logger = logger or logging.getLogger(f"yxl_lace.ui_api.{peer_id}")

        self._peer = UdpPeer(
            peer_id=peer_id,
            psk=psk,
            bind_host=bind_host,
            bind_port=bind_port,
        )
        self._current_peer: Optional[PeerEndpoint] = None
        self._started = False

        self._on_message: Optional[MessageCallback] = None
        self._on_state: Optional[StateCallback] = None
        self._on_error: Optional[ErrorCallback] = None

    def set_message_callback(self, callback: MessageCallback) -> None:
        self._on_message = callback

    def set_state_callback(self, callback: StateCallback) -> None:
        self._on_state = callback

    def set_error_callback(self, callback: ErrorCallback) -> None:
        self._on_error = callback

    @property
    def current_peer(self) -> Optional[PeerEndpoint]:
        return self._current_peer

    async def start(self) -> None:
        if self._started:
            return

        async def _on_message(text: str, from_addr: Addr) -> None:
            event = MessageEvent(text=text, from_peer=PeerEndpoint(host=from_addr[0], port=from_addr[1]))
            await self._safe_emit_message(event)

        self._peer.set_message_handler(_on_message)
        await self._peer.start()
        self._started = True
        await self._safe_emit_state(StateEvent(state="started", detail=f"listening on {self.bind_host}:{self.bind_port}"))

    async def stop(self) -> None:
        if not self._started:
            return
        await self._peer.stop()
        self._started = False
        await self._safe_emit_state(StateEvent(state="stopped", detail="transport stopped"))

    async def set_peer(self, host: str, port: int, *, auto_connect: bool = True) -> None:
        endpoint = PeerEndpoint(host=host, port=port)
        self._current_peer = endpoint
        await self._safe_emit_state(StateEvent(state="peer_changed", detail=f"peer={host}:{port}"))

        if auto_connect:
            try:
                await self._peer.connect(endpoint.as_addr(), timeout=self.connect_timeout)
                await self._safe_emit_state(StateEvent(state="connected", detail=f"peer={host}:{port}"))
            except Exception as exc:
                await self._safe_emit_error(exc)
                raise

    async def clear_peer(self) -> None:
        self._current_peer = None
        await self._safe_emit_state(StateEvent(state="peer_cleared", detail="no active peer"))

    async def send(self, text: str) -> None:
        if self._current_peer is None:
            raise RuntimeError("no active peer, call set_peer() first")

        try:
            await self._peer.connect(self._current_peer.as_addr(), timeout=self.connect_timeout)
            await self._peer.send_text(self._current_peer.as_addr(), text)
            await self._safe_emit_state(
                StateEvent(
                    state="message_sent",
                    detail=f"to={self._current_peer.host}:{self._current_peer.port}",
                )
            )
        except Exception as exc:
            await self._safe_emit_error(exc)
            raise

    async def send_to(self, host: str, port: int, text: str) -> None:
        await self.set_peer(host, port, auto_connect=True)
        await self.send(text)

    async def _safe_emit_message(self, event: MessageEvent) -> None:
        if self._on_message is None:
            return
        await self._invoke_callback(self._on_message, event)

    async def _safe_emit_state(self, event: StateEvent) -> None:
        if self._on_state is None:
            return
        await self._invoke_callback(self._on_state, event)

    async def _safe_emit_error(self, exc: Exception) -> None:
        self.logger.error("ui api error: %s", exc)
        if self._on_error is None:
            return
        await self._invoke_callback(self._on_error, exc)

    async def _invoke_callback(self, callback: Callable[..., object], arg: object) -> None:
        result = callback(arg)
        if inspect.isawaitable(result):
            await result
