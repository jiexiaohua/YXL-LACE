# YXL-LACE(Local Area Crypto Encryption)
**Languages / 语言:**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/) ![CLI](https://img.shields.io/badge/CLI-Terminal-4EAA25?logo=gnu-bash&logoColor=white) ![P2P](https://img.shields.io/badge/P2P-Serverless-111827) ![UDP](https://img.shields.io/badge/UDP-Handshake-0EA5E9) ![TCP](https://img.shields.io/badge/TCP-Chat-6366F1) ![RSA](https://img.shields.io/badge/RSA-OAEP-8B5CF6) ![AES](https://img.shields.io/badge/AES-256--GCM-F59E0B) [![cryptography](https://img.shields.io/badge/cryptography-lib-2CA5E0)](https://pypi.org/project/cryptography/)


**English** (this file) · [中文](docs/README.zh.md) · [日本語](docs/README.ja.md) · [한국어](docs/README.ko.md) · [Español](docs/README.es.md)



---

P2P terminal chat **without a central server**: **UDP** carries **RSA-OAEP** mutual challenge–response; **TCP** carries **AES-256-GCM** encrypted messages. The local default port is **9001** (change via menu **(3)**, stored in `~/.yxl_lace/default_comm_port`). For **(2)** you only enter the peer’s **IPv4** and **port**.

## Requirements

Python 3.10+ and [`cryptography`](https://pypi.org/project/cryptography/):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

GUI deps (optional):

```bash
pip install -r requirements-gui.txt
```

## Run

**Type 1:**

From the repository root:

```bash
./run.sh
```

Or with an active venv and `PYTHONPATH=src`:

```bash
python -m yxl_lace
```

**Type 2:**
```
cd dist
./YXL-LACE
```

**Type 3 (GUI, Qt / PySide6):**

```bash
PYTHONPATH=src python -m yxl_lace.ui_qt
```

Notes:
- Install GUI deps: `pip install PySide6`

## Layout

- `docs/rsa_tcp_refactor_design.md` — protocol and module design.
- `src/yxl_lace/crypto/` — RSA keys, OAEP, HKDF, AES-GCM.
- `src/yxl_lace/udp_auth.py` — UDP RSA handshake.
- `src/yxl_lace/tcp_session.py` — TCP chat framing and loop.
- `src/yxl_lace/print.py` — CLI banners and menu text.
- `src/yxl_lace/cli.py` — main CLI logic; `src/yxl_lace/__main__.py` enables `python -m yxl_lace`.
- `src/yxl_lace/ui_qt/` — Qt (PySide6) desktop GUI (minimal chat).
- `src/yxl_lace/ui/` — Tkinter desktop GUI (legacy).
- `src/yxl_lace/udp_chat_session.py` — GUI-friendly UDP chat session wrapper.

## Quick start

On two machines (or two terminals), clone the repo and run menu **(1)** first to generate keys (default `~/.yxl_lace/`).

**(2)** Enter the peer’s **IPv4**, **port**, and **PEM public key** (finish the PEM block with a single line containing only `.`). You can start both sides at the same time. The host always uses the **default local port** for UDP/TCP listen (the side with the **smaller RSA public key (DER order)** sends UDP first and acts as the **TCP client**).

**(3)** Change the default local port. **(4)** Save a contact. **(5)** Connect a saved contact. **(6)** Switch language.

Flow: RSA mutual authentication (UDP) → chat sessions (AES-GCM over UDP). Type `/quit` to leave the CLI chat.

## Packaging (PyInstaller)

CLI (onefile):

```bash
pyinstaller -F -n YXL-LACE src/yxl_lace/__main__.py
```

GUI (onefile):

```bash
pyinstaller -F -n YXL-LACE-GUI --icon assets/app.icns --add-data "assets/app.png:assets" run_ui.py
```
