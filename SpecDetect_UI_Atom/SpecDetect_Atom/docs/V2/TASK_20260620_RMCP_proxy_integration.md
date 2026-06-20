# TASK_20260620: RMCP 透明代理集成到 Atom 部署包

**日期**: 2026-06-20  
**版本**: v1.6.0 → v1.7.5  
**状态**: 🔄 Phase 1-6 完成，Phase 7 待实施  
**估时**: 4.5 天（7 阶段）

---

## 0. 分析结论摘要

### 架构裁决

| 决策            | 选择                                  | 理由                                             |
| ------------- | ----------------------------------- | ---------------------------------------------- |
| 构建方案          | **双 exe，Atom 子进程启动 proxy**          | 进程隔离保留；`main.py` 做子进程编排；仍支持独立启动 proxy       |
| 配置方式          | 共享 `settings.json` + `--config` CLI | 单一事实来源；proxy 独立读取 `rmcp_proxy` 段               |
| Atom-Proxy 耦合 | **`main.py` 层进程编排，proxy 包零耦合**      | proxy 源码不动；仅在 Atom 入口层 spawn/kill 子进程          |
| 进程生命周期        | **Atom 启动时自动拉 proxy，退出时自动杀**        | `_parent_alive()` 兜底孤儿防护；仍支持手动独立启停              |
| 日志隔离          | `logs/` 同目录、不同文件名前缀                 | `capture_*.log` vs Atom 日志，不冲突                 |
| 旧 POC 代码      | 保留不删                                | `SpecDetect_POC/rmcp_proxy/` 作为参考归档            |

### 功能需求变更

| 功能                               | Phase 1-5 结论 | Phase 6 结论 | 原因                                    |
| ------------------------------- |:----------:|:---------:| ------------------------------------- |
| `rmcp_proxy.enabled` 主开关        | ❌ 不需要     | ✅ **需要**  | Phase 6：Atom 启动时读此开关决定是否 spawn proxy |
| `get_rmcp_target()` proxy 模式重定向 | ❌ 不需要     | ❌ 不需要     | 用户手动改 `rmcp.host:port` 指向 proxy       |
| `AtomService` 启停 proxy          | ❌ 不需要     | ❌ 不需要     | 编排逻辑在 `main.py`，不进 `AtomService`      |

### 代码质量改进

✅ 原始 `rmcp_proxy.py` 已拆分为 6 模块，bare except 已在 Phase 5 + Code Review 中修复为精确异常类型。

---

## 1. 代码结构

```
SpecDetect_Atom/
├── proxy/                    ← 新增：proxy 源码包
│   ├── __init__.py           ← 空包标记
│   ├── __main__.py           ← 入口，支持 `python -m proxy --config <path>`
│   ├── constants.py          ← FUNCID_TO_NAME, NBDTYPE_TO_NAME, MSG_TYPE_*
│   ├── frame.py              ← RMCPFrame 类（帧解析器，~230 行）
│   ├── logger.py             ← CaptureLogger 类（日志记录器，~320 行精简后）
│   ├── connection.py         ← ProxyConnection 类（TCP 透传，~230 行）
│   └── config.py             ← 从 settings.json 读 rmcp_proxy 段
├── src/atom/                 ← Atom 主代码（不变）
├── config/settings.json      ← 已有 rmcp_proxy 段（需小幅修正）
├── packaging/
│   ├── SpecDetect_Atom.spec  ← 不变
│   └── rmcp_proxy.spec       ← 新增：proxy 独立 PyInstaller spec
└── tests/
    ├── test_proxy_config.py          ← 单元测试 (6)
    ├── test_proxy_frame.py           ← 单元测试 (11)
    ├── test_proxy_logger.py          ← 单元测试 (9)
    └── integration/
        ├── __init__.py               ← 集成测试包
        ├── mock_device.py            ← Mock RMCP 设备
        └── test_proxy_integration.py ← 集成测试 (19)
```

### 模块依赖关系

```
proxy/__main__.py
  ├─→ proxy/config.py          (无依赖)
  ├─→ proxy/logger.py          (依赖 constants.py, frame.py)
  ├─→ proxy/connection.py      (依赖 constants.py, frame.py, logger.py)
  │     ├─→ proxy/constants.py
  │     ├─→ proxy/frame.py
  │     └─→ proxy/logger.py
  └─→ proxy/constants.py       (被 frame.py, logger.py, connection.py 依赖)
```

## 1.1 待修复问题

