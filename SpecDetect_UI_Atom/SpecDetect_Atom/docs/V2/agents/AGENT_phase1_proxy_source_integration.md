# AGENT Phase 1: Proxy 源码整合 + 配置适配

**父任务**: `TASK_20260620_RMCP_proxy_integration.md`  
**估时**: 1 天  
**依赖**: 无（第一批）  
**输出**: 6 个源文件 + 2 个测试文件

---

## 目标

将 `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_POC\rmcp_proxy\rmcp_proxy.py`（1249 行）拆分为 6 个独立模块，放入 `SpecDetect_Atom/proxy/` 目录，适配共享 `settings.json` 配置。

---

## 步骤 1：创建 `proxy/__init__.py`

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\proxy\__init__.py`

空文件（使 proxy 成为 Python 包）。

---

## 步骤 2：创建 `proxy/constants.py`

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\proxy\constants.py`

**来源**: `rmcp_proxy.py` L45-68

**内容**:
- `RMCP_FRAME_HEADER_SIZE = 18`
- `MSG_TYPE_REQUEST = 90`, `MSG_TYPE_RESPONSE = 6`, `MSG_TYPE_DATA_1 = 29`, `MSG_TYPE_DATA_2 = 95`
- `FUNCID_TO_NAME` 字典（6 个条目）
- `NBDTYPE_TO_NAME` 字典（5 个条目）

不依赖任何其他模块。

---

## 步骤 3：创建 `proxy/frame.py`

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\proxy\frame.py`

**来源**: `rmcp_proxy.py` L134-359（`RMCPFrame` 类）

**RMCPFrame 静态方法**:

| 方法 | 行号 | 功能 |
|------|------|------|
| `parse_header(data: bytes) -> dict | None` | 解析 18 字节 RMCP 帧头，含 nVersion=7 验证、dwLength 合理性、FILETIME 范围 |
| `get_msg_type_name(msg_type: int) -> str` | 消息类型名映射 |
| `format_timestamp(tmStamp: int) -> str` | FILETIME → 可读时间 |
| `parse_fscan_data(data: bytes) -> dict` | 完整 FSCAN 业务数据解析（LEADER/VER/STC/TS/PL/EL/DT/DL/频段/电平） |
| `parse_fscan_data_simple(data: bytes, startfreq=0, step=0) -> dict` | 简化 FSCAN 解析（实测格式：3B 业务头 + 8B counters + int16 频谱） |

**注意事项**:
- 纯函数，无副作用，无 I/O
- `parse_header` 的 FILETIME 上限 `140000000000000000` 约 2027 年过期，暂不改动
- `parse_fscan_data_simple` 中的 dBm 转换 `v / 10.0` 保持

---

## 步骤 4：创建 `proxy/config.py`

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\proxy\config.py`

**功能**: 从共享 `settings.json` 读取 `rmcp_proxy` 段，返回结构化配置。

**关键函数**:

```python
def load_proxy_config(config_path: str) -> dict:
    """从共享 settings.json 加载 rmcp_proxy 配置段
    
    Args:
        config_path: settings.json 绝对路径
    
    Returns:
        合并了默认值的配置字典
    """
    # 1. 读取 JSON
    # 2. 提取 'rmcp_proxy' 段
    # 3. 深度合并默认值
    # 4. 返回
```

**默认值**:

| 路径 | 默认值 |
|------|--------|
| `listen.host` | `"0.0.0.0"` |
| `listen.port_1` | `9999` |
| `listen.port_2` | `8888` |
| `target.host` | `"127.0.0.1"` |
| `target.port` | `19999` |
| `parse.enabled` | `False` |
| `log.dir` | `"logs/proxy"` |
| `log.text_enabled` | `False` |
| `log.raw_enabled` | `False` |
| `log.json_enabled` | `False` |
| `log.csv_enabled` | `False` |
| `log.per_interface_enabled` | `False` |

**不复用**: 旧的 `rmcp_proxy/config.py` 和 `rmcp_proxy/rmcp_settings.json`。旧 `DEFAULT_CONFIG` 字符串常量也删除。

---

