# YXL-LACE

**Idiomas / Languages:**
 [English](../README.md) · [中文](README.zh.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · **Español** (esta página)


---

Chat de terminal **P2P sin servidor central**: **UDP** para el reto–respuesta mutuo **RSA-OAEP**; **TCP** para mensajes cifrados **AES-256-GCM**. El puerto local por defecto es **9001** (cámbialo en el menú **(3)**, guardado en `~/.yxl_lace/default_comm_port`). En **(2)** solo introduces la **IPv4** y el **puerto** del par.

## Requisitos

Python **3.10+** y [`cryptography`](https://pypi.org/project/cryptography/):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecución

Desde la raíz del repositorio:

```bash
./run.sh
```

O con venv activo y `PYTHONPATH=src`:

```bash
python -m yxl_lace
```

## Estructura

- `docs/rsa_tcp_refactor_design.md` — diseño del protocolo.
- `src/yxl_lace/crypto/` — RSA, OAEP, HKDF, AES-GCM.
- `src/yxl_lace/udp_auth.py` — handshake RSA por UDP.
- `src/yxl_lace/tcp_session.py` — enmarcado del chat TCP.
- `src/yxl_lace/print.py` — textos del menú CLI.
- `src/yxl_lace/cli.py` — lógica principal; `__main__.py` permite `python -m yxl_lace`.

## Inicio rápido

En dos máquinas (o dos terminales), clona el repo y ejecuta primero el menú **(1)** para generar claves (por defecto en `~/.yxl_lace/`).

**(2)** Introduce la **IPv4**, el **puerto** y la **clave pública PEM** del par (termina el bloque PEM con una línea que solo contenga `.`). Ambos lados pueden arrancar a la vez. El equipo siempre usa el **puerto local por defecto** para escuchar UDP/TCP; el lado con la **clave pública RSA menor (orden DER)** envía primero por UDP y actúa como **cliente TCP**.

**(3)** Cambia el puerto local por defecto. **(4)** Guardar contactos (marcador de posición).

Flujo: autenticación UDP → chat **TCP** (AES-GCM). Escribe `/quit` para salir.
