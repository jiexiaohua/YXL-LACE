# YXL-LACE

**言語 / Languages:**
 [English](../README.md) · [中文](README.zh.md) · **日本語**（このページ） · [한국어](README.ko.md) · [Español](README.es.md)


---

中央サーバーなしの **P2P 端末チャット**。**UDP** で **RSA-OAEP** 相互チャレンジ–レスポンス、**TCP** で **AES-256-GCM** 暗号化メッセージ。ローカル既定ポートは **9001**（メニュー **(3)** で変更、`~/.yxl_lace/default_comm_port` に保存）。**(2)** では相手の **IPv4** と **ポート** のみ入力します。

## 要件

Python **3.10+** と [`cryptography`](https://pypi.org/project/cryptography/)：

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 実行

リポジトリルートで：

```bash
./run.sh
```

または venv を有効化し `PYTHONPATH=src` のとき：

```bash
python -m yxl_lace
```

## 構成

- `docs/rsa_tcp_refactor_design.md` — プロトコルと設計。
- `src/yxl_lace/crypto/` — RSA、OAEP、HKDF、AES-GCM。
- `src/yxl_lace/udp_auth.py` — UDP 上の RSA ハンドシェイク。
- `src/yxl_lace/tcp_session.py` — TCP チャットのフレーミング。
- `src/yxl_lace/print.py` — CLI 表示。
- `src/yxl_lace/cli.py` — メイン CLI；`__main__.py` で `python -m yxl_lace`。

## クイックスタート

2 台（または 2 ターミナル）でクローンし、まずメニュー **(1)** で鍵を生成（既定 `~/.yxl_lace/`）。

**(2)** 相手の **IPv4**、**ポート**、**PEM 公開鍵**（PEM 終了後に `.` のみの行）。同時起動可。本機は常に**既定ローカルポート**で UDP/TCP を待ち受け、**DER 順で小さい RSA 公開鍵**の側が UDP を先に送り **TCP クライアント**になる。

**(3)** 既定ローカルポート変更。**(4)** 連絡先保存（プレースホルダー）。

流れ：UDP 認証 → **TCP**（AES-GCM）チャット。`/quit` で終了。
