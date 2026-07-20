# RMCP Proxy 配置说明

> 配置文件：`SpecDetect_UI_Atom/SpecDetect_Atom/config/settings.json`  
> 改完需重启 SGAtom 生效

---

## 启用 / 停用

```json
"rmcp_proxy": { "enabled": true }   // 启用（启动 SGAtom 时一并拉起代理）
"rmcp_proxy": { "enabled": false }  // 停用（客户端直连 device，不走代理）
```

---

## 端口对应关系（关键）

**核心原则：客户端零修改**。rmcp_proxy 接在客户端和 device 中间，把客户端"以为"的端口接过来，再转发到 device 实际监听的端口。

```text
                            rmcp_proxy 视角
  ┌──────────────┐    listen.port_1     ┌──────────────┐    target.host:port    ┌──────────────┐
  │   客户端      │ ──────────────────► │   rmcp_proxy │ ────────────────────► │    device     │
  │ (无需修改)    │   9999 / 8888       │   (本机)      │   100.72.95.36:1449  │ (改了端口)    │
  └──────────────┘                      └──────────────┘                       └──────────────┘
        ▲                                     │                                       │
        │                                     │ listen.port_2 (备用)                   │
        └─────────────────────────────────────┘ 8888
```

| 配置项 | 含义 | 典型值 | 谁在用 |
|---|---|---|---|
| `listen.port_1` / `port_2` | **device 原本监听的端口**（客户端认知的端口） | `9999` / `8888` | 客户端连这里 |
| `target.host:port` | **device 改后实际监听的新地址** | `100.72.95.36:1449` | rmcp_proxy 连这里 |

对应到 `rmcp.presets` 中的 `station.serverport`：所有 preset 都写 `9999`，因为客户端认知的端口就是 `listen.port_1`。

---

## 完整配置

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
  "parse": { "enabled": false },
  "log": {
    "dir": "logs/rmcp",
    "text_enabled": false,
    "raw_enabled": false,
    "json_enabled": false,
    "csv_enabled": false,
    "per_interface_enabled": false
  }
}
```

---

## 字段说明

### `enabled`

| 值 | 含义 |
|---|---|
| `true` | 启动 SGAtom 时一并启动代理 |
| `false` | 不启动代理，客户端直连 device |

### `listen`（rmcp_proxy 对外监听的端口 = device 原端口）

| 字段 | 含义 |
|---|---|
| `host` | 监听地址。`0.0.0.0` = 所有网卡；`127.0.0.1` = 仅本机 |
| `port_1` | 主端口，**对应 device 原监听端口**（客户端连这里） |
| `port_2` | 备用端口，行为与 `port_1` 完全相同，都转发到同一个 `target` |

### `target`（device 改后的实际地址）

| 字段 | 含义 |
|---|---|
| `host` | device IP |
| `port` | device RMCP 新端口（默认 1449） |

### `parse`（是否解析 RMCP 协议）

| 值 | 含义 |
|---|---|
| `false` | TCP 透传，**性能高**（推荐生产用） |
| `true` | 解析 RMCP 帧结构（业务感知、状态统计） |

### `log`（日志配置）

| 字段 | 默认 | 含义 |
|---|---|---|
| `dir` | `logs/rmcp` | 日志目录（相对 SGAtom 启动目录） |
| `text_enabled` | false | 人类可读文本 |
| `raw_enabled` | false | 原始字节流（hex dump） |
| `json_enabled` | false | 结构化 JSON |
| `csv_enabled` | false | CSV（Excel 分析） |
| `per_interface_enabled` | false | 是否按 `port_1` / `port_2` 分目录 |

`per_interface_enabled: true` 时日志按端口分目录：

```text
logs/rmcp/port_1/raw/  json/  csv/
logs/rmcp/port_2/raw/  json/  csv/
```

---

## 部署步骤

1. **改 device 端口**：把 device 的 RMCP 监听端口从原值改成 `target.port`（如 `1449`）。
2. **改 settings.json**：按上表填好 `listen.port_1`（device 原端口，如 `9999`）和 `target.host:port`（device 新地址）。
3. **启动 SGAtom**：rmcp_proxy 自动启动，监听 `listen.port_1` 和 `listen.port_2`，转发到 `target.host:port`。
4. **客户端无需修改**：客户端原本连 `device:9999`，现在还是连 `<atom_PC_IP>:9999`（或 `:8888`），由 rmcp_proxy 透明转发到 device 新端口。

`<atom_PC_IP>` = atom 所在机器的 IP（同机时常用 `127.0.0.1`），**不是 device 的 IP**。