# TASK_20260621_01: Busy 状态多来源 & 连接生命周期集中化

**日期**: 2026-06-21
**状态**: 🔄 Phase C1+C3+B+C2+C4 完成（实施 + 审查），待测试验证
**估时**: 4 天（已完成 ~5h）
**来源**: 实机运行反馈 + 代码审查发现
**测试**: 148 通过（Phase B），C2/C4 测试 agent 运行中
**版本**: ATOM 1.7.7 / PROXY 1.2.12 / RMCP_PROXY 1.0.13

---

## 0. 背景

### 0.1 问题起源

两个独立但相关的架构缺陷被识别：

| # | 问题 | 根因 |
|---|------|------|
| 1 | rmcp_proxy 接收到外部请求时，Atom 的 idle/busy 状态不更新 | Proxy 是独立 OS 进程，与 Atom 无 IPC，状态完全隔离 |
| 2 | 连接生命周期管理散布在 6 个文件中，无集中所有权 | 原始设计逐步叠加功能，未做生命周期抽象 |

### 0.2 迁移说明

本任务整合以下内容：
- **TASK_20260620_02** 中未完成的 P0/P1/P2（P3 控制通道降级为可选）
- **本日新增**：BusySource 抽象（问题 1）+ 连接生命周期集中化（问题 2）

---

## 1. 现状分析

### 1.1 Idle/Busy 状态管理（问题 1）

**当前架构**：idle/busy 不是持久状态，而是 `DeviceStatusProvider.get_status()` 每次实时计算：

```
B_QueryFaciDevStat 请求
  → DeviceStatusProvider.get_status()        # device_status.py:88
    → session_manager.get_active_sessions()   # 找 state==ACTIVE 的 session
      → 有 → 返回 "busy" + taskid/userid/feature
      → 无 → 返回 "idle"
```

**核心缺陷**：

| 缺陷 | 说明 |
|------|------|
| 状态来源唯一 | 只有 `SessionManager` 的 ACTIVE session 能触发 busy |
| Proxy 完全隔离 | rmcp_proxy 是独立 OS 子进程，无 IPC 通知 Atom |
| 无抽象层 | busy 逻辑硬编码在 `DeviceStatusProvider` 中，无法扩展 |
| `judge_busy_by_max_task_num` 死代码 | config 中存在但运行时无引用 |

**关键文件**：

| 文件 | 角色 |
|------|------|
| `src/atom/device_status.py:88-116` | 计算 idle/busy（核心入口） |
| `src/atom/session_manager.py:228-245` | `get_active_sessions()` 决定 busy 来源 |
| `src/atom/session.py:18-23` | `SessionState` 枚举（PENDING/ACTIVE/CLOSING/CLOSED） |
| `proxy/__main__.py` | Proxy 入口，与 Atom 无 IPC |
| `src/atom/proxy_launcher.py` | 仅负责 spawn/stop proxy 进程 |

### 1.2 连接生命周期管理（问题 2）

**当前架构**：生命周期管理散布在 6 个文件中，无集中所有权：

```
                    ┌─────────────────────────────────┐
                    │      SessionManager             │
                    │  (最接近协调者，但只管 session   │
                    │   抽象，不管原始 TCP 连接)       │
                    └──────────┬──────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
  RMCPClient            StreamSrcServer        ProxyConnection
  (client.py)           (stream/server.py)     (proxy/connection.py)
  .connect()             ._handle_client()      .run()
  .disconnect()          ._check_dead_clients() .close()
```

**关闭链（Source 模式正常路径）**：

```
B_StopMeas SOAP
  → SessionManager.close_session(session)
    → _do_close(session)
      → session.close_all()
        → sets _stop_event         [信号 receive+push 线程退出]
        → streamsrc_client.close()
        → RMCPClient.disconnect()  [TCP FIN → Proxy]
        → outputchannel_forwarder.close()
      → session.state = CLOSED
```

**已知 P0 Bug（从 TASK_20260620_02 迁移）**：

`proxy/connection.py:260-264` — `running` 标志双重用途导致 socket 泄漏：

```python
def close(self):
    with self.close_lock:
        if not self.running:    # ← BUG: running=False 时跳过清理
            return
        self.running = False
        # socket 清理...
```

泄漏路径：forward 线程的 `finally: self.running = False` 先执行 → `run()` 的 `finally: self.close()` 被 `if not self.running: return` 拦截 → 两端 socket 永久泄漏。

---

## 2. 方案设计

### 2.1 BusySource 抽象（方案 B：共享文件 IPC）

**选型理由**（方案 B vs A/C）：

