from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path

from ..crypto import (
    generate_rsa_keypair,
    load_private_key_from_pem,
    private_key_to_pem,
    public_key_to_pem,
    write_private_key_pem,
    write_public_key_pem,
)
from ..udp_chat_session import MutualAuthFailed, UdpChatSession


DEFAULT_KEY_DIR = Path.home() / ".yxl_lace"
DEFAULT_PRIVATE_KEY_PATH = DEFAULT_KEY_DIR / "rsa_private.pem"
DEFAULT_PUBLIC_KEY_PATH = DEFAULT_KEY_DIR / "rsa_public.pem"
DEFAULT_COMM_PORT_FILE = DEFAULT_KEY_DIR / "default_comm_port"
DEFAULT_COMM_PORT_FALLBACK = 9001


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


@dataclass(frozen=True)
class PeerConfig:
    host: str
    port: int
    public_pem: bytes


class AsyncioThread:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._started = threading.Event()

    def start(self) -> None:
        self._thread.start()
        self._started.wait(timeout=5)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self._started.set()
        loop.run_forever()

    def submit(self, coro):
        if self.loop is None:
            raise RuntimeError("asyncio loop not started")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self.loop.stop)


def _require_tkinter():
    """
    Import tkinter lazily, so environments without `_tkinter` can still use CLI/library.
    """
    try:
        import tkinter as tk  # noqa: PLC0415
        from tkinter import messagebox, scrolledtext  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Tkinter is not available in this Python environment. "
            "Please install/enable Tk support (e.g. a Python build with `_tkinter`). "
            f"Original error: {exc!r}"
        ) from exc
    return tk, messagebox, scrolledtext


