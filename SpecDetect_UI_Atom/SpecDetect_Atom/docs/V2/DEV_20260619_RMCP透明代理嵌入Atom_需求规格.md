# DEV_20260619: RMCP 透明代理集成到 Atom 部署包 需求规格

**日期**: 2026-06-19
**版本**: v2.0（需求澄清后修订）
**状态**: 分析完成，待实施
**来源**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_POC\rmcp_proxy\`

---

## 1. 需求概述

将 rmcp_proxy 整合到 SpecDetect_Atom 工程中，作为**独立子进程**与 Atom 一起打包部署。启动 Atom 时自动拉起 proxy 进程。

### 1.1 核心原则

| 原则         | 说明                                               |
| ---------- | ------------------------------------------------ |
| **独立进程**   | proxy 与 Atom 是同一部署包的两个进程，运行时独立                   |
| **自动拉起**   | 启动 Atom 时自动启动 proxy；Atom 退出时自动终止 proxy           |
| **旁观者角色**  | proxy 监听 RMCP 端口，旁观所有流量（Atom 的 + 其他客户端的），不做进程内嵌入 |
| **透传永远开启** | TCP 双向透传是基础功能，始终运行，不可关闭                          |
| **分析功能按需** | 帧解析、按接口分离日志默认关闭，通过配置开启                           |

---

## 2. 部署架构

```
┌──────────────────────────────────────────────────┐
│              SpecDetect_Atom 部署包               │
│                                                  │
│  ┌──────────────────┐  ┌──────────────────────┐  │
│  │   SGAtom.exe     │  │  rmcp_proxy.exe      │  │
│  │   (SOAP 服务)    │  │  (RMCP 透明代理)     │  │
│  │                  │  │                      │  │
│  │  port 8284       │  │  listen: 9999, 8888  │  │
│  │                  │  │  target: 127.0.0.1   │  │
│  └────────┬─────────┘  │          :19999      │  │
│           │            └──────────┬───────────┘  │
│           │                       │              │
│  Atom ────┤── RMCP ──→ [9999] ──→│──→ Device    │
│           │                       │              │
│  Others ──┼── RMCP ──→ [8888] ──→│              │
│           │                       │              │
│           │         ┌─────────────┤              │
│           │         │ 透传 (始终) │              │
│           │         │ 解析 (按需) │              │
│           │         │ 日志 (按需) │              │
│           │         └─────────────┘              │
│  shared config/settings.json                     │
└──────────────────────────────────────────────────┘
```

**关键**：所有 RMCP 流量必须经过 proxy 的监听端口。Atom 和其他客户端不直连 Device，而是连接 proxy 的监听端口。

---

## 3. 功能分层

### 3.1 基础层（始终开启，不可关闭）

| 功能         | 说明                          |
| ---------- | --------------------------- |
| **TCP 透传** | 双向转发，字节不修改。这是 proxy 存在的根本目的 |
| **多端口监听**  | 同时监听两个端口，接受多个客户端连接          |
| **进程管理**   | Atom 启动时拉起，Atom 退出时终止       |

### 3.2 解析层（默认关闭，配置开启）

| 功能                      | 配置键                        | 默认值     |
| ----------------------- | -------------------------- |:-------:|
| RMCP 帧头解析               | `rmcp_proxy.parse.enabled` | `false` |
| funcid 提取（SOAP→RMCP 关联） | （跟随 parse.enabled）         | `false` |
| nBdType 识别              | （跟随 parse.enabled）         | `false` |

### 3.3 日志层（默认关闭，配置开启）

| 功能              | 配置键                                    | 默认值     |
| --------------- | -------------------------------------- |:-------:|
| 结构化文本日志 (.log)  | `rmcp_proxy.log.text_enabled`          | `false` |
| 原始二进制 (.raw)    | `rmcp_proxy.log.raw_enabled`           | `false` |
| JSON 日志 (.json) | `rmcp_proxy.log.json_enabled`          | `false` |
| 连接 CSV (.csv)   | `rmcp_proxy.log.csv_enabled`           | `false` |
| 按接口分离回调日志       | `rmcp_proxy.log.per_interface_enabled` | `false` |

**全部关闭时**：proxy 进程只做 TCP 透传 + 控制台极简输出（连接/断开事件），CPU/内存/磁盘开销接近零。

### 3.4 状态感知（后续研究）

设备繁忙状态感知需要低消耗方案，不在此版本范围。后续方向：在解析层开启时，从 DATA 帧中统计活跃度和 nBdType 模式。

---

## 4. 配置设计

### 4.1 共享配置文件

proxy 与 Atom 共用 `config/settings.json`，新增 `rmcp_proxy` 段：

```json
{
  "rmcp_proxy": {
    "listen": {
      "host": "0.0.0.0",
      "port_1": 9999,
      "port_2": 8888
    },
    "target": {
      "host": "127.0.0.1",
      "port": 19999
    },
    "parse": {
      "enabled": false
    },
    "log": {
      "dir": "logs",
      "text_enabled": false,
      "raw_enabled": false,
      "json_enabled": false,
      "csv_enabled": false,
      "per_interface_enabled": false
    }
  }
}
```

### 4.2 端口默认值

| 配置键                        | 默认值         | 说明           |
| -------------------------- |:-----------:| ------------ |
| `rmcp_proxy.listen.host`   | `0.0.0.0`   | 对外监听地址       |
| `rmcp_proxy.listen.port_1` | `9999`      | 主监听端口        |
| `rmcp_proxy.listen.port_2` | `8888`      | 副监听端口        |
| `rmcp_proxy.target.host`   | `127.0.0.1` | 目标 Device 地址 |
| `rmcp_proxy.target.port`   | `19999`     | 目标 Device 端口 |

---

## 5. 进程管理

### 5.1 Atom 启动 proxy

在 `AtomService.start()` 中：

```python
import subprocess