## 步骤 5：创建 `proxy/logger.py`

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\proxy\logger.py`

**来源**: `rmcp_proxy.py` L362-906（`CaptureLogger` 类），精简至 ~320 行

**改造要点**:

1. **构造函数签名变更**:
   ```python
   def __init__(self, log_dir: str, port: int = 0,
                text_enabled: bool = False, raw_enabled: bool = False,
                json_enabled: bool = False, csv_enabled: bool = False,
                per_interface_enabled: bool = False):
   ```
   替代原来的 `ENABLE_JSON_OUTPUT` 等全局变量。

2. **延迟文件创建**: 仅在对应开关为 True 时 `open()` 文件。全部关闭时不创建任何文件（`os.makedirs` 也跳过）。

3. **JSON 写入改为追加模式**（解决性能问题）:
   ```python
   # 旧：每次重写整个文件
   # json.dump(self.frames, f, ...)  ← O(n) 每帧
   
   # 新：追加一行 JSON
   # json.dump(frame_info, f, ensure_ascii=False); f.write('\n')  ← O(1) 每帧
   ```

4. **bare except 修复**: 所有 `except: pass` → `except Exception: pass`

5. **保留**: `_print_to_console()` 控制台输出逻辑、`log_rmcp_callback_data()` 按接口分离、`_parse_rmcp_callback_frame()` payload 解析

6. **提取公共方法**: `_save_log_line()` (L638-669) 和 `log_rmcp_callback_data()` (L800-819) 中重复的 payload 解析逻辑提取为 `_format_payload_summary(payload: bytes) -> str`

---

## 步骤 6：创建 `proxy/connection.py`

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\proxy\connection.py`

**来源**: `rmcp_proxy.py` L909-1131（`ProxyConnection` 类）

**改造要点**:

1. **构造函数接受 target 参数**（替代全局变量）:
   ```python
   def __init__(self, client_socket, client_addr, logger, listen_port,
                target_host: str, target_port: int, parse_enabled: bool = False):
   ```

2. **解析层开关**: `parse_enabled=False` 时不调用 `_parse_and_store_funcid()` 和 `log_frame()`

3. **bare except 修复**: `except: pass` → `except Exception: pass`（6 处）

4. **线程安全增强**: `last_funcid` / `last_funcid_name` 的读写竞争 — 在 CPython GIL 下原子性足够，但添加注释标记

5. **`print()` 统一**: 改用 `print(..., file=sys.stderr, flush=True)` 或将控制台输出通过回调函数注入

---

## 步骤 7：创建 `proxy/__main__.py`

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\proxy\__main__.py`

**来源**: `rmcp_proxy.py` L1133-1248（`start_proxy()` + `main()`）

**内容**:
- `start_proxy(config_path: str)` — 启动多端口监听
- `main()` — CLI 入口，支持 `--config`、`--version`、`--help`

**关键**: 支持 `python -m proxy --config path/to/settings.json` 启动

---

## 步骤 8：单元测试

### `tests/test_proxy_config.py`

- 测试 `load_proxy_config()` 正确解析完整 settings.json
- 测试缺失字段 fallback 到默认值
- 测试 `rmcp_proxy` 段完全缺失时仍返回默认值
- 测试文件不存在时抛出 `FileNotFoundError`

### `tests/test_proxy_frame.py`

- 正常 RMCP 帧解析（18 字节头 + 有效数据）
- nVersion != 7 → 返回 None
- dwLength > 65535 → 返回 None
- FILETIME 越界 → 返回 None
- 数据长度不足 18 字节 → 返回 None
- `parse_fscan_data()` 正常/数据不足/GT=0
- `parse_fscan_data_simple()` 正常/数据不足

---

## 验收标准

- [ ] `proxy/` 目录包含 6 个 `.py` 文件
- [ ] `python -m proxy --config config/settings.json` 可独立启动 proxy
- [ ] `load_proxy_config()` 正确解析 `rmcp_proxy` 段
- [ ] `RMCPFrame.parse_header()` 与旧 `rmcp_proxy.py` 行为一致
- [ ] 8+ 个单元测试 PASS
- [ ] 无 `except: pass`（bare except）残留
- [ ] 旧 `rmcp_proxy.py` 的 6 个已知问题修复（项目总结.md）全部保留
