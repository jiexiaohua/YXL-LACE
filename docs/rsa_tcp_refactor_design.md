# YXL-LACE 重构设计：RSA 双向认证 + TCP + AES-256-GCM

本文档描述**大范围重构**的目标架构与协议约定，用于替代当前「UDP + 预共享密钥 PSK + 自定义 CryptoSuite」的 MVP 路径。实现时可分阶段落地；与旧版 UDP 设计的关系见下文。

---

## 1. 与现有代码的关系

| 维度 | 旧版（UDP `UdpPeer` + PSK，已废弃） | 当前（本文件） |
|------|---------------------------------------------|------------------|
| 传输 | UDP，`UdpPeer`，ACK + 重传 | **UDP** 握手 + **TCP** 聊天（全双工） |
| 身份 / 密钥协商 | 双方共享同一 PSK | **RSA 密钥对**（本地私钥 + 交换公钥） |
| 握手 | HELLO / HELLO_ACK | **双向挑战–应答**（RSA-OAEP，走 UDP） |
| 聊天机密性 | 流式异或 + HMAC（开发用） | **AES-256-GCM**（AEAD，走 TCP） |

旧版 `UdpPeer` 等已移除；**当前入口**：`python -m yxl_lace`（`src/yxl_lace/cli.py`）。

---

## 2. 源码目录规划（`src/yxl_lace/`）

新建 **`crypto/`** 包，**专职密码学**，与网络状态机解耦：

```
src/yxl_lace/
  crypto/
    __init__.py      # 对外 re-export 常用 API（可选）
    rsa_keys.py      # RSA 密钥生成、PEM 读写、公钥导出（供终端打印 / 保存）
    rsa_oaep.py      # RSA-OAEP（SHA-256 MGF1）加解密，用于握手挑战报文
    aes_gcm.py       # AES-256-GCM：nonce 策略、AAD 约定、封包 / 解包
    kdf.py           # 会话密钥派生（建议 HKDF-SHA256）
  udp_auth.py        # UDP 握手
  tcp_session.py     # TCP 聊天帧
  cli.py             # 命令行主逻辑
  __main__.py        # python -m yxl_lace
  print.py           # CLI 文案
```

**依赖建议**：使用 PyPI `cryptography` 库实现 RSA-OAEP 与 AES-GCM（避免自研密码）。

---

## 3. 命令行入口（`src/yxl_lace/cli.py` + `print.py`）

启动：`./run.sh` 或 `PYTHONPATH=src python -m yxl_lace`。

1. 调用 **`logo_out()`**、**`index_out()`**。
2. 主循环展示 **`operate_out()`** 中的菜单：

| 选项 | 含义 |
|------|------|
| **(0)** | 退出 |
| **(1)** | 创建 RSA 密钥对并持久化；公钥输出到终端 |
| **(2)** | 连接用户：对方 IPv4、对方端口、对方公钥；UDP 认证后 TCP + AES-GCM 聊天 |
| **(3)** | 修改本机默认通信端口（默认 9001） |
| **(4)** | 保存用户（TODO） |

密钥默认存储路径建议在文档与代码中写死一处（例如 `~/.yxl_lace/rsa_private.pem`），私钥文件权限 **0600**，日志中**禁止**打印私钥或完整会话密钥。

---

## 4. RSA 参数与随机数尺寸

- **RSA 密钥长度**：至少 **2048** bit（推荐 3072 若你方有合规要求）。
- **挑战明文**：每轮使用密码学安全随机数 **32 字节**（`secrets.token_bytes(32)`），与 RSA-OAEP-2048 的常见用法一致，且符合「按密码学习惯」的强度直觉。

---

## 5. 双向认证协议（对「双方公钥」语义的落地说明）

需求原文包含「解密后再拿双方的公钥加密再发给双方」。若按字面做**两次 RSA 公钥嵌套加密**，单次可加密明文长度会急剧变小，且与常见库默认 OAEP 限制冲突，**不推荐作为 MVP**。

本设计采用标准的**双向挑战–应答**（mutual challenge–response），语义为：

- 每一方必须证明自己持有**与对方所宣称公钥匹配的私钥**；
- 任一侧验证失败则**整次连接失败**（双方均不得进入加密聊天）。

记：

- 本地为 **A**，对端为 **B**。
- **A** 持有 `(sk_A, pk_A)`，**B** 持有 `(sk_B, pk_B)`（均为当前连接中交换的公钥所对应密钥对）。

