from __future__ import annotations

import asyncio

from yxl_lace.crypto import generate_rsa_keypair, private_key_to_pem, public_key_to_pem
from yxl_lace.session_manager import SessionManager


async def main() -> None:
    # two local peers on different UDP ports
    a_port = 19001
    b_port = 19002
    host = "127.0.0.1"

    a_sk = generate_rsa_keypair(2048)
    b_sk = generate_rsa_keypair(2048)
    a_priv = private_key_to_pem(a_sk)
    b_priv = private_key_to_pem(b_sk)
    a_pub = public_key_to_pem(a_sk.public_key())
    b_pub = public_key_to_pem(b_sk.public_key())

    recv_a: list[str] = []
    recv_b: list[str] = []

    a = SessionManager(local_port=a_port, local_private_key_pem=a_priv, on_message=lambda _p, t: recv_a.append(t))
    b = SessionManager(local_port=b_port, local_private_key_pem=b_priv, on_message=lambda _p, t: recv_b.append(t))

    await a.start()
    await b.start()

    # establish sessions concurrently
    await asyncio.gather(
        a.connect_peer(peer_ip=host, peer_port=b_port, peer_public_key_pem=b_pub),
        b.connect_peer(peer_ip=host, peer_port=a_port, peer_public_key_pem=a_pub),
    )

    a.send((host, b_port), "hello-from-a")
    b.send((host, a_port), "hello-from-b")

    # wait for delivery
    for _ in range(50):
        if "hello-from-b" in recv_a and "hello-from-a" in recv_b:
            break
        await asyncio.sleep(0.05)

    assert "hello-from-b" in recv_a, recv_a
    assert "hello-from-a" in recv_b, recv_b

    await a.close()
    await b.close()


if __name__ == "__main__":
    asyncio.run(main())