| #   | 问题                                    | 严重度      | 位置                  | 状态      |
| --- | ------------------------------------- |:--------:| ------------------- |:-------:|
| ✅   | `frames`/`connections` 列表内存泄漏         | CRITICAL | `logger.py`         | **已修复** |
| ✅   | `rmcp_proxy.enabled` → Phase 1-5 删除    | LOW      | `proxy/config.py`   | **已删除** |
| ✅   | `rmcp_proxy.enabled` → Phase 6 加回      | —        | `settings.json` / `main.py` | **已完成** |
| ✅   | accept 线程死亡 → 僵尸 proxy                | HIGH     | `__main__.py`       | **已修复** |
| ✅   | `_parent_alive()` 异常返回 True           | MEDIUM   | `__main__.py:56-57` | **已修复** |
| ✅   | `get_version` 未加入 hiddenimports       | MEDIUM   | `rmcp_proxy.spec`   | **已修复** |
| ✅   | `build.bat` 复制过时 `rmcp_settings.json` | LOW      | `build.bat`         | **已删除** |
| ✅   | `connection.py` inline import         | LOW      | `connection.py:239` | **已修复** |
| ✅   | `log_frame` 关在 `parse_enabled` 门后     | HIGH     | `connection.py`     | **已修复** |
| ✅   | `connection.py` TOCTOU 线程竞争          | HIGH     | `connection.py`     | **已修复** |
| ✅   | `_parse_and_store_funcid` bare except | HIGH     | `connection.py:243` | **已修复** |
| —   | `legacy/devinfo/` 缺失刺树丫站 XML          | —        | 不需要                 | 回退      |
| ✅   | Phase 5 联调测试                          | —        | —                   | **已完成** |

---

## 2. 功能分层

| 层级      | 功能                                 | 配置键                        | 默认值        |
| ------- | ---------------------------------- | -------------------------- |:----------:|
| **基础层** | TCP 透传 + 多端口监听 + 控制台极简输出           | （始终开启）                     | —          |
| **解析层** | RMCP 帧头解析 + funcid 提取 + nBdType 识别 | `rmcp_proxy.parse.enabled` | `false`    |
| **日志层** | .log / .raw / .json / .csv / 按接口分离 | `rmcp_proxy.log.*`         | 全部 `false` |

---

## 3. 实施阶段

| 阶段  | 内容                              | 估时    | 子 Agent 文件                                        |
|:---:| ------------------------------- |:-----:| ------------------------------------------------- |
| 1   | 整合 proxy 源码到 `proxy/` 目录，适配共享配置 | 1 天   | `agents/AGENT_phase1_proxy_source_integration.md` |
| 2   | 添加日志开关（解析/日志分层控制）               | 0.5 天 | `agents/AGENT_phase2_log_switches.md`             |
| 3   | proxy 稳定性保障（僵尸防护 + `_parent_alive` + 版号） | 0.5 天 | `agents/AGENT_phase3_process_management.md`       |
| 4   | PyInstaller 构建 + 部署包验证          | 0.5 天 | `agents/AGENT_phase4_build_packaging.md`          |
| 5   | 联调测试（19 项集成测试全部通过）               | 1 天   | `tests/integration/test_proxy_integration.py`     |
| 6   | Atom 子进程启动 proxy（`main.py` 编排）      | 0.5 天 | —                                                |
| 7   | 方案C: 同 exe 不同入口（proxy 不再独立 exe）    | 0.5 天 | —                                                |

### Phase 6 实施计划

**目标**：SGAtom 启动时自动 spawn `rmcp_proxy.exe` 子进程，退出时自动 kill。

**改动文件**：

| 文件 | 改动 | 行数 |
|------|------|:---:|
| `src/main.py` | 新增 `_spawn_proxy()` / `_kill_proxy()` + 信号处理 | ~30 |
| `config/settings.json` | 加回 `rmcp_proxy.enabled: true` | 1 |

**伪代码**：

```python
# main.py 新增

def _find_proxy_exe() -> Optional[str]:
    """在 exe 同级目录查找 rmcp_proxy_v*.exe"""
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
    for f in os.listdir(exe_dir):
        if f.startswith('rmcp_proxy_v') and f.endswith('.exe'):
            return os.path.join(exe_dir, f)
    return None

def _spawn_proxy(config_path: str) -> Optional[subprocess.Popen]:
    """启动 rmcp_proxy 子进程"""
    proxy_exe = _find_proxy_exe()
    if not proxy_exe:
        warn("rmcp_proxy.exe 未找到，跳过代理启动", LogTag.ATOM)
        return None
    info(f"启动 RMCP 代理: {proxy_exe}", LogTag.ATOM)
    return subprocess.Popen(
        [proxy_exe, '--config', config_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

# 在 main() 中:
#   1. 读 config → rmcp_proxy.enabled == True?
#   2. proxy_proc = _spawn_proxy(config_file)
#   3. service.start()
#   4. signal_handler → proxy_proc.terminate() → service.stop()
```

