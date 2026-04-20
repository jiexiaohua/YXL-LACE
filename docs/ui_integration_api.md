# YXL-LACE UI 集成 API 文档（UDP 传输层）

## 1. 文档目标

本文档用于 UI/客户端开发接入当前 UDP 聊天传输层，目标是：
- 明确可直接调用的 API。
- 明确状态流转和事件回调。
- 提供可复用的接入流程与样例。

当前 API 封装文件：`src/yxl_lace/ui_api.py`

## 2. 设计定位

`ChatUiApi` 是对底层 `UdpPeer` 的 UI 友好封装，屏蔽了大部分传输细节。

职责：
- 生命周期管理：`start/stop`
- 聊天对象管理：`set_peer/clear_peer`
- 消息发送：`send/send_to`
- 事件回调：消息、状态、错误

不负责：
- UI 组件状态管理（由上层框架负责）
- 持久化聊天记录（由业务层负责）
- 生产级密码协议（当前仍是开发阶段密码实现）

## 3. 数据模型

### 3.1 `PeerEndpoint`

字段：
- `host: str`
- `port: int`

用途：表示当前聊天对象或消息来源。

### 3.2 `MessageEvent`

字段：
- `text: str`
- `from_peer: PeerEndpoint`

用途：收到消息时分发给 UI。

### 3.3 `StateEvent`

字段：
- `state: str`
- `detail: str`

用途：向 UI 输出可展示的状态变化。

当前已使用的状态值：
- `started`
- `stopped`
- `peer_changed`
- `connected`
- `peer_cleared`
- `message_sent`

## 4. `ChatUiApi` 构造参数

```python
ChatUiApi(
    peer_id: str,
    psk: str,
    bind_port: int,
    bind_host: str = "0.0.0.0",
    connect_timeout: float = 30.0,
    logger: Optional[logging.Logger] = None,
)
```

参数说明：
- `peer_id`：本地节点 ID。
- `psk`：预共享密钥（双方需一致）。
- `bind_port`：本地 UDP 监听端口。
- `bind_host`：默认 `0.0.0.0`，监听全部网卡。
- `connect_timeout`：握手超时时间（秒）。
- `logger`：可选自定义日志对象。

## 5. API 方法清单

### 5.1 回调注册

- `set_message_callback(callback)`
- `set_state_callback(callback)`
- `set_error_callback(callback)`

支持同步或异步函数（内部自动识别 awaitable）。

### 5.2 属性

- `current_peer -> Optional[PeerEndpoint]`

返回当前聊天对象；如果未设置则为 `None`。

### 5.3 生命周期

- `await start()`：启动 UDP 监听。
- `await stop()`：停止 UDP 监听。

### 5.4 对象管理

- `await set_peer(host, port, auto_connect=True)`
  - 设置当前聊天对象。
  - 默认立即尝试握手连接。
- `await clear_peer()`
  - 清空当前聊天对象。

### 5.5 发送消息

- `await send(text)`
  - 发送到 `current_peer`。
  - 若未设置对象会抛 `RuntimeError`。
- `await send_to(host, port, text)`
  - 一次性设置对象并发送。

## 6. 事件与错误约定

### 6.1 消息事件

触发时机：收到并成功解密 `DATA` 包后。

回调签名：
```python
def on_message(event: MessageEvent):
    ...
```
或
```python
async def on_message(event: MessageEvent):
    ...
```

### 6.2 状态事件

建议 UI 可直接映射到提示条/状态栏。

示例：
- `started`: listening on 0.0.0.0:9002
- `connected`: peer=10.148.70.138:9001

### 6.3 错误事件

任何 `set_peer/send/send_to` 的异常都会通过 `error callback` 通知。

常见异常：
- `TimeoutError`：握手超时（对端未回 `HELLO_ACK`）
- `RuntimeError("no active peer...")`：未设置对象直接发送
- `TimeoutError("message seq=... not acked...")`：消息未收到 ACK

## 7. UI 集成推荐流程

1. 用户输入本地参数：`peer_id/psk/port`。
2. 创建 `ChatUiApi` 实例并注册回调。
3. 调用 `start()`。
4. 用户设置聊天对象 -> 调用 `set_peer(host, port)`。
5. 用户发送消息 -> 调用 `send(text)`。
6. 用户切换对象 -> 再次 `set_peer(...)`。
7. 用户退出当前对象 -> `clear_peer()`。
8. 应用退出 -> `stop()`。

## 8. 最小调用示例

```python
import asyncio
from yxl_lace.ui_api import ChatUiApi

async def run():
    api = ChatUiApi(peer_id="alice", psk="demo-key", bind_port=9001)

    api.set_message_callback(lambda e: print(f"recv: {e.text}"))
    api.set_state_callback(lambda e: print(f"state: {e.state} {e.detail}"))
    api.set_error_callback(lambda e: print(f"error: {e}"))

    await api.start()
    await api.set_peer("10.148.70.138", 9002)
    await api.send("hello")

    await api.stop()

asyncio.run(run())
```

## 9. 与前端框架对接建议

- PySide/Tkinter：回调里投递到 UI 主线程队列再刷新组件。
- WebSocket 网关模式：用 `ChatUiApi` 作为后端会话层，对前端暴露 HTTP/WebSocket。
- Electron/Tauri：将 Python 进程作为后台服务，UI 通过 IPC 调用。

## 10. 当前边界与后续演进

当前边界：
- 主要适合同网段或可直连网络。
- 未包含 NAT 穿透。
- 默认密码套件为开发态占位实现。

后续建议：
- 增加 `disconnect_peer()`（清理会话缓存）。
- 增加消息 ID 和投递回执事件。
- 引入真实 E2EE 协议并扩展密钥轮转事件。
- 提供 REST/WebSocket 适配层，供前端零 Python 侵入接入。
