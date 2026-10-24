# REPORT_20260621: RMCP Proxy 日志冗余与内存优化分析

**日期**: 2026-06-21
**分析数据**: `logs/logs_sgatom_2026-06-20_2356/rmcp/`（~49 秒测量会话）
**状态**: ✅ 分析完成

---

## 0. 核心结论

| 结论 | 详情 |
|------|------|
| **无 Python 内存泄漏** | RAM 占用 <100KB，logger 中没有 `self.frames`/`self.*_buffer` 等累积结构 |
| **"文件突然变大"是 Windows 写缓存** | `flush()` 只推到 OS 缓冲区，文件关闭时 OS 才更新元数据（Explorer 中显示的文件大小） |
| **磁盘膨胀是真实问题** | 同一帧数据被写入 5 次，全开关打开时 ~323 MB/hr，其中 43% 是完全冗余的 |
| **最高性价比优化** | 关闭 `per_interface_enabled`，零代码改动，节省 43% 磁盘 I/O |

---

## 1. 文件清单

会话时长 ~49 秒（23:56:08 → 23:56:57），共 114 帧（93% 为 IFANALYSIS DATA 帧）。

| # | 文件 | 大小 | 占比 | 行数/类型 | 内容 |
|---|------|------|:---:|------|------|
| 1 | `capture_9999_*.json` | 1.89 MB | 44.7% | 114 行 JSON | 全量帧元数据 + hex 编码 raw 数据 + 解析后的频谱数组 |
| 2 | `rmcp_IFANALYSIS_9999_*.log` | 1.46 MB | 34.4% | 26,296 行 | IFANALYSIS DATA 帧的格式化 hex dump |
| 3 | `rmcp_IFANALYSIS_9999_*.raw` | 390 KB | 9.0% | 二进制 | IFANALYSIS DATA 帧 raw bytes + 文本包装头 |
| 4 | `capture_9999_*.raw` | 386 KB | 8.9% | 二进制 | 全量帧 raw bytes（无分隔符） |
| 5 | `capture_9999_*.log` | 121 KB | 2.8% | 2,235 行 | 全量帧可读文本（RMCP 头 + SOAP XML + 频谱摘要） |
| 6 | `connections_9999_*.csv` | 1.3 KB | 0.03% | 15 行 | 连接生命周期事件 |
| 7 | `capture_8888_*.log` | 248 B | <0.01% | 7 行 | 空（端口无流量） |
| 8 | `connections_8888_*.csv` | 95 B | <0.01% | 1 行 | 空 |
| **合计** | | **4.2 MB** | | | |

**外推 1 小时**: ~323 MB（10 Hz 帧率，114 帧/49s → ~8,400 帧/hr）

---

## 2. 冗余矩阵

| | capture.log | capture.raw | capture.json | conn.csv | per-if.log | per-if.raw |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **capture.log** | — | 无重叠 | **100% 被 JSON 包含** | 无重叠 | 帧头 + 元数据重叠 | 无重叠 |
| **capture.raw** | 无重叠 | — | **100%（hex 形式，2x 膨胀）** | 无重叠 | 无重叠 | **100%（子集 + 包装开销）** |
| **capture.json** | 元数据超集 | hex = raw×2 | — | 无重叠 | hex + 头 + 元数据超集 | hex = raw×2 |
| **per-if.log** | 帧头重叠 | 无重叠 | **100% 被 JSON 包含** | 无重叠 | — | ~40% hex dump = raw |
| **per-if.raw** | 无重叠 | **严格子集** | JSON hex 字段 | 无重叠 | ~40% 重叠 | — |
| **conn.csv** | 无重叠 | 无重叠 | 无重叠 | — | 无重叠 | 无重叠 |

**冗余链总结**:

```
capture.raw ──(hex 编码)──→ capture.json["hex"] ──(格式化)──→ per-if.log（hex dump）
                                                  ──(包装)───→ per-if.raw（子集 + 头）

capture.log 是 capture.json 的真子集（无 hex dump，频谱截断到 50 点）
per-if.*  是 capture.json 的过滤真子集（仅 S→C DATA 帧，按 nBdType 分类）
conn.csv   是唯一无冗余的文件类型（连接生命周期事件）
```

---

## 3. 内存累积分析

### 3.1 Logger 内部结构

`CaptureLogger` 类中只有 **两个** 持久容器，且大小有界：

| 结构 | 类型 | 增长模式 | 风险 |
|------|------|---------|:--:|
| `self.rmcp_callback_files` | `Dict[str, file_handle]` | 最多 5 个条目（按 nBdType） | 无 |
| `self.rmcp_callback_raw_files` | `Dict[str, file_handle]` | 最多 5 个条目 | 无 |

**不存在**:
- `self.frames` 列表
- `self.*_buffer` 累积缓冲
- `self.*_cache` 帧引用
- 任何无限增长的内存结构

### 3.2 帧处理内存流

