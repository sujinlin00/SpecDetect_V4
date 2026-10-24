# TASK_20260620_02: RMCP Proxy 连接生命周期与停止信号传递

**日期**: 2026-06-20
**状态**: 📋 → ✅ **已迁移**（P0/P1/P2 → TASK_20260621_01 Phase C1-C3，P3 → C5 可选）
**估时**: 2 天（4 个修复项）
**来源**: Phase 7 实机运行反馈
**迁移目标**: `TASK_20260621_01_busy_state_and_connection_lifecycle.md`

---

## 0. 问题摘要

| # | 问题 | 严重度 | 根因 |
|---|------|:---:|------|
| 1 | SOAP B_StopMeas 后 proxy 与 device 连接未断开 | **CRITICAL** | ① `close()` 存在 socket 泄漏 bug ② Atom 未发送 RMCP 停止帧 |
| 2 | 停止操作可能影响 proxy 的其他外部连接 | HIGH | proxy 透明代理，无法将控制指令精准关联到特定连接 |

---

## 1. 根因分析

### 1.1 问题 1 根因 A：`close()` early-return 导致 socket 泄漏

**文件**: `proxy/connection.py:260-264`

```python
def close(self):
    with self.close_lock:
        if not self.running:    # ← BUG: running=False 时跳过清理
            return
        self.running = False
        # socket 清理...
```

**泄漏路径**:

```
T1: _forward_client_to_device 的 finally → self.running = False (第155行)
T2: _forward_device_to_client 的 while self.running: → 退出
T3: run() 的 finally → self.close() → if not self.running: return
    → client_socket 和 device_socket 均未关闭！永久泄漏。
```

### 1.2 问题 1 根因 B：Atom 未发送 RMCP 停止帧

B_StopMeas → `session.close_all()` → `RMCPClient.disconnect()` → TCP RST

整个流程中**没有构造和发送 RMCP 级别的停止帧给设备**。设备收到的是 TCP 断连信号，而非 RMCP 停止指令。设备是否停止测量完全取决于固件实现的解释。

### 1.3 问题 2：连接身份盲区

Proxy 作为透明代理，不解析 RMCP 业务语义。当前 `parse_enabled=True` 时记录的 `last_funcid` 仅用于日志，未参与连接生命周期管理。

```
Proxy 看到的:    Connection#1 (client_addr=10.0.0.1:54321) → Device:1449
                 Connection#2 (client_addr=10.0.0.1:54322) → Device:1449

Proxy 不知道:    Connection#1 属于 taskid="FSCAN-1718832000"
                 Connection#2 属于 taskid="PSCAN-1718832005"
```

TCP 层面隔离有效（每个连接独立 ProxyConnection 实例），但缺乏控制层面的精准关断能力。

---

## 2. 修复方案

### P0: 修复 `close()` socket 泄漏（估时 0.5h）

**文件**: `proxy/connection.py`

引入 `_closed` 标志，与 `_running` 分离：

```python
# __init__ 新增:
self._closed = False

def close(self):
    with self.close_lock:
        if self._closed:
            return
        self._closed = True
        self.running = False
        # 清理 client_socket 和 device_socket ...
```

**影响**: 消除 socket 泄漏，不影响现有转发逻辑。

### P1: Atom 端发送 RMCP 停止帧（估时 1h）

**文件**: `src/atom/service.py`、`src/atom/rmcp/frame.py`

在 `_handle_stopmeas()` 中，关闭 session 之前先向设备发送 RMCP 停止帧：

```python
def _handle_stopmeas(self, request):
    session = self.session_manager.get_session_by_taskid(taskid)
    if session:
        self._send_rmcp_stop_frame(session)  # ← 新增
        self.session_manager.close_session(session)
```

`_send_rmcp_stop_frame()` 失败时回退到 TCP 断连（现有行为）。

**风险**: `funcid=0` 是假设值，需确认设备协议。失败时有 try/except 保护。

### P2: 连接日志增强（估时 0.5h）

**文件**: `proxy/connection.py:248-258`

在 `_log_connection_close()` 中记录 `last_funcid`、`last_funcid_name`，使日志可追溯：

```
[PROXY] CLOSE funcid=B_FScan(12) client=127.0.0.1:54321 duration_ms=5230
```

**影响**: 纯日志增强，零风险。

### P3: Proxy 控制通道（估时 3h，可选）

**文件**: `proxy/__main__.py`、`proxy/connection.py`

增加本地控制端口（127.0.0.1:19998），Atom 可通过 JSON 指令关闭特定连接：

```json
{"action": "close_connection", "client_addr": ["127.0.0.1", 54321]}
```

**优先级**: 偏低，当前 TCP 隔离已满足需求，此功能为安全余量。

---

## 3. 实施计划

| 优先级 | 修复项 | 估时 | 依赖 |
|:---:|------|:---:|------|
| **P0** | `close()` `_closed` 标志 | 0.5h | 无 |
| **P1** | RMCP 停止帧发送 | 1h | 需确认设备停止帧协议 |
| **P2** | 连接日志增强 | 0.5h | 无 |
| P3 | Proxy 控制通道 | 3h | P0 完成后 |

---

## 4. 涉及文件

| 文件 | 改动 | 估行数 |
|------|------|:---:|
| `proxy/connection.py` | P0: `_closed` 标志 + P2: 日志增强 | ~15 |
| `src/atom/rmcp/frame.py` | P1: 新增 `build_rmcp_stop_frame()` | ~30 |
| `src/atom/service.py` | P1: `_handle_stopmeas()` 调用停止帧 | ~15 |
| `tests/test_proxy_connection.py` | 新增: close() 幂等性测试 | ~30 |
| `tests/test_rmcp_stop_frame.py` | 新增: 停止帧构建测试 | ~20 |

---

## 5. 风险评估

| 修复项 | 风险 | 缓解 |
|------|:---:|------|
| P0 `_closed` | 低 | 幂等设计，重复 close 安全 |
| P1 停止帧 | 中 | funcid 格式需确认；失败时回退 TCP 断连 |
| P2 日志 | 低 | 纯增量 |
| P3 控制通道 | 高 | 新增协议，需充分测试 |

---

## 6. 验证标准

- [ ] P0: `close()` 在 running=False 时仍执行 socket 清理
- [ ] P0: 单元测试覆盖 close() 幂等性（连续 2 次调用不抛异常）
- [ ] P1: B_StopMeas 后设备收到 RMCP 停止帧（抓包验证）
- [ ] P1: 停止帧发送失败时 session 正常关闭（TCP 断连回退）
- [ ] P2: 日志包含 funcid 信息
- [ ] 回归: 全部 60+ 测试通过
