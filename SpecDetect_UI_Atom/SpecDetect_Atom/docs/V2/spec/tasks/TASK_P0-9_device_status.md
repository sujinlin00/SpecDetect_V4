# TASK_P0-9: DeviceStatusProvider 模块提取

**日期**: 2026-06-20
**优先级**: P0（必处理）
**估时**: 0.5h
**来源**: SPEC_20260620_orchestration.md

---

## 1. 问题描述

`service.py` 的 `_handle_query_faci_dev_stat` 方法（L990-1086）共 97 行，混合了 5 个关注点：

| 关注点 | 位置 | 行数 |
|--------|------|:--:|
| mfid/equid/userid 正则提取 | L996-1002 | 7 |
| devinfo 文件加载 + equname 提取 | L1007-1015 | 9 |
| mfname 从 preset 查找 | L1019-1028 | 10 |
| 活动 session 状态判定 + mode→feature 映射 | L1031-1049 | 19 |
| idle 响应体硬编码构造 | L1065-1086 | 12 |

应提取为独立模块，提升可测试性和可维护性。

## 2. 实现方案

### 2.1 新建 `src/atom/device_status.py`

```python
# -*- coding: utf-8 -*-
"""设备状态提供者 — B_QueryFaciDevStat 处理器"""

import re
from dataclasses import dataclass, field
from typing import Optional, List

from atom.session import StreamSession


# ── 数据模型 ───────────────────────────────────────────

@dataclass
class StatusResult:
    """B_QueryFaciDevStat 响应数据"""
    mfid: str = ''
    mfname: str = 'Unknown'
    equid: str = ''
    equname: str = 'Unknown'
    state: str = 'idle'           # 'idle' | 'busy'
    altitude: str = '0.0'

    # busy 字段（idle 时为 None）
    taskid: Optional[str] = None
    userid: Optional[str] = None
    feature: Optional[str] = None
    appid: Optional[str] = None
    stc: Optional[int] = None


# ── 映射表 ─────────────────────────────────────────────

MODE_TO_FEATURE: dict = {
    'fscan': 'B_FScan',
    'pscan': 'B_PScan',
    'mscan': 'B_MScan',
    'sglfreq': 'B_SglFreqMeas',
}


# ── 提供者 ─────────────────────────────────────────────

class DeviceStatusProvider:
    """设备状态提供者

    职责：
    1. 从 devinfo XML 提取 equname
    2. 从 presets 查找 mfname
    3. 判定 idle/busy 并收集 busy 字段
    4. 构建 StatusResult
    """

    def __init__(self, preset_manager, config, session_manager):
        self._preset_manager = preset_manager
        self._config = config
        self._session_manager = session_manager

    def extract_request_ids(self, raw_body: str) -> dict:
        """从 SOAP body 提取 mfid/equid/userid"""
        mfid = self._regex_extract(raw_body, r'<[^>]*:mfid[^>]*>([^<]+)</[^>]*:mfid>')
        equid = self._regex_extract(raw_body, r'<[^>]*:equid[^>]*>([^<]+)</[^>]*:equid>')
        userid = self._regex_extract(raw_body, r'<[^>]*:userid[^>]*>([^<]+)</[^>]*:userid>')
        return {'mfid': mfid, 'equid': equid, 'userid': userid}

    def load_devinfo(self, mfid: str, equid: str) -> Optional[str]:
        """加载 devinfo XML 内容"""
        return self._preset_manager.load_responsebody(mfid, equid)

    def extract_equname(self, devinfo_xml: str) -> str:
        """从 devinfo XML 提取 equname"""
        match = re.search(
            r'<[^>]*:equname[^>]*>([^<]+)</[^>]*:equname>',
            devinfo_xml, re.IGNORECASE
        )
        return match.group(1).strip() if match else 'Unknown'

    def lookup_mfname(self, mfid: str, equid: str) -> str:
        """从 rmcp.presets 查找站点名"""
        for preset in self._config.rmcp_presets:
            if preset.get('mfid') == mfid and preset.get('equid') == equid:
                return preset.get('station', {}).get('name', 'Unknown')
        # Fallback
        presets = self._config.get('rmcp.presets', [])
        if presets:
            return presets[0].get('station', {}).get('name', 'Unknown')
        return 'Unknown'

    def get_status(self, mfid: str, equid: str, userid: str) -> StatusResult:
        """查询设备状态（主入口）

        流程：
        1. 加载 devinfo → 提取 equname
        2. 查找 mfname
        3. 检查活动 session → 判定 idle/busy
        4. 构造 StatusResult

        Returns:
            StatusResult: 设备状态结果
        """
        result = StatusResult(mfid=mfid, equid=equid)

        # equname
        devinfo_xml = self.load_devinfo(mfid, equid)
        if devinfo_xml:
            result.equname = self.extract_equname(devinfo_xml)

        # mfname
        result.mfname = self.lookup_mfname(mfid, equid)

        # 状态判定
        active_sessions = self._session_manager.get_active_sessions()
        if active_sessions:
            session = active_sessions[0]
            mode = session.fscan_params.get('mode', 'fscan')
            result.state = 'busy'
            result.taskid = session.taskid
            result.userid = session.fscan_params.get('userid', '') or userid
            result.feature = MODE_TO_FEATURE.get(mode, '')
            result.appid = session.fscan_params.get('appid', '')
            result.stc = session.fscan_params.get('stc', 0)

        return result

    def build_idle_body(self) -> str:
        """构建 idle 状态的 responsebody"""
        return (
            '<srrc:responsebody><srrc:result>'
            '<srrc:mfid>{mfid}</srrc:mfid>'
            '<srrc:mfname>{mfname}</srrc:mfname>'
            '<srrc:altitude>0.0</srrc:altitude>'
            '<srrc:equlist><srrc:equipment>'
            '<srrc:equid>{equid}</srrc:equid>'
            '<srrc:equname>{equname}</srrc:equname>'
            '<srrc:state>idle</srrc:state>'
            '</srrc:equipment></srrc:equlist>'
            '</srrc:result></srrc:responsebody>'
        )

    @staticmethod
    def _regex_extract(text: str, pattern: str) -> str:
        """正则提取，返回第一个捕获组，无匹配返回空字符串"""
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else ''
```