| 方案 | 描述 | 优点 | 缺点 | 选择 |
|------|------|------|------|:---:|
| A | 本地 TCP 控制通道 | 实时 | 增加端口管理复杂度 | ❌ |
| **B** | **共享文件 IPC** | 简单、可追溯、无端口依赖 | 轮询延迟（可接受） | ✅ |
| C | Proxy 改为线程 | 零 IPC | 失去进程隔离 | ❌ |

**架构设计**：

```
┌──────────────────────────────────────────────────────┐
│                  DeviceStatusProvider                 │
│                                                      │
│  sources: [                                          │
│    SessionBusySource(session_manager),   ← 现有逻辑  │
│    ProxyBusySource(state_file_path),     ← 新增      │
│  ]                                                   │
│                                                      │
│  get_status():                                       │
│    busy_sources = [s for s in sources if s.is_busy()]│
│    if busy_sources: return busy(...)                 │
│    return idle                                       │
└──────────────────────────────────────────────────────┘
         │                              ▲
         │              ┌───────────────┘
         │              │  read state file
         │     ┌────────┴────────┐
         │     │  ProxyBusySource │
         │     │  state_file:     │
         │     │  logs/proxy_state│
         │     │  .json           │
         │     └─────────────────┘
         │              ▲
         │              │ write on connection open/close
         │     ┌────────┴────────┐
         │     │  rmcp_proxy     │
         │     │  (subprocess)   │
         │     └─────────────────┘
```

**状态文件格式** (`logs/proxy_state.json`)：

```json
{
  "busy": false,
  "active_connections": 0,
  "connections": [],
  "last_update": "2026-06-21T10:30:00",
  "version": 1
}
```

**状态文件位置**：与 proxy 日志同目录 `logs/rmcp/proxy_state.json`，通过 `rmcp_proxy.log.dir` 配置推导。

**初始化细节**：

| 场景 | 处理方式 |
|------|---------|
| Proxy 启动 | 创建/覆盖 `proxy_state.json`，`busy: false, active_connections: 0` |
| 首个连接建立 | 更新 `busy: true, active_connections: 1` |
| 所有连接断开 | 更新 `busy: false, active_connections: 0` |
| Proxy 正常退出 | 删除 `proxy_state.json`（避免 Atom 读到僵尸状态） |
| Proxy 异常崩溃 | 文件残留 → `ProxyBusySource` 通过 `last_update` 时间戳检测僵死（超过 30s 视为无效） |
| Atom 启动时文件不存在 | `ProxyBusySource` 返回 `busy=False`（默认 idle） |
| 并发写入 | Proxy 端使用 `atomic write`（写临时文件 → os.replace），Atom 端只读 |

**连接断开是 idle 的必要不充分条件**：

```
is_idle() = all(sources are idle)
  = SessionBusySource.idle AND ProxyBusySource.idle

单个连接断开 ≠ idle（如果还有其他活跃来源）
全部断开 ≠ 立即 idle（如果 Atom 还有 ACTIVE session）
```

### 2.2 连接生命周期改进

**策略**：渐进式集中化，不推倒重来。

| 阶段 | 内容 | 估时 |
|:---:|------|:---:|
| **C1** | P0 修复：`close()` `_closed` 标志 | 0.5h |
| **C2** | P1 修复：Atom 发送 RMCP 停止帧 | 1h |
| **C3** | P2 增强：连接日志包含 funcid | 0.5h |
| **C4** | 引入 `ConnectionHandle` 基类，统一 socket 生命周期 | 1.5h |
| C5 | Proxy 控制通道（可选，低优先级） | 3h |

**C4 `ConnectionHandle` 设计**：

```python
class ConnectionHandle:
    """TCP 连接生命周期基类
    统一 socket 的 connect / disconnect / is_connected 模式
    """

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._closed = False

    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
    def send(self, data: bytes) -> int: ...
    def recv(self, bufsize: int) -> bytes: ...
```

**应用范围**：
- `RMCPClient` → 继承 `ConnectionHandle`，添加 RMCP 帧协议
- `ProxyConnection` → 组合两个 `ConnectionHandle`（client_side + device_side）
- `StreamSrcServer` 的 client socket → 可选，低优先级

---

## 3. 实施阶段

### 实施顺序

```
Phase A: P0 close() 修复 ──→ Phase C1（同 P0）
         │
         ▼
Phase B: BusySource 抽象
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Phase C2   Phase C3
(P1 停止帧)  (P2 日志)
    │         │
    └────┬────┘
         ▼
Phase C4: ConnectionHandle 基类
         ▼
Phase C5: 控制通道（可选）
```

### Phase A/B: BusySource 抽象（估时 2h）