### Round 1 — 验证 B 持有 `sk_B`

1. **A** 生成 `R_A ← {0,1}^256`，计算 `C1 = RSA-OAEP-Encrypt(pk_B, R_A)`，经 TCP 发送给 **B**。
2. **B** 用 `sk_B` 解密得 `R_A'`，若解密失败则认证失败。
3. **B** 计算 `C2 = RSA-OAEP-Encrypt(pk_A, R_A')`，发回 **A**。
4. **A** 用 `sk_A` 解密 `C2` 得 `R_A''`，使用**常量时间比较**判断 `R_A'' == R_A`。相等则 **A 侧**认为对端 **B** 身份成立。

### Round 2 — 验证 A 持有 `sk_A`（对称）

1. **B** 生成 `R_B`，发送 `C3 = RSA-OAEP-Encrypt(pk_A, R_B)`。
2. **A** 解密得 `R_B'`，发送 `C4 = RSA-OAEP-Encrypt(pk_B, R_B')`。
3. **B** 解密得 `R_B''`，判断 `R_B'' == R_B`。

**仅当 Round 1 与 Round 2 均成功**，才进入下一节的会话密钥派生与 GCM 聊天。

> 若后续你方明确要求「嵌套双公钥加密」帧格式，可在本文件追加 **附录：Nested-RSA 帧** 单独定义长度与填充；与 MVP 分开发布。

---

## 6. 认证成功后的会话密钥（AES-256-GCM）

双方需导出**同一条 256-bit 对称密钥**，且不能依赖单方可篡改的排序。建议：

- 设 `R_A`、`R_B` 为两方各自生成并**已通过上节验证**的 32 字节随机数。
- 定义**无歧义拼接**：按字典序比较 `R_A` 与 `R_B`（作为字节串），令  
  `R_lo = min(R_A, R_B)`，`R_hi = max(R_A, R_B)`（按字节序）。
- **IKM** = `R_lo || R_hi`（64 字节）。
- **会话密钥**：`K = HKDF-SHA256(salt=固定应用盐或空, ikm=IKM, info="YXL-LACE-chat-v1", L=32)`。

AES-GCM：

- **算法**：AES-256-GCM；**nonce** 每条消息唯一（建议 12 字节随机，或 4 字节固定前缀 + 8 字节计数器，二选一写死在实现中）。
- **AAD**：建议绑定上下文，例如 ASCII 字面量 `"yxl-lace-tcp-v1"` 或包含双方公钥指纹，防止跨会话重放（最小实现可先用常量 AAD，后续加强）。
- **TCP 承载**：建议 **4 字节大端长度前缀** + **密文（含 GCM tag，按 `cryptography` 惯例拼接）**，避免粘包。

---

## 7. 角色与端口（当前实现）

- **对称启动**：双方同时输入对方 IPv4、**对方端口**、对方公钥；本机 **UDP/TCP 监听端口** 为菜单 **(3)** 中的默认值（默认 9001）。
- **Tie-break**：RSA 公钥 DER 较小者为 UDP 先手 + **TCP 客户端**（发往/连接 `peer_host:peer_port`）；较大者为后手 + **TCP 服务端**（绑定本机 `local_port`）。
- **UDP**：第 5 节四轮挑战走 UDP，帧格式含类型字节（见 `udp_auth.py`）。
- **TCP**：认证成功后仅用于 AES-GCM 聊天。

---

## 8. 实现阶段建议

1. **Phase 1**：`crypto/` + `(1)` 密钥与 PEM；OAEP/HKDF 验证。
2. **Phase 2**：`udp_auth` + `tcp_session` + `cli` + `(2)` 联调（已完成主线）。
3. **Phase 3**：`(4)` 保存用户（通讯录等）与文案细化。

---

## 9. 已知边界与后续工作

- 未包含 NAT 穿透、中继；TCP 直连要求网络可达。
- 未包含证书 / PKI；**公钥以首次用户粘贴为准**，存在中间人风险，除非另有带外校验（指纹比对）。
- `(4)` 保存用户为占位；菜单与 `operate_out` 保留该项。

---

## 10. 参考

- RFC 8017（RSA-OAEP）
- NIST SP 800-108 / HKDF（RFC 5869）
- AES-GCM（NIST SP 800-38D）
