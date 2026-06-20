# SPEC_20260620: 任务编排与协同实施

**日期**: 2026-06-20
**版本**: v1.6.0
**来源**: TASK_20260619_error_response_format.md
**角色**: 项目经理（Manager）

---

## 1. 需求来源

来自 `TASK_20260619_error_response_format.md`，当前 **2 个 P0 待实施任务** + **1 个后续高优需求**：

| 编号         | 内容                        | 优先级 | 估时   |
|:---------- | ------------------------- |:---:|:----:|
| P0-6       | RMCP 按 mfid/equid 路由      | P0  | 0.5h |
| P0-9       | DeviceStatusProvider 模块提取 | P0  | 0.5h |
| RMCP Proxy | 透明代理集成（5 阶段）              | 高   | 3.5d |

---

## 2. 任务拆解与 Agent 分配

### 2.1 P0-6: RMCP 按 mfid/equid 路由

**目标**: Source/Sink 模式连接 RMCP 设备时，根据请求的 mfid/equid 匹配 preset，使用 preset 的 station.serverip/serverport，而非固定全局 rmcp_host/rmcp_port。

**涉及文件**:
| 文件 | 改动 |
|------|------|
| `src/atom/config.py` | 新增 `get_rmcp_target(mfid, equid)` 方法 (~8 行) |
| `src/atom/service.py` | 2 处 RMCPClient 构造改为调用 `get_rmcp_target` (~10 行) |

**Agent 分配**:

| Agent       | 角色  | 职责                       |
| ----------- | --- | ------------------------ |
| P0-6-dev    | 开发  | 实现路由逻辑                   |
| P0-6-test   | 测试  | 编写单元测试，验证路由匹配 + fallback |
| P0-6-review | 审查  | 代码审查 + 安全审查              |

---

### 2.2 P0-9: DeviceStatusProvider 模块提取

**目标**: 将 `service.py` 中 97 行的 `_handle_query_faci_dev_stat` 提取为独立模块 `src/atom/device_status.py`，包含 `StatusResult` dataclass 和 `DeviceStatusProvider` 类。

**涉及文件**:
| 文件 | 改动 |
|------|------|
| `src/atom/device_status.py` | **新建**，~100 行，含 StatusResult + DeviceStatusProvider |
| `src/atom/service.py` | `_handle_query_faci_dev_stat` 缩减至 ~20 行 |

**Agent 分配**:

| Agent       | 角色  | 职责                           |
| ----------- | --- | ---------------------------- |
| P0-9-dev    | 开发  | 提取模块，重构 handler              |
| P0-9-test   | 测试  | 编写 DeviceStatusProvider 单元测试 |
| P0-9-review | 审查  | 代码审查 + 类型安全检查                |

---

## 3. 执行计划

```
Phase 1: 并行开发
├── Agent P0-6-dev → 实现 RMCP 路由
└── Agent P0-9-dev → 实现 DeviceStatusProvider

Phase 2: 并行测试
├── Agent P0-6-test → 测试 RMCP 路由
└── Agent P0-9-test → 测试 DeviceStatusProvider

Phase 3: 并行审查
├── Agent P0-6-review → 审查 RMCP 路由
└── Agent P0-9-review → 审查 DeviceStatusProvider
```

---

## 4. 验收标准

### P0-6

- [x] `config.get_rmcp_target(mfid, equid)` 返回匹配 preset 的 (host, port)
- [x] 无匹配时 fallback 到全局 `rmcp.host`/`rmcp.port`
- [x] service.py 两处 RMCPClient 构造使用 `get_rmcp_target`
- [x] 单元测试通过（14/14 PASS）

### P0-9

- [x] `StatusResult` dataclass 包含所有状态字段
- [x] `DeviceStatusProvider` 支持 idle/busy 判定
- [x] `DeviceStatusProvider` 支持 mode→feature 映射
- [x] `DeviceStatusProvider` 支持 mfname 查找
- [x] `_handle_query_faci_dev_stat` 缩减至 35 行（<40）
- [x] 单元测试通过，覆盖率 ~98%（38/38 PASS）

---

## 5. 目录结构

```
docs/V2/spec/
├── SPEC_20260620_orchestration.md    ← 本文件
└── tasks/
    ├── TASK_P0-6_rmcp_routing.md     ← P0-6 开发规格
    └── TASK_P0-9_device_status.md    ← P0-9 开发规格
```
