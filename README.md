# YXL-LACE

一个 P2P、无中心化服务器的端到端加密项目，目标是通过去中心化加密保障信息安全（当前处于开发阶段）。

## 当前里程碑：UDP 传输层

仓库已实现第一版 UDP 通信层，用于加密聊天联调，并重点保证可扩展性。

## 目录结构

- `docs/udp_transport_design.md`：UDP 传输层设计文档与演进路线。
- `docs/ui_integration_api.md`：UI 集成 API 详细文档。
- `src/yxl_lace/protocol.py`：协议包模型与可插拔编解码。
- `src/yxl_lace/crypto.py`：可插拔加密套件（当前为开发阶段默认实现）。
- `src/yxl_lace/reliability.py`：可插拔重传策略。
- `src/yxl_lace/session_store.py`：可插拔会话存储。
- `src/yxl_lace/peer.py`：UDP 节点核心（握手、ACK、重传、消息分发）。
- `src/yxl_lace/ui_api.py`：面向应用/UI 的统一调用封装层。
- `examples/chat_node.py`：交互式命令行聊天示例。
- `examples/ui_api_quickstart.py`：UI API 最小调用示例。

## 快速运行

打开两个终端：

终端 A：

```bash
python3 examples/chat_node.py
```

终端 B：

```bash
python3 examples/chat_node.py
```

然后按照交互提示输入本地监听端口和对方地址即可。

## UI API 快速示例

```bash
python3 examples/ui_api_quickstart.py
```

完整接口说明请查看：`docs/ui_integration_api.md`。

## 可扩展点

- 可替换 `PacketCodec`：支持 protobuf/msgpack 等二进制协议格式。
- 可替换 `CryptoSuite`：接入生产级握手与 AEAD 加密方案。
- 可替换 `RetryPolicy`：支持退避重传、窗口控制等策略。
- 可替换 `SessionStore`：支持持久化或分布式会话存储。

## 安全说明

当前默认密码实现用于开发联调，不可直接用于生产环境。
