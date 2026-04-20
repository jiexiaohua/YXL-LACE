from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yxl_lace.peer import UdpPeer  # noqa: E402


def parse_addr(text: str) -> Tuple[str, int]:
    host, port = text.split(":", 1)
    return host, int(port)


def prompt_non_empty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("输入不能为空。")


def prompt_port(prompt: str) -> int:
    while True:
        value = input(prompt).strip()
        try:
            port = int(value)
        except ValueError:
            print("端口必须是整数。")
            continue
        if 1 <= port <= 65535:
            return port
        print("端口范围必须在 [1, 65535]。")


def prompt_peer() -> Optional[Tuple[str, int]]:
    print("设置对方地址（留空表示暂不设置）。格式：ip:port")
    while True:
        text = input("对方> ").strip()
        if not text:
            return None
        try:
            return parse_addr(text)
        except Exception:
            print("格式错误。示例：10.148.70.138:9001")


async def main() -> None:
    parser = argparse.ArgumentParser(description="YXL-LACE UDP 聊天节点（交互模式）")
    parser.add_argument("--id", help="节点 ID，例如 alice")
    parser.add_argument("--psk", help="预共享密钥")
    parser.add_argument("--log-level", default="INFO", help="日志级别：DEBUG/INFO/WARNING")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    peer_id = args.id or prompt_non_empty("节点ID> ")
    psk = args.psk or prompt_non_empty("预共享密钥PSK> ")
    bind_host = "0.0.0.0"
    bind_port = prompt_port("本地监听端口（绑定 0.0.0.0）> ")

    peer = UdpPeer(peer_id=peer_id, psk=psk, bind_host=bind_host, bind_port=bind_port)

    async def on_message(text: str, from_addr: Tuple[str, int]) -> None:
        print(f"\\n[{from_addr[0]}:{from_addr[1]}] {text}")

    peer.set_message_handler(on_message)
    await peer.start()

    remote_addr = prompt_peer()
    if remote_addr:
        print(f"当前聊天对象：{remote_addr[0]}:{remote_addr[1]}")

    print("可用命令：/peer（设置/切换对象）、/leave（退出当前对象）、/quit（退出程序）")
    print("输入消息后回车发送。")
    try:
        while True:
            line = await asyncio.to_thread(input, "> ")
            line = line.strip()
            if not line:
                continue
            if line == "/quit":
                break
            if line == "/peer":
                remote_addr = await asyncio.to_thread(prompt_peer)
                if remote_addr:
                    print(f"当前聊天对象：{remote_addr[0]}:{remote_addr[1]}")
                else:
                    print("未设置聊天对象。")
                continue
            if line == "/leave":
                remote_addr = None
                print("已退出当前聊天对象。可使用 /peer 设置新对象。")
                continue
            if not remote_addr:
                print("尚未设置聊天对象。请先使用 /peer 设置对方地址。")
                continue
            try:
                await peer.connect(remote_addr, timeout=30.0)
                await peer.send_text(remote_addr, line)
            except Exception as exc:
                print(f"发送失败：{exc}")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        await peer.stop()


if __name__ == "__main__":
    asyncio.run(main())
