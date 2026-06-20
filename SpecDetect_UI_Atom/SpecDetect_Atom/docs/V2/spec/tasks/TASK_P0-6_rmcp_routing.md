# TASK_P0-6: RMCP 按 mfid/equid 路由

**日期**: 2026-06-20
**优先级**: P0（必处理）
**估时**: 0.5h
**来源**: SPEC_20260620_orchestration.md

---

## 1. 问题描述

`service.py` 中 Source 模式（L1120）和 Sink 模式（L352）创建 `RMCPClient` 时，固定使用全局 `self.config.rmcp_host` / `self.config.rmcp_port`。但真实 Atom 应根据请求报文中的 mfid/equid 匹配 preset，使用 preset 对应站点的 `station.serverip` / `station.serverport`。

## 2. 实现方案

### 2.1 config.py: 新增 `get_rmcp_target()` 方法

```python
def get_rmcp_target(self, mfid: str = '', equid: str = '') -> tuple:
    """根据 mfid/equid 获取 RMCP 连接目标

    匹配规则：遍历 rmcp.presets，找 mfid+equid 匹配的 preset，
    返回其 station.serverip / station.serverport。
    无匹配时 fallback 到全局 rmcp.host / rmcp.port。

    Args:
        mfid: 设备 mfid
        equid: 设备 equid

    Returns:
        (host: str, port: int)
    """
    if mfid and equid:
        for preset in self.rmcp_presets:
            if preset.get('mfid') == mfid and preset.get('equid') == equid:
                station = preset.get('station', {})
                host = station.get('serverip', '')
                port = station.get('serverport', 0)
                if host and port:
                    return host, port
                break
    # Fallback 到全局配置
    return self.rmcp_host, self.rmcp_port
```

### 2.2 service.py: 2 处 RMCPClient 构造改为使用路由

**位置 1** — `_start_sink_stream` (L351-355):
```python
# 旧
rmcp_client = RMCPClient(
    host=self.config.rmcp_host,
    port=self.config.rmcp_port,
    timeout=10
)

# 新
rmcp_host, rmcp_port = self.config.get_rmcp_target(
    getattr(session, 'mfid', ''), getattr(session, 'equid', '')
)
rmcp_client = RMCPClient(
    host=rmcp_host,
    port=rmcp_port,
    timeout=10
)
```

**位置 2** — `_match_and_start_stream` (L1119-1123):
```python
# 旧
rmcp_client = RMCPClient(
    host=self.config.rmcp_host,
    port=self.config.rmcp_port,
    timeout=10
)

# 新
rmcp_host, rmcp_port = self.config.get_rmcp_target(
    session.fscan_params.get('mfid', ''),
    session.fscan_params.get('equid', '')
)
rmcp_client = RMCPClient(
    host=rmcp_host,
    port=rmcp_port,
    timeout=10
)
```

## 3. 注意事项

- `_start_sink_stream` 中 session 可能没有 mfid/equid 属性 — 需要检查 session 对象的实际属性名，使用 `getattr` 安全获取
- 全局配置必须在 fallback 中保持可用，保证向后兼容
- 不要修改 `config.py` 现有的 `rmcp_host`/`rmcp_port` property（已有消费者依赖）

## 4. 验收标准

- [ ] `config.get_rmcp_target('53090001140005', 'AE777276-...')` 返回 `('172.18.114.226', 9999)`
- [ ] `config.get_rmcp_target('unknown', 'unknown')` 返回全局 `('100.72.95.36', 1449)`
- [ ] `config.get_rmcp_target('', '')` 返回全局 fallback
- [ ] service.py 两处 RMCPClient 构造均改为使用 `get_rmcp_target`
- [ ] 现有功能不退化（单元测试通过）