**目标**：引入多来源 busy 判定，Proxy 通过共享文件 IPC 通知 Atom。

**新增文件**：

| 文件 | 说明 | 估行数 |
|------|------|:---:|
| `src/atom/busy_source.py` | `BusySource` 协议 + `SessionBusySource` + `ProxyBusySource` | ~80 |
| `proxy/state_writer.py` | Proxy 端状态文件写入（原子写入 + 连接计数） | ~60 |

**修改文件**：

| 文件 | 改动 | 估行数 |
|------|------|:---:|
| `src/atom/device_status.py` | `DeviceStatusProvider.__init__` 接受 `busy_sources: list`，`get_status()` 遍历 sources | ~20 |
| `src/atom/service.py` | 构造 `SessionBusySource` + `ProxyBusySource`，注入 `DeviceStatusProvider` | ~15 |
| `proxy/connection.py` | 连接建立/关闭时回调 `StateWriter` | ~15 |
| `proxy/__main__.py` | 初始化 `StateWriter`，传入 `ProxyConnection` 构造 | ~10 |
| `src/atom/proxy_launcher.py` | Atom 退出时清理 `proxy_state.json` | ~10 |

**BusySource 接口**：

```python
from typing import Protocol

class BusySource(Protocol):
    """busy 判定来源协议"""

    def is_busy(self) -> bool:
        """返回 True 表示此来源判定为 busy"""
        ...

    @property
    def detail(self) -> Optional[dict]:
        """busy 详情（taskid/userid/feature 等），idle 时返回 None"""
        ...
```

**状态初始化矩阵**：

| 场景 | ProxyBusySource.is_busy() | 行为 |
|------|:---:|------|
| `proxy_state.json` 不存在 | `False` | Proxy 未运行或已正常退出 |
| 文件存在，`busy: false` | `False` | Proxy 运行中但无外部连接 |
| 文件存在，`busy: true` | `True` | Proxy 有活跃外部连接 |
| 文件存在，`last_update` 超过 30s | `False` + WARN 日志 | Proxy 可能崩溃，忽略僵死状态 |
| 文件 JSON 损坏 | `False` + ERROR 日志 | 容错降级 |

### Phase C1: P0 `close()` 修复（估时 0.5h）

**文件**: `proxy/connection.py`

**修复**：引入 `_closed` 标志，与 `_running` 分离：

```python
# __init__ 新增:
self._closed = False

def close(self) -> None:
    with self.close_lock:
        if self._closed:
            return
        self._closed = True
        self.running = False
        # ... 原有清理逻辑不变 ...
```

**测试**: 新增 3 个单元测试

| 测试 | 验证点 |
|------|--------|
| `test_close_idempotent` | 连续 2 次 `close()` 不抛异常 |
| `test_close_after_forward_thread_crash` | forward 线程 `finally` 设 `running=False` 后，`close()` 仍执行清理 |
| `test_close_cleans_both_sockets` | `close()` 后 `client_socket` 和 `device_socket` 均为 None |

### Phase C2: P1 RMCP 停止帧（估时 1h）

**文件**: `src/atom/service.py`、`src/atom/rmcp/frame.py`

**在 `_handle_stopmeas()` 中**，关闭 session 之前先向设备发送 RMCP 停止帧：

```python
def _handle_stopmeas(self, request):
    session = self.session_manager.get_session_by_taskid(taskid)
    if session:
        self._send_rmcp_stop_frame(session)  # ← 新增
        self.session_manager.close_session(session)

def _send_rmcp_stop_frame(self, session):
    """发送 RMCP 停止帧，失败时回退到 TCP 断连"""
    try:
        funcid = session.last_funcid or 0
        stop_frame = build_rmcp_stop_frame(funcid)
        session.target_client.send_raw_frame(stop_frame)
    except Exception:
        # 回退：TCP 断连（现有行为）
        pass
```

**风险**：`funcid=0` 是占位值，需确认设备协议中停止帧的正确 funcid。失败时有 try/except 保护，不影响现有行为。

### Phase C3: P2 连接日志增强（估时 0.5h）

**文件**: `proxy/connection.py:248-258`

在 `_log_connection_close()` 中记录 `last_funcid` 信息：

```
# Before:
[PROXY] CLOSE client=127.0.0.1:54321 duration_ms=5230

# After:
[PROXY] CLOSE funcid=12(B_FScan) client=127.0.0.1:54321 duration_ms=5230 bytes_sent=10240 bytes_recv=204800
```

### Phase C4: ConnectionHandle 基类（估时 1.5h）

**新增文件**：

| 文件 | 说明 |
|------|------|
| `src/atom/connection_handle.py` | `ConnectionHandle` 基类 |

