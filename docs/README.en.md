# YXL-LACE

**Languages / 语言:**
**English** (this page) · [中文](README.zh.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)


---

P2P terminal chat **without a central server**: **UDP** carries **RSA-OAEP** mutual challenge–response; **TCP** carries **AES-256-GCM** encrypted messages. The local default port is **9001** (change via menu **(3)**, stored in `~/.yxl_lace/default_comm_port`). For **(2)** you only enter the peer’s **IPv4** and **port**.

## Requirements

Python 3.10+ and [`cryptography`](https://pypi.org/project/cryptography/):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

From the repository root:

```bash
./run.sh
```

Or with an active venv and `PYTHONPATH=src`:

```bash
python -m yxl_lace
```

## Layout

- `docs/rsa_tcp_refactor_design.md` — protocol and module design.
- `src/yxl_lace/crypto/` — RSA keys, OAEP, HKDF, AES-GCM.
- `src/yxl_lace/udp_auth.py` — UDP RSA handshake.
- `src/yxl_lace/tcp_session.py` — TCP chat framing and loop.
- `src/yxl_lace/print.py` — CLI banners and menu text.
- `src/yxl_lace/cli.py` — main CLI logic; `src/yxl_lace/__main__.py` enables `python -m yxl_lace`.

## Quick start

On two machines (or two terminals), clone the repo and run menu **(1)** first to generate keys (default `~/.yxl_lace/`).

**(2)** Enter the peer’s **IPv4**, **port**, and **PEM public key** (finish the PEM block with a single line containing only `.`). You can start both sides at the same time. The host always uses the **default local port** for UDP/TCP listen (the side with the **smaller RSA public key (DER order)** sends UDP first and acts as the **TCP client**).

**(3)** Change the default local port. **(4)** Save contacts (placeholder).

Flow: UDP authentication → **TCP** chat (AES-GCM). Type `/quit` to leave the chat.