**数据流**：

```
Atom (main.py)
  ├─ config.rmcp_proxy.enabled == true
  ├─ _spawn_proxy() → Popen("rmcp_proxy_v1.0.8.exe --config ...")
  │      │
  │      └──→ [独立进程] rmcp_proxy.exe
  │              ├─ 读 settings.json → rmcp_proxy 段
  │              ├─ listen 9999, 8888
  │              ├─ forward → target (100.72.95.36:1449)
  │              └─ _parent_alive() 每 1s 检测
  │
  ├─ service.start() → Atom 正常运行
  │      Atom → 127.0.0.1:9999 → proxy → 100.72.95.36:1449
  │
  └─ SIGINT/SIGTERM
       ├─ proxy_proc.terminate()  (SIGTERM)
       ├─ proxy_proc.wait(timeout=5)
       └─ proxy_proc.kill()       (fallback)
```

**不变量**：

- `proxy/` 包源代码 **零改动**
- `AtomService` **零改动**
- proxy 仍可独立启动：`rmcp_proxy_v1.0.8.exe --config config\settings.json`
- 找不到 exe 时 Atom 正常工作（降级，不阻塞）

### Phase 7 实施计划（方案 C：同 exe 不同入口）

**目标**：proxy 不再作为独立 exe 存在，而是 SGAtom.exe 的一个子进程入口。单文件部署，无 UAC 弹窗。

**核心 idea**：PyInstaller 将所有 Python 模块冻结进 SGAtom.exe。启动 proxy 时运行 `SGAtom.exe --proxy-subprocess --config ...`，main.py 根据标志位决定走 Atom 主流程还是 proxy 子流程。

**改动文件**：

| 文件 | 改动 | 行数 |
|------|------|:---:|
| `src/main.py` | 顶部新增 `--proxy-subprocess` 入口分支 | ~15 |
| `src/atom/proxy_launcher.py` | `spawn_proxy()` frozen 模式改用 `sys.executable` | ~5 |
| `packaging/SpecDetect_Atom.spec` | **删除**方案 A 的嵌入逻辑（`_proxy_exes` 等） | -15 |
| `build.bat` | **还原**构建顺序（无需 proxy 先构建） | ~10 |

**删除的代码**：

| 删除 | 原因 |
|------|------|
| `SpecDetect_Atom.spec` 嵌入逻辑 | 不再需要 `--add-binary` |
| `build.bat` 构建顺序依赖 | proxy 不需要先于 Atom 构建 |
| `find_proxy_exe()` frozen 中查找 `_MEIPASS` | 直接用 `sys.executable` |
| `packaging/rmcp_proxy.spec` 入口 `run_proxy.py` | 方案 A 特定的 wrapper，不再需要 |

**不变量**：

- `proxy/` 包源代码 **零改动**
- `AtomService` **零改动**
- proxy 仍可独立运行（`python -m proxy` 开发模式）
- `_parent_alive()` 兜底孤儿防护 **保留**

---

## 4. 风险清单

| #   | 风险                                 | 严重度   | 缓解措施                                                                                             |
| --- | ---------------------------------- |:-----:| ------------------------------------------------------------------------------------------------ |
| R1  | ~~PyInstaller 打包 `proxy/` 包后入口模块解析失败~~ | ~~高~~ | ✅ Phase 4 已验证 `rmcp_proxy.exe` 可独立运行，`__main__.py` 入口正常 |
| R2  | 无真实 Device 环境，测试需 mock             | 中     | Mock device ~30 行 Python；真实设备后补充回归测试                                                             |
| R3  | 端口冲突（9999/8888 被占用）                | 低     | bind 失败输出清晰错误并退出；crash handler 延迟重试（5s，3 次）                                                      |
| R4  | proxy 进程稳定性（死亡/断连/端口泄漏）            | 中     | 见 Phase 3 稳定性分析                                                                                  |
| R5  | `main.py` 找不到 `rmcp_proxy.exe`      | **高** | 按 exe 相对路径查找；找不到时 warn 并跳过，Atom 仍可正常工作                  |
| R6  | proxy 子进程无法被 kill 导致僵尸             | 中     | `_parent_alive()` 兜底；`taskkill /F` 作为最后手段                            |
| R7  | proxy exe 版本与配置不兼容                  | 低     | Phase 4 已验证 spec 入口正确；用户需保证 exe 与 config 匹配                       |

