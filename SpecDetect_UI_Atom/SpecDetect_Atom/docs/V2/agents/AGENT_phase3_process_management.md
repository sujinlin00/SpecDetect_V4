# AGENT Phase 3: Proxy 稳定性保障

**父任务**: `TASK_20260620_RMCP_proxy_integration.md`  
**估时**: 0.5 天  
**依赖**: Phase 1-2（proxy 包完成）  
**输出**: proxy 侧稳定性机制

---

## 目标

Proxy 是长存活透传服务，需确保：
1. 父进程（Atom）死亡时 proxy 自动退出（孤儿防护）
2. 连接断开时端口正确释放
3. 无内存/句柄泄漏

**不做**: Atom 启停 proxy — 两个独立进程，各自管理生命周期。

---

## 步骤 1：孤儿进程防护（已实现）

**文件**: `proxy/__main__.py:36-57`

`_parent_alive()` 使用 Windows `OpenProcess` + `WaitForSingleObject` 每秒检测父进程存活。父进程退出 → proxy 自动退出。

**验证**: 确认 `server.settimeout(1.0)` 已设置（`__main__.py` ），accept 可被打断。

---

## 步骤 2：连接断开 → 端口释放

**文件**: `proxy/connection.py`

每个客户端连接：
1. `ProxyConnection.run()` 创建 2 个转发线程
2. 任一线程检测断开 → `self.running = False` → `self.close()`
3. `close()` 执行 `shutdown(SHUT_RDWR)` + `close()` 释放 socket

**验证点**:
- `close()` 是否在所有退出路径被调用（正常断开 / 异常 / recv 空）
- `close_lock` 防止重复关闭
- socket 关闭后端口立即释放（SO_REUSEADDR 已在 server socket 设置）

---

## 步骤 3：连接稳定性

**文件**: `proxy/connection.py`

| 场景 | 处理 |
|------|------|
| 客户端断连 | `recv() == b''` → close |
| Device 断连 | `recv() == b''` → close |
| ConnectionResetError | 捕获 → close |
| BrokenPipeError | 捕获 → close |
| sendall 失败 | 捕获 → close |
| socket.timeout | continue（允许 Ctrl+C 打断） |

**不做**: 自动重连。断连后清理资源，由客户端重新发起连接。

---

## 步骤 4：资源泄漏检查

- 每次连接 new 2 个 thread → daemon=True → 主线程退出时自动清理
- socket 在 close() 中显式 shutdown + close
- CaptureLogger 文件在 close() 中关闭
- 无全局状态累积（frames 列表仅内存，进程退出自动释放）

---

## 验收标准

- [ ] `_parent_alive()` 父进程退出后 proxy 2 秒内退出
- [ ] 客户端断连后端口可立即被新连接复用
- [ ] 异常断连不导致 socket 泄漏（100 次连接→断开循环后句柄数稳定）
- [ ] `server.settimeout(1.0)` 确保 Ctrl+C 可中断
