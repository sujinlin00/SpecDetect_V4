# AGENT Phase 2: 日志开关实现

**父任务**: `TASK_20260620_RMCP_proxy_integration.md`  
**估时**: 0.5 天  
**依赖**: Phase 1（proxy/ 包结构完成）  
**输出**: logger.py + connection.py + __main__.py 改造

---

## 目标

实现三层开关控制：
- **基础层（始终开启）**: TCP 透传 + 控制台极简输出
- **解析层（默认关闭）**: `rmcp_proxy.parse.enabled` 控制 RMCP 帧头解析 + funcid 提取
- **日志层（默认关闭）**: 5 个独立开关控制文件输出

全部开关关闭时：**零额外磁盘 I/O**，仅控制台输出连接/断开事件。

---

## 步骤 1：CaptureLogger 构造函数接收开关

**文件**: `proxy/logger.py`

当前 Phase 1 产物中 `CaptureLogger.__init__` 已接收 5 个 bool 参数。验证：

1. 开关关闭时 **不调用** `os.makedirs(log_dir)` 和 `open()`
2. 开关开启时正常创建文件
3. `log_frame()` 中每个文件写入前检查对应开关：
   ```python
   def log_frame(self, ...):
       with self.lock:
           self.frames.append(frame_info)
       if self.raw_enabled:
           self._write_raw(data)
       if self.json_enabled:
           self._append_json_line(frame_info)
       if self.text_enabled:
           self._append_log_line(frame_info)
   ```

---

## 步骤 2：解析层开关透传

**文件**: `proxy/connection.py`, `proxy/__main__.py`

```python
# connection.py: ProxyConnection.__init__ 接收 parse_enabled
def __init__(self, ..., parse_enabled: bool = False):
    self.parse_enabled = parse_enabled

# 转发线程中条件判断
def _forward_client_to_device(self):
    # ...
    data = self.client_socket.recv(8192)
    self.device_socket.sendall(data)  # 始终执行（基础层）
    if self.parse_enabled:
        self._parse_and_store_funcid(data)  # 解析层：提取 funcid
        self.logger.log_frame('C->S', data, ...)

def _forward_device_to_client(self):
    # ...
    data = self.device_socket.recv(8192)
    self.client_socket.sendall(data)  # 始终执行（基础层）
    if self.parse_enabled:
        self.logger.log_frame('S->C', data, ...,
                              related_funcid=self.last_funcid, ...)
```

**`__main__.py` 传递开关**:
```python
def start_proxy(config_path):
    cfg = load_proxy_config(config_path)
    parse_enabled = cfg.get('parse', {}).get('enabled', False)
    # 传递给 CaptureLogger 和 ProxyConnection
```

---

## 步骤 3：极简控制台输出

**文件**: `proxy/connection.py`

基础层（所有开关关闭时）仅输出：
```
[PROXY] New connection from 127.0.0.1:xxxxx (port 9999)
[PROXY] Connected to device 100.72.95.36:1449
[PROXY] Connection closed (duration=12.3s, sent=1024B, recv=2048B)
```

解析层开启时额外输出帧详情（保持原 `_print_to_console` 逻辑）。

**实现**: `_print_to_console()` 方法检查 `self.parse_enabled`，关闭时跳过帧解析输出。

---

## 步骤 4：按接口分离日志开关

**文件**: `proxy/logger.py`

`log_rmcp_callback_data()` 开头检查：
```python
def log_rmcp_callback_data(self, direction, data, addr):
    if not self.per_interface_enabled:
        return  # 开关关闭，跳过
    # ... 原有逻辑
```

---

## 步骤 5：单元测试

**文件**: `tests/test_proxy_logger.py`

| 测试 | 验证点 |
|------|--------|
| `test_all_disabled_no_files` | 全部开关关闭 → `log_dir` 无文件创建 |
| `test_text_enabled` | text_enabled=True → 仅 .log 文件存在 |
| `test_raw_enabled` | raw_enabled=True → 仅 .raw 文件存在 |
| `test_json_enabled` | json_enabled=True → 仅 .json 文件存在（追加格式） |
| `test_csv_enabled` | csv_enabled=True → 仅 connections.csv 存在 |
| `test_independent_switches` | 两个开关同时开启 → 两个文件，互不影响 |
| `test_log_frame_no_crash_when_disabled` | 关闭开关后 log_frame() 不抛异常 |
| `test_console_output_basic` | 基础层输出仅含连接事件（无帧详情） |

---

## 验收标准

- [ ] 全部开关关闭 → `logs/proxy/` 目录不创建，磁盘无写入
- [ ] 各开关独立控制，互不影响
- [ ] `parse.enabled=false` → 无 funcid 解析，控制台无 `Parsed funcid=` 输出
- [ ] 控制台在所有开关关闭时仅输出连接/断开事件
- [ ] 8 个日志开关测试 PASS
