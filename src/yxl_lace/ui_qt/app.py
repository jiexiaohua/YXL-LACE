from __future__ import annotations

import asyncio
import contextlib
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
from ..contacts import Contact, add_contact, load_contacts, update_contact_label, validate_ipv4, validate_label, validate_port, normalize_public_key_pem
from ..session_manager import SessionManager
from ..print import get_lang, set_lang, t


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


def write_default_comm_port(port: int) -> None:
    DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_COMM_PORT_FILE.write_text(str(int(port)), encoding="utf-8")


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
        try:
            loop.run_forever()
        finally:
            try:
                loop.close()
            except Exception:
                pass

    def submit(self, coro):
        if self.loop is None:
            raise RuntimeError("asyncio loop not started")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        # best-effort join; keep daemon=True to avoid hard hang on exit
        self._thread.join(timeout=3)


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

    class SettingsDialog(QtWidgets.QDialog):
        def __init__(self, parent: "MainWindow") -> None:
            super().__init__(parent)
            self._mw = parent
            self.setWindowTitle(t("qt_settings_title"))
            self.setModal(True)
            self.resize(560, 420)

            lay = QtWidgets.QVBoxLayout(self)
            form = QtWidgets.QFormLayout()
            lay.addLayout(form)

            self.eLocalPort = QtWidgets.QLineEdit(str(read_default_comm_port()))
            form.addRow(t("qt_local_port"), self.eLocalPort)

            self.langCombo = QtWidgets.QComboBox()
            self.langCombo.addItem("English", "en")
            self.langCombo.addItem("中文", "zh")
            cur = get_lang()
            idx = self.langCombo.findData(cur)
            if idx >= 0:
                self.langCombo.setCurrentIndex(idx)
            form.addRow(t("qt_language"), self.langCombo)

            self.btnGenKeys = QtWidgets.QPushButton(t("qt_gen_keys"))
            self.btnCopyPub = QtWidgets.QPushButton(t("qt_copy_public_key"))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.btnGenKeys)
            row.addWidget(self.btnCopyPub)
            lay.addLayout(row)

            self.lblHint = QtWidgets.QLabel(t("qt_settings_hint"))
            self.lblHint.setWordWrap(True)
            lay.addWidget(self.lblHint)

            btns = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Save
                | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            )
            lay.addWidget(btns)

            btns.accepted.connect(self._on_save)
            btns.rejected.connect(self.reject)
            self.btnGenKeys.clicked.connect(self._on_gen_keys)
            self.btnCopyPub.clicked.connect(self._on_copy_public_key)

        def _on_gen_keys(self) -> None:
            try:
                DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
                sk = generate_rsa_keypair(2048)
                priv_pem = private_key_to_pem(sk)
                pub_pem = public_key_to_pem(sk.public_key())
                write_private_key_pem(DEFAULT_PRIVATE_KEY_PATH, priv_pem)
                write_public_key_pem(DEFAULT_PUBLIC_KEY_PATH, pub_pem)
                QtWidgets.QApplication.clipboard().setText(pub_pem.decode("utf-8"))
                QtWidgets.QMessageBox.information(self, t("qt_info"), t("qt_keys_generated"))
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, t("qt_error"), t("qt_keys_generate_failed", err=exc))

        def _on_copy_public_key(self) -> None:
            try:
                if not DEFAULT_PUBLIC_KEY_PATH.is_file():
                    raise FileNotFoundError(str(DEFAULT_PUBLIC_KEY_PATH))
                pub = DEFAULT_PUBLIC_KEY_PATH.read_text(encoding="utf-8")
                QtWidgets.QApplication.clipboard().setText(pub)
                QtWidgets.QMessageBox.information(self, t("qt_info"), t("qt_public_key_copied"))
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, t("qt_error"), t("qt_copy_public_key_failed", err=exc))

        def _on_save(self) -> None:
            # save local port
            try:
                p = int(self.eLocalPort.text().strip())
            except ValueError:
                QtWidgets.QMessageBox.critical(self, t("qt_error"), t("port_int_required"))
                return
            if not (1 <= p <= 65535):
                QtWidgets.QMessageBox.critical(self, t("qt_error"), t("port_range"))
                return
            write_default_comm_port(p)

            # save language
            lang = self.langCombo.currentData()
            if isinstance(lang, str) and lang:
                try:
                    set_lang(lang)
                except Exception:
                    pass

            self._mw._on_settings_saved()
            self.accept()

    class MainWindow(QtWidgets.QMainWindow):
        messageReceived = QtCore.Signal(tuple, str)  # peer(addr), text
        statusChanged = QtCore.Signal(str)
        peerClosed = QtCore.Signal(tuple)  # peer(addr)
        connectSucceeded = QtCore.Signal(tuple)  # peer addr
        connectFailed = QtCore.Signal(str, str)  # title, message

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(t("qt_title"))
            self.resize(980, 620)

            self._aio = AsyncioThread()
            self._aio.start()
            self._mgr: SessionManager | None = None
            self._peer_tabs: dict[tuple[str, int], QtWidgets.QPlainTextEdit] = {}

            self._build_ui()
            self._wire_signals()
            self._retranslate_ui()

        def _build_ui(self) -> None:
            central = QtWidgets.QWidget()
            self.setCentralWidget(central)

            layout = QtWidgets.QHBoxLayout(central)

            # Left: contacts + connect pane
            left = QtWidgets.QWidget()
            left_layout = QtWidgets.QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)

            self.lblContacts = QtWidgets.QLabel()
            left_layout.addWidget(self.lblContacts)

            self.contactsList = QtWidgets.QListWidget()
            self.contactsList.setMinimumWidth(340)
            left_layout.addWidget(self.contactsList, 1)

            contact_btns = QtWidgets.QHBoxLayout()
            self.btnAddContact = QtWidgets.QPushButton()
            self.btnEditContact = QtWidgets.QPushButton()
            self.btnConnectContact = QtWidgets.QPushButton()
            contact_btns.addWidget(self.btnAddContact)
            contact_btns.addWidget(self.btnEditContact)
            contact_btns.addWidget(self.btnConnectContact)
            left_layout.addLayout(contact_btns)

            left_layout.addSpacing(10)
            form = QtWidgets.QFormLayout()
            self.peerHost = QtWidgets.QLineEdit()
            self.peerPort = QtWidgets.QLineEdit(str(read_default_comm_port()))
            self.lblPeerIPv4 = QtWidgets.QLabel()
            self.lblPeerPort = QtWidgets.QLabel()
            form.addRow(self.lblPeerIPv4, self.peerHost)
            form.addRow(self.lblPeerPort, self.peerPort)
            left_layout.addLayout(form)

            self.lblPeerPem = QtWidgets.QLabel()
            left_layout.addWidget(self.lblPeerPem)
            self.peerPem = QtWidgets.QPlainTextEdit()
            self.peerPem.setPlaceholderText("-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----")
            self.peerPem.setMinimumWidth(340)
            left_layout.addWidget(self.peerPem, 1)

            btn_row = QtWidgets.QHBoxLayout()
            self.btnConnect = QtWidgets.QPushButton()
            btn_row.addWidget(self.btnConnect)
            left_layout.addLayout(btn_row)

            self.statusLabel = QtWidgets.QLabel()
            self.statusLabel.setWordWrap(True)
            left_layout.addWidget(self.statusLabel)

            # Bottom-left: settings (gear icon)
            left_layout.addStretch(1)
            settings_row = QtWidgets.QHBoxLayout()
            self.btnSettings = QtWidgets.QToolButton()
            self.btnSettings.setAutoRaise(True)
            self.btnSettings.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            self.btnSettings.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btnSettings.setIconSize(QtCore.QSize(18, 18))
            settings_row.addWidget(self.btnSettings, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
            settings_row.addStretch(1)
            left_layout.addLayout(settings_row)

            # Right: chat pane (tabs per peer)
            right = QtWidgets.QWidget()
            right_layout = QtWidgets.QVBoxLayout(right)
            right_layout.setContentsMargins(0, 0, 0, 0)

            self.chatTabs = QtWidgets.QTabWidget()
            right_layout.addWidget(self.chatTabs, 1)

            send_row = QtWidgets.QHBoxLayout()
            self.msgEdit = QtWidgets.QLineEdit()
            self.msgEdit.setPlaceholderText(t("qt_type_message"))
            self.btnSend = QtWidgets.QPushButton()
            self.btnDisconnect = QtWidgets.QPushButton()
            send_row.addWidget(self.msgEdit, 1)
            send_row.addWidget(self.btnSend)
            send_row.addWidget(self.btnDisconnect)
            right_layout.addLayout(send_row)

            layout.addWidget(left, 0)
            layout.addWidget(right, 1)

        def _wire_signals(self) -> None:
            self.btnConnect.clicked.connect(self.onConnect)
            self.btnSend.clicked.connect(self.onSend)
            self.btnDisconnect.clicked.connect(self.onDisconnect)
            self.btnSettings.clicked.connect(self.onOpenSettings)
            self.msgEdit.returnPressed.connect(self.onSend)
            self.btnAddContact.clicked.connect(self.onAddContact)
            self.btnEditContact.clicked.connect(self.onEditContactLabel)
            self.btnConnectContact.clicked.connect(self.onConnectSavedContact)
            self.contactsList.itemSelectionChanged.connect(self._sync_manual_fields_from_selected_contact)

            self.messageReceived.connect(self._on_message)
            self.peerClosed.connect(self._on_peer_closed)
            self.statusChanged.connect(self.statusLabel.setText)
            self.connectFailed.connect(lambda title, msg: QtWidgets.QMessageBox.critical(self, title, msg))
            self.connectSucceeded.connect(self._on_connect_succeeded)
            self._reload_contacts()

        def _apply_settings_icon(self) -> None:
            # Prefer bundled SVG for consistent look across platforms.
            svg_path = _resource_path("assets/gear.svg")
            icon = QtGui.QIcon(svg_path) if Path(svg_path).is_file() else QtGui.QIcon()
            if icon.isNull():
                # Prefer platform/theme gear icon; fall back to a standard icon.
                icon = QtGui.QIcon.fromTheme("preferences-system")
            if icon.isNull():
                icon = QtGui.QIcon.fromTheme("settings")
            if icon.isNull():
                icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogDetailedView)
            self.btnSettings.setIcon(icon)

        def _retranslate_ui(self) -> None:
            self.setWindowTitle(t("qt_title"))
            self.lblContacts.setText(t("qt_contacts"))
            self.btnAddContact.setText(t("qt_add"))
            self.btnEditContact.setText(t("qt_edit_label"))
            self.btnConnectContact.setText(t("qt_connect"))
            self.lblPeerIPv4.setText(t("qt_peer_ipv4"))
            self.lblPeerPort.setText(t("qt_peer_port"))
            self.lblPeerPem.setText(t("qt_peer_pubkey"))
            self.btnConnect.setText(t("qt_connect_manual"))
            self.btnSend.setText(t("qt_send"))
            self.btnDisconnect.setText(t("qt_disconnect"))
            self.btnSettings.setToolTip(t("qt_settings"))
            self.btnSettings.setAccessibleName(t("qt_settings"))
            self._apply_settings_icon()
            if not self.statusLabel.text():
                self.statusLabel.setText(t("qt_ready"))
            self.msgEdit.setPlaceholderText(t("qt_type_message"))

        def _on_settings_saved(self) -> None:
            # language and local port may have changed
            self._retranslate_ui()
            self.statusLabel.setText(t("qt_settings_saved", port=read_default_comm_port(), lang=get_lang()))

        def onOpenSettings(self) -> None:
            dlg = SettingsDialog(self)
            dlg.exec()

        def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
            try:
                if self._mgr is not None:
                    mgr = self._mgr
                    self._mgr = None

                    async def _do_close():
                        for s in mgr.list_sessions():
                            with contextlib.suppress(Exception):
                                await mgr.close_peer(s.peer)
                        await mgr.close()

                    self._aio.submit(_do_close())
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

        def _on_peer_closed(self, peer: tuple) -> None:
            p = (str(peer[0]), int(peer[1]))
            w = self._peer_tabs.pop(p, None)
            if w is not None:
                idx = self.chatTabs.indexOf(w)
                if idx >= 0:
                    self.chatTabs.removeTab(idx)
            self.statusLabel.setText(f"Peer closed: {p}")

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
                item = QtWidgets.QListWidgetItem(f"{c.label} — {c.ipv4}:{c.port}")
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
            e_label = QtWidgets.QLineEdit()
            e_ip = QtWidgets.QLineEdit()
            e_port = QtWidgets.QLineEdit(str(read_default_comm_port()))
            e_pem = QtWidgets.QPlainTextEdit()
            e_pem.setPlaceholderText("-----BEGIN PUBLIC KEY-----\\n...\\n-----END PUBLIC KEY-----")
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
                add_contact(
                    label=validate_label(e_label.text()),
                    ipv4=validate_ipv4(e_ip.text()),
                    port=validate_port(int(e_port.text())),
                    public_key_pem=normalize_public_key_pem(e_pem.toPlainText()),
                )
                self._reload_contacts()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Invalid", str(exc))

        def onEditContactLabel(self) -> None:
            items = self.contactsList.selectedItems()
            if not items:
                QtWidgets.QMessageBox.information(self, "No contact", "Select a contact first.")
                return
            cid = items[0].data(QtCore.Qt.ItemDataRole.UserRole)
            c = next((x for x in load_contacts() if x.id == cid), None)
            if c is None:
                return
            text, ok = QtWidgets.QInputDialog.getText(self, "Edit label", "Label", text=c.label)
            if not ok:
                return
            try:
                update_contact_label(str(cid), validate_label(text))
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
                local_port = read_default_comm_port()
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
                            on_peer_closed=lambda peer: self.peerClosed.emit(peer),
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
            # Graceful close: ask peers to close, then stop manager.
            mgr = self._mgr
            self._mgr = None

            async def _do_close():
                for s in mgr.list_sessions():
                    with contextlib.suppress(Exception):
                        await mgr.close_peer(s.peer)
                await mgr.close()

            self._peer_tabs.clear()
            self.chatTabs.clear()
            self._aio.submit(_do_close())
            self.statusLabel.setText("Disconnected.")

        # Window cleanup is handled in closeEvent.

    app = QtWidgets.QApplication([])
    # App/window icon (used by run_UI.sh and packaged binary)
    icon_path = _resource_path("assets/app.png")
    if Path(icon_path).is_file():
        app.setWindowIcon(QtGui.QIcon(icon_path))
    win = MainWindow()
    win.show()
    app.exec()