def main() -> None:
    tk, messagebox, scrolledtext = _require_tkinter()

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("YXL-LACE GUI")
            self.geometry("880x560")

            self._aio = AsyncioThread()
            self._aio.start()

            self._session: UdpChatSession | None = None

            self._build_ui()
            self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---------- UI ----------
        def _build_ui(self) -> None:
            root = tk.Frame(self)
            root.pack(fill=tk.BOTH, expand=True)

            # left: connect panel
            left = tk.Frame(root, padx=10, pady=10)
            left.pack(side=tk.LEFT, fill=tk.Y)

            tk.Label(left, text="Peer IPv4").pack(anchor="w")
            self.peer_host = tk.Entry(left, width=28)
            self.peer_host.pack(fill=tk.X)

            tk.Label(left, text="Peer port").pack(anchor="w", pady=(10, 0))
            self.peer_port = tk.Entry(left, width=28)
            self.peer_port.insert(0, str(read_default_comm_port()))
            self.peer_port.pack(fill=tk.X)

            tk.Label(left, text="Local port").pack(anchor="w", pady=(10, 0))
            self.local_port = tk.Entry(left, width=28)
            self.local_port.insert(0, str(read_default_comm_port()))
            self.local_port.pack(fill=tk.X)

            tk.Label(left, text="Peer public key (PEM)").pack(anchor="w", pady=(10, 0))
            self.peer_pem = scrolledtext.ScrolledText(left, width=34, height=12)
            self.peer_pem.pack(fill=tk.BOTH, expand=False)

            btns = tk.Frame(left, pady=10)
            btns.pack(fill=tk.X)
            tk.Button(btns, text="Generate keys", command=self._on_generate_keys).pack(
                side=tk.LEFT, expand=True, fill=tk.X
            )
            tk.Button(btns, text="Connect", command=self._on_connect).pack(
                side=tk.LEFT, expand=True, fill=tk.X, padx=(8, 0)
            )

            self.status = tk.StringVar(value="Ready.")
            tk.Label(left, textvariable=self.status, wraplength=250, justify="left").pack(
                anchor="w", pady=(6, 0)
            )

            # right: chat panel
            right = tk.Frame(root, padx=10, pady=10)
            right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

            self.chat_log = scrolledtext.ScrolledText(right, state="disabled", height=22)
            self.chat_log.pack(fill=tk.BOTH, expand=True)

            bottom = tk.Frame(right, pady=8)
            bottom.pack(fill=tk.X)

            self.msg_entry = tk.Entry(bottom)
            self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.msg_entry.bind("<Return>", lambda _e: self._on_send())

            tk.Button(bottom, text="Send", command=self._on_send).pack(side=tk.LEFT, padx=(8, 0))
            tk.Button(bottom, text="Disconnect", command=self._on_disconnect).pack(
                side=tk.LEFT, padx=(8, 0)
            )

        # ---------- helpers ----------
        def _ui(self, fn, *args, **kwargs):
            self.after(0, lambda: fn(*args, **kwargs))

        def _append_chat(self, who: str, text: str) -> None:
            self.chat_log.configure(state="normal")
            self.chat_log.insert("end", f"[{who}] {text}\n")
            self.chat_log.see("end")
            self.chat_log.configure(state="disabled")

        def _set_status(self, s: str) -> None:
            self.status.set(s)

        # ---------- actions ----------
        def _on_generate_keys(self) -> None:
            try:
                DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
                sk = generate_rsa_keypair(2048)
                priv_pem = private_key_to_pem(sk)
                pub_pem = public_key_to_pem(sk.public_key())
                write_private_key_pem(DEFAULT_PRIVATE_KEY_PATH, priv_pem)
                write_public_key_pem(DEFAULT_PUBLIC_KEY_PATH, pub_pem)
                messagebox.showinfo(
                    "Keys generated",
                    f"Saved:\n{DEFAULT_PRIVATE_KEY_PATH}\n{DEFAULT_PUBLIC_KEY_PATH}\n\nPublic key copied to clipboard.",
                )
                self.clipboard_clear()
                self.clipboard_append(pub_pem.decode("utf-8"))
            except Exception as exc:
                messagebox.showerror("Error", f"Failed to generate keys: {exc!r}")

        def _read_peer_cfg(self) -> PeerConfig:
            host = self.peer_host.get().strip()
            if not host:
                raise ValueError("peer host is empty")
            try:
                port = int(self.peer_port.get().strip())
            except ValueError as exc:
                raise ValueError("peer port must be integer") from exc
            if not (1 <= port <= 65535):
                raise ValueError("peer port out of range")
            pem = self.peer_pem.get("1.0", "end").strip().encode("utf-8")
            if not pem:
                raise ValueError("peer public key is empty")
            return PeerConfig(host=host, port=port, public_pem=pem)

        def _load_local_private_pem(self) -> bytes:
            if not DEFAULT_PRIVATE_KEY_PATH.is_file():
                raise FileNotFoundError(
                    f"Local private key not found: {DEFAULT_PRIVATE_KEY_PATH} (Generate keys first)"
                )
            return DEFAULT_PRIVATE_KEY_PATH.read_bytes()

        def _on_connect(self) -> None:
            if self._session is not None:
                messagebox.showinfo("Already connected", "Please disconnect first.")
                return
            try:
                cfg = self._read_peer_cfg()
                local_port = int(self.local_port.get().strip())
                if not (1 <= local_port <= 65535):
                    raise ValueError("local port out of range")
                local_priv_pem = self._load_local_private_pem()
                load_private_key_from_pem(local_priv_pem)
            except Exception as exc:
                messagebox.showerror("Invalid input", str(exc))
                return

            self._set_status("Connecting… (UDP RSA handshake)")

            def on_message(text: str) -> None:
                self._ui(self._append_chat, "peer", text)

            def on_status(s: str) -> None:
                self._ui(self._set_status, s)

            async def _do_connect():
                try:
                    sess = await UdpChatSession.connect(
                        peer_host=cfg.host,
                        peer_port=cfg.port,
                        local_port=local_port,
                        local_private_key_pem=local_priv_pem,
                        peer_public_key_pem=cfg.public_pem,
                        on_message=on_message,
                        on_status=on_status,
                    )
                except MutualAuthFailed as exc:
                    self._ui(messagebox.showerror, "Auth failed", str(exc))
                    self._ui(self._set_status, "Auth failed.")
                    return
                except Exception as exc:
                    self._ui(messagebox.showerror, "Connect failed", repr(exc))
                    self._ui(self._set_status, "Connect failed.")
                    return

                self._session = sess
                sn = sess.local_sockname
                self._ui(
                    self._set_status, f"Connected. local={sn} peer=({sess.peer.ip},{sess.peer.port})"
                )

            self._aio.submit(_do_connect())

        def _on_send(self) -> None:
            text = self.msg_entry.get().strip()
            if not text:
                return
            self.msg_entry.delete(0, "end")
            self._append_chat("me", text)
            sess = self._session
            if sess is None:
                self._set_status("Not connected.")
                return
            try:
                sess.send(text)
            except Exception as exc:
                self._set_status(f"Send failed: {exc}")

        def _on_disconnect(self) -> None:
            sess = self._session
            if sess is None:
                return
            self._session = None
            try:
                sess.close()
            finally:
                self._set_status("Disconnected.")

        def _on_close(self) -> None:
            try:
                if self._session is not None:
                    self._session.close()
            finally:
                self._aio.stop()
                self.destroy()

    App().mainloop()