**修改文件**：

| 文件 | 改动 |
|------|------|
| `src/atom/rmcp/client.py` | `RMCPClient` 继承 `ConnectionHandle` |

**优先级**：C4 可在 C2/C3 之后独立执行，不阻塞其他阶段。

### Phase C5: Proxy 控制通道（估时 3h，可选）

从 TASK_20260620_02 迁移，优先级最低。当 Phase B 的共享文件 IPC 就位后，控制通道的必要性进一步降低。

---

## 4. 涉及文件总览

| 文件 | Phase | 改动类型 | 估行数 |
|------|:---:|------|:---:|
| `src/atom/busy_source.py` | B | **新增** | ~80 |
| `proxy/state_writer.py` | B | **新增** | ~60 |
| `src/atom/connection_handle.py` | C4 | **新增** | ~80 |
| `src/atom/device_status.py` | B | 修改 | ~20 |
| `src/atom/service.py` | B, C2 | 修改 | ~30 |
| `proxy/connection.py` | C1, C3, B | 修改 | ~30 |
| `proxy/__main__.py` | B | 修改 | ~10 |
| `src/atom/proxy_launcher.py` | B | 修改 | ~10 |
| `src/atom/rmcp/frame.py` | C2 | 修改 | ~30 |
| `src/atom/rmcp/client.py` | C4 | 修改 | ~20 |
| `src/atom/session_manager.py` | — | 不变 | 0 |
| `src/atom/session.py` | — | 不变 | 0 |
| `config/settings.json` | — | 不变 | 0 |

**测试文件**：

| 文件 | Phase | 说明 |
|------|:---:|------|
| `tests/test_busy_source.py` | B | BusySource 协议 + SessionBusySource + ProxyBusySource 单元测试 |
| `tests/test_proxy_state_writer.py` | B | StateWriter 原子写入 + 僵死检测 + JSON 容错 |
| `tests/test_connection_close.py` | C1 | close() 幂等性 + socket 清理验证 |
| `tests/test_rmcp_stop_frame.py` | C2 | 停止帧构建 + 发送失败回退 |
| `tests/test_connection_handle.py` | C4 | ConnectionHandle 基类测试 |

---

## 5. 风险评估

| 风险 | 阶段 | 严重度 | 缓解 |
|------|:---:|:---:|------|
| `proxy_state.json` 僵死（proxy 崩溃未清理） | B | 中 | `last_update` 30s 超时检测，超时视为 idle |
| 文件写入竞争（proxy 多连接并发写） | B | 低 | StateWriter 内部使用 `threading.Lock` + 原子写入 |
| RMCP 停止帧 funcid 不确定 | C2 | 中 | 失败回退 TCP 断连；funcid 可从 session 记录推导 |
| ConnectionHandle 重构影响现有 RMCPClient | C4 | 中 | 保持 RMCPClient 公开 API 不变，仅内部改用基类 |
| Proxy close() 修改引入回归 | C1 | 低 | `_closed` 只增不减，新旧逻辑无冲突 |

---

## 6. 验证标准

- [ ] Phase B: `B_QueryFaciDevStat` 在 proxy 有外部连接时返回 `busy`
- [ ] Phase B: 所有 proxy 连接断开 + 无 ACTIVE session → `idle`
- [ ] Phase B: proxy 崩溃后 30s 内 `proxy_state.json` 自动失效 → `idle`
- [ ] Phase C1: `close()` 在 `running=False` 时仍执行 socket 清理
- [ ] Phase C1: 单元测试覆盖 `close()` 幂等性
- [ ] Phase C2: B_StopMeas 后设备收到 RMCP 停止帧（抓包验证）
- [ ] Phase C2: 停止帧发送失败时 session 正常关闭
- [ ] Phase C3: 日志包含 `funcid` 信息
- [ ] 回归: 全部 60+ 测试通过（含新增单元测试）

---

## 7. 与已有 TASK 的关系

| 已有 TASK | 状态 | 本任务关联 |
|-----------|:---:|------|
| `TASK_20260619_error_response_format.md` | ✅ 完成 | 无直接关联 |
| `TASK_20260620_RMCP_proxy_integration.md` | ✅ 完成 | 本任务在其基础上增加 IPC |
| `TASK_20260620_02_proxy_disconnect_fix.md` | 📋 → **迁移** | P0/P1/P2 已迁移至本任务 Phase C1-C3，P3 降级为 C5 |

**TASK_20260620_02 归档说明**：其分析结论保留，实施项全部迁移至本文档。`TASK_20260620_02` 状态更新为 `已迁移`。