def start(self):
    # ... 现有启动逻辑 ...

    # 启动 rmcp_proxy 子进程
    proxy_exe = os.path.join(os.path.dirname(sys.executable), 'rmcp_proxy.exe')
    if os.path.exists(proxy_exe):
        self._proxy_process = subprocess.Popen(
            [proxy_exe, '--config', self.config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        info("rmcp_proxy 子进程已启动", LogTag.ATOM)
```

### 5.2 Atom 终止 proxy

```python
def stop(self):
    # ... 现有停止逻辑 ...

    if hasattr(self, '_proxy_process') and self._proxy_process:
        self._proxy_process.terminate()
        self._proxy_process.wait(timeout=5)
        info("rmcp_proxy 子进程已终止", LogTag.ATOM)
```

### 5.3 proxy 独立运行（调试用）

proxy 也支持命令行独立启动：

```
rmcp_proxy.exe --config path/to/settings.json
```

---

## 6. 代码整合方案

### 6.1 目录结构

```
SpecDetect_Atom/
├── src/
│   └── atom/           ← Atom 主代码（不变）
├── proxy/              ← 新增：proxy 源码
│   ├── __main__.py
│   ├── proxy.py        ← 从 rmcp_proxy/rmcp_proxy.py 整合
│   ├── config.py       ← 轻量适配，读 settings.json rmcp_proxy 段
│   └── logger.py       ← 精简日志模块
├── config/
│   └── settings.json   ← 新增 rmcp_proxy 段
├── packaging/
│   ├── SpecDetect_Atom.spec  ← Atom PyInstaller
│   ├── rmcp_proxy.spec       ← 新增：proxy PyInstaller
│   └── build_all.bat         ← 一次构建两个 exe
└── dist/
    ├── SGAtom.exe
    └── rmcp_proxy.exe
```

### 6.2 复用清单

| 来源 (`POC/rmcp_proxy/`)               | 目标 (`proxy/`)                              | 复用程度 |
| ------------------------------------ | ------------------------------------------ |:----:|
| `RMCPFrame` 类 (L134-359)             | 完整复用，加解析开关                                 | 95%  |
| `ProxyConnection` 类 (L909-1131)      | 完整复用，透传逻辑不变                                | 90%  |
| `CaptureLogger` 类 (L362-906)         | 按开关分层：透传→始终 / 日志→按需                        | 70%  |
| `start_proxy()` (L1133-1205)         | 改为从 `settings.json` 读配置                    | 60%  |
| `FUNCID_TO_NAME` / `NBDTYPE_TO_NAME` | 直接复用                                       | 100% |
| `parse_fscan_data_simple()`          | 直接复用                                       | 100% |
| 独立 `config.py`                       | **不复用** — 改为读 `settings.json` rmcp_proxy 段 | 0%   |
| 独立 `DEFAULT_CONFIG`                  | **不复用** — 配置文件与 Atom 共享                    | 0%   |

### 6.3 不纳入范围

| 项目                                          | 原因                   |
| ------------------------------------------- | -------------------- |
| `parse_fscan_data.py` / `compare_frames.py` | 独立分析工具，不属于 proxy 核心  |
| `rmcp_proxy.bat` / `start_rx_atom.bat`      | 旧启动脚本，由 Atom 自动拉起替代  |
| 旧 `config.py`                               | 改为共享 `settings.json` |

---

## 7. 构建与打包

### 7.1 单 exe，双进程

rmcp_proxy 代码打入 `SGAtom.exe`（`--add-data` 或作为 Python 模块），不生成独立 exe。

```python
# AtomService.start() 中
proxy_args = [sys.executable, '-m', 'proxy', '--config', config_file]
self._proxy_process = subprocess.Popen(proxy_args, ...)
```

### 7.2 部署包内容

```
SGAtom_v1.6.0.zip
└── SGAtom.exe           ← 单 exe，启动后两个进程
    ├── Atom 主进程 (SOAP 8284)
    └── proxy 子进程 (监听 9999+8888 → 19999)
```

---

## 8. 实施阶段

| 阶段  | 内容                                  | 估时    |
|:---:| ----------------------------------- |:-----:|
| 1   | 整合 proxy 源码到 `proxy/` 目录，适配共享配置     | 1 天   |
| 2   | 添加日志开关（解析/日志分层控制）                   | 0.5 天 |
| 3   | 进程管理（Atom 拉起/终止 proxy）              | 0.5 天 |
| 4   | PyInstaller 构建双 exe + build_all.bat | 0.5 天 |
| 5   | 联调测试                                | 1 天   |

---

## 9. 与 v1 版本的关键差异

|       | v1 方案（废弃）     | v2 方案（当前）                     |
| ----- | ------------- | ----------------------------- |
| 运行方式  | 嵌入 Atom 进程内   | **独立子进程**                     |
| 工作模式  | Socket 包装 tap | **独立端口监听透传**                  |
| 端口    | 无额外端口         | 9999 + 8888 → 19999           |
| 配置    | 新增 sniffer 段  | 共享 settings.json rmcp_proxy 段 |
| 透传    | 不适用           | **始终开启**（基础功能）                |
| 解析/日志 | 始终开启          | **默认关闭**，按需配置                 |
