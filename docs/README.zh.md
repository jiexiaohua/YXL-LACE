# YXL-LACE

**语言 / Languages:**
 [English](../README.md) · **中文**（本页） · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/) ![CLI](https://img.shields.io/badge/CLI-Terminal-4EAA25?logo=gnu-bash&logoColor=white) ![P2P](https://img.shields.io/badge/P2P-Serverless-111827) ![UDP](https://img.shields.io/badge/UDP-Handshake-0EA5E9) ![TCP](https://img.shields.io/badge/TCP-Chat-6366F1) ![RSA](https://img.shields.io/badge/RSA-OAEP-8B5CF6) ![AES](https://img.shields.io/badge/AES-256--GCM-F59E0B) [![cryptography](https://img.shields.io/badge/cryptography-lib-2CA5E0)](https://pypi.org/project/cryptography/)


---

P2P 命令行聊天（无中心服务器）：**UDP** 完成 **RSA-OAEP** 双向挑战–应答，**TCP** 承载 **AES-256-GCM** 加密聊天。本机默认通信端口 **9001**（菜单 **(3)** 可改，写入 `~/.yxl_lace/default_comm_port`）；连接时 **(2)** 只需再输入**对方 IPv4** 与**对方端口**。

## 依赖

需要 Python 3.10+ 与 [cryptography](https://pypi.org/project/cryptography/)：

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

GUI 依赖（可选）：

```bash
pip install -r requirements-gui.txt
```

## 运行

仓库根目录一键启动：

```bash
./run.sh
```

或已激活 venv 且 `PYTHONPATH=src` 时：

```bash
python -m yxl_lace
```

GUI（Qt / PySide6）：

```bash
PYTHONPATH=src python -m yxl_lace.ui_qt
```

## 目录结构

- `docs/rsa_tcp_refactor_design.md`：协议与模块设计说明。
- `src/yxl_lace/crypto/`：RSA 密钥、OAEP、HKDF、AES-GCM。
- `src/yxl_lace/udp_auth.py`：UDP 上的 RSA 双向握手。
- `src/yxl_lace/tcp_session.py`：TCP 加密聊天帧与交互循环。
- `src/yxl_lace/print.py`：CLI 菜单与欢迎语。
- `src/yxl_lace/cli.py`：交互式主逻辑；`src/yxl_lace/__main__.py` 支持 `python -m yxl_lace`。

## 快速运行

两台机器（或本机两终端）各克隆/拷贝仓库，并**先各自执行菜单 (1)** 生成密钥（默认写入 `~/.yxl_lace/`）。

`(2)`：输入**对方 IPv4**、**对方端口**、对方 **PEM 公钥**（以单独一行 `.` 结束）后可与对方**同时回车**。本机始终使用当前**默认端口**做 UDP/TCP 监听（先手向对方端口发 UDP，TCP 客户端连对方端口）。公钥较小者为 UDP 先手 / TCP 客户端。

`(3)`：修改本机默认端口。`(4)`：保存用户（占位）。

流程：RSA（UDP）双向认证 → UDP（AES-GCM）聊天会话。输入 `/quit` 退出聊天。

