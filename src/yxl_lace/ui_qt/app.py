from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
import sys

from ..crypto import (
    generate_rsa_keypair,
    load_private_key_from_pem,
    private_key_to_pem,
    public_key_to_pem,
    write_private_key_pem,
    write_public_key_pem,
)
from ..udp_chat_session import MutualAuthFailed, UdpChatSession
from ..contacts import Contact, load_contacts, upsert_contact, validate_contact_id, validate_ipv4, validate_label, validate_port, normalize_public_key_pem
from ..session_manager import SessionManager


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


def _require_pyside6():
    """
    Import PySide6 lazily, so missing GUI deps won't break CLI usage.
    """
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "PySide6 is not installed. Install GUI deps with:\n"
            "  pip install PySide6\n"
            f"Original error: {exc!r}"
        ) from exc
    return QtCore, QtGui, QtWidgets


def _resource_path(rel: str) -> str:
    """
    Resolve resource path for both source run and PyInstaller onefile.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return str(Path(base) / rel)
    # repo root: .../src/yxl_lace/ui_qt/app.py -> ../../..
    return str((Path(__file__).resolve().parents[3] / rel).resolve())


def main() -> None:
    QtCore, QtGui, QtWidgets = _require_pyside6()

    class MainWindow(QtWidgets.QMainWindow):
        messageReceived = QtCore.Signal(tuple, str)  # peer(addr), text
        statusChanged = QtCore.Signal(str)
        connectSucceeded = QtCore.Signal(tuple)  # peer addr
        connectFailed = QtCore.Signal(str, str)  # title, message

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("YXL-LACE GUI (Qt)")
            self.resize(980, 620)

            self._aio = AsyncioThread()
            self._aio.start()
            self._mgr: SessionManager | None = None
            self._peer_tabs: dict[tuple[str, int], QtWidgets.QPlainTextEdit] = {}

            self._build_ui()
            self._wire_signals()

        def _build_ui(self) -> None:
            central = QtWidgets.QWidget()
            self.setCentralWidget(central)

            layout = QtWidgets.QHBoxLayout(central)

            # Left: contacts + connect pane
            left = QtWidgets.QWidget()
            left_layout = QtWidgets.QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)

            left_layout.addWidget(QtWidgets.QLabel("Contacts"))
            self.contactsList = QtWidgets.QListWidget()
            self.contactsList.setMinimumWidth(340)
            left_layout.addWidget(self.contactsList, 1)

            contact_btns = QtWidgets.QHBoxLayout()
            self.btnAddContact = QtWidgets.QPushButton("Add")
            self.btnConnectContact = QtWidgets.QPushButton("Connect")
            contact_btns.addWidget(self.btnAddContact)
            contact_btns.addWidget(self.btnConnectContact)
            left_layout.addLayout(contact_btns)

            left_layout.addSpacing(10)
            form = QtWidgets.QFormLayout()
            self.peerHost = QtWidgets.QLineEdit()
            self.peerPort = QtWidgets.QLineEdit(str(read_default_comm_port()))
            self.localPort = QtWidgets.QLineEdit(str(read_default_comm_port()))
            form.addRow("Peer IPv4", self.peerHost)
            form.addRow("Peer port", self.peerPort)
            form.addRow("Local port", self.localPort)
            left_layout.addLayout(form)

            left_layout.addWidget(QtWidgets.QLabel("Peer public key (PEM)"))
            self.peerPem = QtWidgets.QPlainTextEdit()
            self.peerPem.setPlaceholderText("-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----")
            self.peerPem.setMinimumWidth(340)
            left_layout.addWidget(self.peerPem, 1)

            btn_row = QtWidgets.QHBoxLayout()
            self.btnGenKeys = QtWidgets.QPushButton("Generate keys")
            self.btnConnect = QtWidgets.QPushButton("Connect (manual)")
            btn_row.addWidget(self.btnGenKeys)
            btn_row.addWidget(self.btnConnect)
            left_layout.addLayout(btn_row)

            self.statusLabel = QtWidgets.QLabel("Ready.")
            self.statusLabel.setWordWrap(True)
            left_layout.addWidget(self.statusLabel)

            # Right: chat pane (tabs per peer)
            right = QtWidgets.QWidget()
            right_layout = QtWidgets.QVBoxLayout(right)
            right_layout.setContentsMargins(0, 0, 0, 0)

            self.chatTabs = QtWidgets.QTabWidget()
            right_layout.addWidget(self.chatTabs, 1)

            send_row = QtWidgets.QHBoxLayout()
            self.msgEdit = QtWidgets.QLineEdit()
            self.msgEdit.setPlaceholderText("Type message…")
            self.btnSend = QtWidgets.QPushButton("Send")
            self.btnDisconnect = QtWidgets.QPushButton("Disconnect")
            send_row.addWidget(self.msgEdit, 1)
            send_row.addWidget(self.btnSend)
            send_row.addWidget(self.btnDisconnect)
            right_layout.addLayout(send_row)

            layout.addWidget(left, 0)
            layout.addWidget(right, 1)

        def _wire_signals(self) -> None:
            self.btnGenKeys.clicked.connect(self.onGenerateKeys)
            self.btnConnect.clicked.connect(self.onConnect)
            self.btnSend.clicked.connect(self.onSend)
            self.btnDisconnect.clicked.connect(self.onDisconnect)
            self.msgEdit.returnPressed.connect(self.onSend)
            self.btnAddContact.clicked.connect(self.onAddContact)
            self.btnConnectContact.clicked.connect(self.onConnectSavedContact)
            self.contactsList.itemSelectionChanged.connect(self._sync_manual_fields_from_selected_contact)

            self.messageReceived.connect(self._on_message)
            self.statusChanged.connect(self.statusLabel.setText)
            self.connectFailed.connect(lambda title, msg: QtWidgets.QMessageBox.critical(self, title, msg))
            self.connectSucceeded.connect(self._on_connect_succeeded)
            self._reload_contacts()

        def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
            try:
                if self._mgr is not None:
                    # stop manager loop
                    self._aio.submit(self._mgr.close())
            finally:
                self._aio.stop()
            super().closeEvent(event)

        def _ensure_tab(self, peer: tuple[str, int]) -> QtWidgets.QPlainTextEdit:
            w = self._peer_tabs.get(peer)
            if w is not None:
                return w
            log = QtWidgets.QPlainTextEdit()
            log.setReadOnly(True)
            self._peer_tabs[peer] = log
            self.chatTabs.addTab(log, f"{peer[0]}:{peer[1]}")
            return log

        def _append_chat(self, peer: tuple[str, int], who: str, text: str) -> None:
            log = self._ensure_tab(peer)
            log.appendPlainText(f"[{who}] {text}")
            self.chatTabs.setCurrentWidget(log)

        def _on_message(self, peer: tuple, text: str) -> None:
            p = (str(peer[0]), int(peer[1]))
            self._append_chat(p, "peer", text)

        def onGenerateKeys(self) -> None:
            try:
                DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
                sk = generate_rsa_keypair(2048)
                priv_pem = private_key_to_pem(sk)
                pub_pem = public_key_to_pem(sk.public_key())
                write_private_key_pem(DEFAULT_PRIVATE_KEY_PATH, priv_pem)
                write_public_key_pem(DEFAULT_PUBLIC_KEY_PATH, pub_pem)
                QtWidgets.QApplication.clipboard().setText(pub_pem.decode("utf-8"))
                QtWidgets.QMessageBox.information(
                    self,
                    "Keys generated",
                    f"Saved:\n{DEFAULT_PRIVATE_KEY_PATH}\n{DEFAULT_PUBLIC_KEY_PATH}\n\nPublic key copied to clipboard.",
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to generate keys: {exc!r}")

        def _read_peer_cfg(self) -> PeerConfig:
            host = self.peerHost.text().strip()
            if not host:
                raise ValueError("peer host is empty")
            try:
                port = int(self.peerPort.text().strip())
            except ValueError as exc:
                raise ValueError("peer port must be integer") from exc
            if not (1 <= port <= 65535):
                raise ValueError("peer port out of range")
            pem = self.peerPem.toPlainText().strip().encode("utf-8")
            if not pem:
                raise ValueError("peer public key is empty")
            return PeerConfig(host=host, port=port, public_pem=pem)

        def _reload_contacts(self) -> None:
            self.contactsList.clear()
            for c in load_contacts():
                item = QtWidgets.QListWidgetItem(f"{c.id} — {c.label} — {c.ipv4}:{c.port}")
                item.setData(QtCore.Qt.ItemDataRole.UserRole, c.id)
                self.contactsList.addItem(item)

        def _sync_manual_fields_from_selected_contact(self) -> None:
            items = self.contactsList.selectedItems()
            if not items:
                return
            cid = items[0].data(QtCore.Qt.ItemDataRole.UserRole)
            c = next((x for x in load_contacts() if x.id == cid), None)
            if c is None:
                return
            self.peerHost.setText(c.ipv4)
            self.peerPort.setText(str(c.port))
            self.peerPem.setPlainText(c.public_key_pem)

        def onAddContact(self) -> None:
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("Add contact")
            lay = QtWidgets.QFormLayout(dlg)
            e_id = QtWidgets.QLineEdit()
            e_label = QtWidgets.QLineEdit()
            e_ip = QtWidgets.QLineEdit()
            e_port = QtWidgets.QLineEdit(str(read_default_comm_port()))
            e_pem = QtWidgets.QPlainTextEdit()
            e_pem.setPlaceholderText("-----BEGIN PUBLIC KEY-----\\n...\\n-----END PUBLIC KEY-----")
            lay.addRow("id", e_id)
            lay.addRow("label", e_label)
            lay.addRow("ipv4", e_ip)
            lay.addRow("port", e_port)
            lay.addRow("public key (PEM)", e_pem)
            btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
            lay.addRow(btns)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            try:
                c = Contact(
                    id=validate_contact_id(e_id.text()),
                    label=validate_label(e_label.text()),
                    ipv4=validate_ipv4(e_ip.text()),
                    port=validate_port(int(e_port.text())),
                    public_key_pem=normalize_public_key_pem(e_pem.toPlainText()),
                )
                upsert_contact(c)
                self._reload_contacts()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Invalid", str(exc))

        def _load_local_private_pem(self) -> bytes:
            if not DEFAULT_PRIVATE_KEY_PATH.is_file():
                raise FileNotFoundError(
                    f"Local private key not found: {DEFAULT_PRIVATE_KEY_PATH} (Generate keys first)"
                )
            return DEFAULT_PRIVATE_KEY_PATH.read_bytes()

        def onConnect(self) -> None:
            # manual connect: creates/uses manager and adds a session/tab
            try:
                cfg = self._read_peer_cfg()
                local_port = int(self.localPort.text().strip())
                if not (1 <= local_port <= 65535):
                    raise ValueError("local port out of range")
                local_priv_pem = self._load_local_private_pem()
                load_private_key_from_pem(local_priv_pem)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Invalid input", str(exc))
                return

            self.btnConnect.setEnabled(False)
            self.statusChanged.emit("Connecting… (UDP RSA handshake)")

            async def _do_connect():
                try:
                    if self._mgr is None:
                        self._mgr = SessionManager(
                            local_port=local_port,
                            local_private_key_pem=local_priv_pem,
                            on_message=lambda peer, text: self.messageReceived.emit(peer, text),
                            on_status=lambda s: self.statusChanged.emit(s),
                        )
                        await self._mgr.start()
                    peer = await self._mgr.connect_peer(
                        peer_ip=cfg.host, peer_port=cfg.port, peer_public_key_pem=cfg.public_pem
                    )
                except MutualAuthFailed as exc:
                    self.connectFailed.emit("Auth failed", str(exc))
                    self.statusChanged.emit("Auth failed.")
                    self.btnConnect.setEnabled(True)
                    return
                except Exception as exc:
                    self.connectFailed.emit("Connect failed", repr(exc))
                    self.statusChanged.emit("Connect failed.")
                    self.btnConnect.setEnabled(True)
                    return
                self.connectSucceeded.emit(peer)

            self._aio.submit(_do_connect())

        def onConnectSavedContact(self) -> None:
            items = self.contactsList.selectedItems()
            if not items:
                QtWidgets.QMessageBox.information(self, "No contact", "Select a contact first.")
                return
            cid = items[0].data(QtCore.Qt.ItemDataRole.UserRole)
            c = next((x for x in load_contacts() if x.id == cid), None)
            if c is None:
                return
            self.peerHost.setText(c.ipv4)
            self.peerPort.setText(str(c.port))
            self.peerPem.setPlainText(c.public_key_pem)
            self.onConnect()

        def _on_connect_succeeded(self, peer: tuple) -> None:
            p = (str(peer[0]), int(peer[1]))
            self._ensure_tab(p)
            sn = self._mgr.sockname if self._mgr else None
            self.statusLabel.setText(f"Connected. local={sn} peer={p}")
            self.btnConnect.setEnabled(True)

        def onSend(self) -> None:
            text = self.msgEdit.text().strip()
            if not text:
                return
            self.msgEdit.clear()
            cur = self.chatTabs.currentWidget()
            peer: Optional[tuple[str, int]] = None
            for k, v in self._peer_tabs.items():
                if v is cur:
                    peer = k
                    break
            if peer is None:
                self.statusLabel.setText("Select a chat tab first.")
                return
            self._append_chat(peer, "me", text)
            if self._mgr is None:
                self.statusLabel.setText("Not connected.")
                return
            try:
                self._mgr.send(peer, text)
            except Exception as exc:
                self.statusLabel.setText(f"Send failed: {exc}")

        def onDisconnect(self) -> None:
            if self._mgr is None:
                return
            # For simplicity: close all sessions/stop manager
            mgr = self._mgr
            self._mgr = None
            self._peer_tabs.clear()
            self.chatTabs.clear()
            self._aio.submit(mgr.close())
            self.statusLabel.setText("Disconnected.")

    app = QtWidgets.QApplication([])
    # App/window icon (used by run_UI.sh and packaged binary)
    icon_path = _resource_path("assets/app.png")
    if Path(icon_path).is_file():
        app.setWindowIcon(QtGui.QIcon(icon_path))
    win = MainWindow()
    win.show()
    app.exec()