### 2.2 重构 `service.py` 的 `_handle_query_faci_dev_stat`

缩减至 ~25 行：

```python
def _handle_query_faci_dev_stat(self, request: dict) -> bytes:
    """处理 B_QueryFaciDevStat - 查询设备状态"""
    raw_body = request.get('body', b'').decode('utf-8', errors='replace')

    ids = self._device_status.extract_request_ids(raw_body)
    mfid, equid, userid = ids['mfid'], ids['equid'], ids['userid']
    info(f"B_QueryFaciDevStat mfid={mfid}, equid={equid}, userid={userid}", LogTag.SOAP)

    # 检查 devinfo 是否存在
    devinfo_xml = self._device_status.load_devinfo(mfid, equid)
    if not devinfo_xml:
        info(f"B_QueryFaciDevStat 未找到 devinfo 文件, key={mfid}_{equid}", LogTag.SOAP)
        return self.preset_manager.build_error_response(
            "设备信息未找到", error_code='BIZ-000002', error_type='error'
        )

    status = self._device_status.get_status(mfid, equid, userid)

    if status.state == 'busy':
        return self.preset_manager.build_response(
            'B_QueryFaciDevStat',
            mfid=status.mfid, mfname=status.mfname,
            equid=status.equid, equname=status.equname,
            state='busy',
            taskid=status.taskid, userid=status.userid,
            feature=status.feature, appid=status.appid, stc=status.stc
        )
    else:
        idle_body = self._device_status.build_idle_body()
        return self.preset_manager.build_response(
            'B_QueryFaciDevStat',
            body_content=idle_body,
            mfid=status.mfid, mfname=status.mfname,
            equid=status.equid, equname=status.equname,
            state='idle'
        )
```

### 2.3 `service.py` 初始化

在 `__init__` 中添加：

```python
from atom.device_status import DeviceStatusProvider

# 在 __init__ 中的 self.session_manager = ... 之后
self._device_status = DeviceStatusProvider(
    self.preset_manager, self.config, self.session_manager
)
```

## 3. 注意事项

- `StatusResult` 用普通 `@dataclass`（非 frozen），因为需要逐步填充字段
- 保持 `_handle_query_faci_dev_stat` 的 SOAP 日志行不变（行号偏移可接受）
- `build_idle_body` 保留模板字符串格式（`{mfid}`），由 `preset_manager.build_response` 执行替换
- `MODE_TO_FEATURE` 常量放在模块级别，便于测试和扩展

## 4. 验收标准

- [ ] `StatusResult` dataclass 包含所有必需字段
- [ ] `DeviceStatusProvider.get_status()` 返回正确的 idle/busy 状态
- [ ] `DeviceStatusProvider.lookup_mfname()` 正确匹配 preset
- [ ] `MODE_TO_FEATURE` 映射覆盖 fscan/pscan/mscan/sglfreq
- [ ] `_handle_query_faci_dev_stat` ≤30 行
- [ ] 单元测试覆盖 ≥80%
- [ ] 现有 SOAP 接口响应不退化
