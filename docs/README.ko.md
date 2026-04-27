# YXL-LACE

**언어 / Languages:**
 [English](../README.md) · [中文](README.zh.md) · [日本語](README.ja.md) · **한국어**（이 문서） · [Español](README.es.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/) ![CLI](https://img.shields.io/badge/CLI-Terminal-4EAA25?logo=gnu-bash&logoColor=white) ![P2P](https://img.shields.io/badge/P2P-Serverless-111827) ![UDP](https://img.shields.io/badge/UDP-Handshake-0EA5E9) ![TCP](https://img.shields.io/badge/TCP-Chat-6366F1) ![RSA](https://img.shields.io/badge/RSA-OAEP-8B5CF6) ![AES](https://img.shields.io/badge/AES-256--GCM-F59E0B) [![cryptography](https://img.shields.io/badge/cryptography-lib-2CA5E0)](https://pypi.org/project/cryptography/)


---

중앙 서버 없는 **P2P 터미널 채팅**:**UDP**에서 **RSA-OAEP** 상호 챌린지–응답, **TCP**에서 **AES-256-GCM** 암호화 메시지. 로컬 기본 포트 **9001**(메뉴 **(3)**에서 변경, `~/.yxl_lace/default_comm_port`). **(2)**에서는 상대 **IPv4**와 **포트**만 입력합니다.

## 요구 사항

Python **3.10+** 및 [`cryptography`](https://pypi.org/project/cryptography/):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

GUI 의존성(선택):

```bash
pip install -r requirements-gui.txt
```

## 실행

저장소 루트에서:

```bash
./run.sh
```

또는 venv 활성화 및 `PYTHONPATH=src`일 때:

```bash
python -m yxl_lace
```

GUI (Qt / PySide6):

```bash
PYTHONPATH=src python -m yxl_lace.ui_qt
```

## 구조

- `docs/rsa_tcp_refactor_design.md` — 프로토콜 및 설계.
- `src/yxl_lace/crypto/` — RSA, OAEP, HKDF, AES-GCM.
- `src/yxl_lace/udp_auth.py` — UDP RSA 핸드셰이크.
- `src/yxl_lace/tcp_session.py` — TCP 채팅 프레이밍.
- `src/yxl_lace/print.py` — CLI 배너.
- `src/yxl_lace/cli.py` — 메인 CLI; `__main__.py`로 `python -m yxl_lace`.

## 빠른 시작

두 기기(또는 두 터미널)에서 클론 후 먼저 메뉴 **(1)**로 키 생성(기본 `~/.yxl_lace/`).

**(2)** 상대 **IPv4**, **포트**, **PEM 공개 키**(PEM 끝에 `.`만 있는 줄). 동시 시작 가능. 로컬은 항상 **기본 로컬 포트**로 UDP/TCP를 대기하고, **DER 순서로 더 작은 RSA 공개 키** 쪽이 UDP를 먼저 보내 **TCP 클라이언트**가 됩니다.

**(3)** 기본 로컬 포트 변경. **(4)** 연락처 저장(플레이스홀더).

흐름: RSA 상호 인증(UDP) → 채팅(AES-GCM over UDP). `/quit`로 종료.