---

## 5. 涉及文件

| 文件                               | 状态    | 说明                              |
| -------------------------------- |:-----:| ------------------------------- |
| `proxy/__init__.py`              | ✅ 完成 | 空包标记                            |
| `proxy/__main__.py`              | ✅ 完成 | 入口 + `start_proxy()` + `_parent_alive` |
| `proxy/constants.py`             | ✅ 完成 | FUNCID_TO_NAME, NBDTYPE_TO_NAME |
| `proxy/frame.py`                 | ✅ 完成 | RMCPFrame 类                     |
| `proxy/logger.py`                | ✅ 完成 | CaptureLogger + 开关              |
| `proxy/connection.py`            | ✅ 完成 | ProxyConnection TCP 透传（线程安全）    |
| `proxy/config.py`                | ✅ 完成 | 读 settings.json rmcp_proxy 段    |
| `src/main.py`                    | ✅ Phase 6 | 子进程启动/停止 proxy（import proxy_launcher） |
| `src/atom/proxy_launcher.py`     | ✅ Phase 6 | read/spawn/stop proxy 零副作用模块        |
| `src/atom/service.py`            | — 不变  | Atom 与 proxy 解耦                 |
| `src/atom/config.py`             | — 不变  | Atom 与 proxy 解耦                 |
| `config/settings.json`           | ✅ Phase 6 | `rmcp_proxy.enabled: true` + target 更新 |
| `packaging/SpecDetect_Atom.spec` | — 不变  | —                               |
| `packaging/rmcp_proxy.spec`      | ✅ 完成 | proxy 独立 PyInstaller spec (VERSION 动态) |
| `build.bat`                      | ✅ 完成 | RMCPProxy 构建路径已修正                |
| `tests/test_proxy_config.py`     | ✅ 完成 | 配置加载测试 (6 tests)                |
| `tests/test_proxy_frame.py`      | ✅ 完成 | 帧解析测试 (11 tests)                |
| `tests/test_proxy_logger.py`     | ✅ 完成 | 日志开关测试 (9 tests)                |
| `tests/integration/__init__.py`  | ✅ 完成 | 集成测试包标记                          |
| `tests/integration/mock_device.py` | ✅ 完成 | Mock RMCP 设备 (echo/fscan/req-rsp) |
| `tests/integration/test_proxy_integration.py` | ✅ 完成 | 19 项端到端集成测试                      |

---

## 6. 配置修正

`settings.json` 中 `rmcp_proxy` 段（Phase 6 最终版）：

```json
"rmcp_proxy": {
    "enabled": true,
    "listen": {
      "host": "0.0.0.0",
      "port_1": 9999,
      "port_2": 8888
    },
    "target": {
      "host": "100.72.95.36",
      "port": 1449
    },
    "parse": {
      "enabled": true
    },
    "log": {
      "dir": "logs",
      "text_enabled": true,
      "raw_enabled": true,
      "json_enabled": true,
      "csv_enabled": true,
      "per_interface_enabled": true
    }
}
```

---

## 7. 子 Agent 文件清单

> **注**：Phase 1-5 的 agent MD 文件已规划但 `agents/` 目录未创建。实际实施通过运行时 agent 直接分析+修改完成。

| 文件（计划）                                            | 用途                                    | 实际方式 |
| ------------------------------------------------- | ------------------------------------- |:----:|
| `agents/AGENT_phase1_proxy_source_integration.md` | Phase 1：6 模块拆分 + 配置适配 + 单元测试          | 运行时 agent |
| `agents/AGENT_phase2_log_switches.md`             | Phase 2：解析层/日志层开关实现                   | 运行时 agent |
| `agents/AGENT_phase3_process_management.md`       | Phase 3：proxy 稳定性保障（已改写）             | 运行时 agent |
| `agents/AGENT_phase4_build_packaging.md`          | Phase 4：PyInstaller 构建 + build.bat 更新 | 运行时 agent |
| `agents/AGENT_phase5_integration_test.md`         | Phase 5：端到端测试 + mock device           | 直接编码 |
| （无）                                               | Phase 6：`main.py` 子进程编排（~30 行）         | 直接编码 |