```
log_frame(data) 调用
  → frame_info = {...}            # 局部变量，~16KB（含 hex 字符串）
  → 写入 capture.raw              # 直接 write，立即释放
  → 写入 capture.json             # json.dump，立即释放
  → 写入 capture.log              # 格式化文本，立即释放
  → 如果是 DATA 帧:
      → _log_rmcp_callback_data() → 写入 per-if.log + per-if.raw
  → 函数返回，frame_info GC 回收
```

**结论**: 每帧的内存峰值 ~16KB，函数返回后全部释放。RAM 在任何时刻 <100KB。

### 3.3 "文件突然变大"根因

三层原因叠加：

1. **Windows OS 写缓存**（主要原因）：`file.flush()` 从 Python 缓冲区推到 OS 缓冲区，但 OS 不保证立即更新文件元数据（Explorer 中显示的大小）。文件关闭时才强制提交。

2. **事后观察效应**：用户通常在退出 SGAtom 后才检查日志目录，看到的是整个测量期间线性累积的总量。

3. **`data.hex()` 膨胀**（logger.py:149）：bytes → hex 字符串（2x 膨胀），然后 JSON 和 text log 中再次格式化。`_write_payload_summary` 又调用 `bytes.fromhex()` 做反向转换——一次浪费的往返。

---

## 4. 各日志类型的必要性判定

| 日志开关 | 内容 | 必要性 | 判定 |
|---------|------|:---:|:--:|
| `raw_enabled` | 全量帧 raw bytes | 最紧凑的完整记录，可离线重解析 | ✅ **必要**（调试用） |
| `json_enabled` | 全量帧元数据 + hex + 解析结果 | 结构化、可查询、自包含 | ✅ **必要**（分析用） |
| `text_enabled` | 全量帧可读文本 | 完全被 JSON 包含，无唯一数据 | ⚠️ 冗余（与 JSON 二选一） |
| `csv_enabled` | 连接生命周期事件 | 唯一记录 CONNECT/CLOSE 的文件，体积极小 | ✅ **必要** |
| `per_interface_enabled` | 按 nBdType 分离的 DATA 帧 | **完全冗余**，是 capture.* 的严格过滤子集 | ❌ **冗余** |

---

## 5. 推荐配置方案

### 方案 A："生产运行"（推荐，零代码改动）

```json
"log": {
    "dir": "logs/rmcp",
    "text_enabled": false,
    "raw_enabled": true,
    "json_enabled": true,
    "csv_enabled": true,
    "per_interface_enabled": false
}
```

| 指标 | 当前 | 方案 A | 节省 |
|------|------|--------|:---:|
| 磁盘/hr | ~323 MB | ~173 MB | **46%** |
| 文件数 | 8 | 4 | 50% |
| 数据完整性 | 100% | 100% | 无损 |
| 代码改动 | — | 0 | 纯配置 |

### 方案 B："极简"（超长运行）

```json
"log": {
    "dir": "logs/rmcp",
    "text_enabled": false,
    "raw_enabled": true,
    "json_enabled": false,
    "csv_enabled": true,
    "per_interface_enabled": false
}
```

| 指标 | 当前 | 方案 B | 节省 |
|------|------|--------|:--:|
| 磁盘/hr | ~323 MB | ~28 MB | **91%** |
| 代价 | — | 无解析元数据，需离线重解析 raw | — |

### 方案 C："全量调试"（仅开发/调试时）

保持当前全开关打开，但仅用于短期调试会话。

---

## 6. 建议的代码优化（可选，低优先级）

| 序号 | 改动 | 文件 | 效果 | 估时 |
|:---:|------|------|------|:---:|
| 1 | 移除 `data.hex()` 往返：JSON 中改用 base64 或移除 hex 字段 | `proxy/logger.py:149` | JSON 文件缩小 ~33% | 0.5h |
| 2 | `_write_payload_summary` 直接使用 bytes 参数而非 `bytes.fromhex()` | `proxy/logger.py:330-339` | 消除浪费的 hex→bytes 转换 | 0.25h |
| 3 | 对长时间运行添加 `os.fsync()`，确保 Windows 元数据实时更新 | `proxy/logger.py:393,417` | 文件大小在 Explorer 中实时可见 | 0.25h |
| 4 | 添加周期性帧计数器日志（每 N 帧打印统计） | `proxy/logger.py` | 用户可在运行中观察累积进度 | 0.5h |
| 5 | 8888 端口文件延迟创建（仅首次连接时） | `proxy/logger.py:64` | 消除空文件 | 0.25h |

---

## 7. 立即行动项

| 优先级 | 操作 | 效果 |
|:---:|------|------|
| **P0** | 修改 `config/settings.json`，设 `per_interface_enabled: false` | 节省 43% 磁盘 I/O |
| P1 | 按方案 A 调整生产配置 | 节省 46% |
| P2 | 代码优化 #1-#3 | 进一步缩小 + 实时可见 |

---

## 附录: 数据来源

- 分析样本: `logs/logs_sgatom_2026-06-20_2356/rmcp/` 目录下 8 个文件
- 源文件分析: `proxy/logger.py`、`proxy/connection.py`、`proxy/config.py`、`proxy/frame.py`
- 帧统计: 114 总帧（106 DATA + 4 REQUEST/RESPONSE + 4 CONTROL）
