# -*- coding: utf-8 -*-
"""设备状态提供者 — B_QueryFaciDevStat 处理器"""

import re
from dataclasses import dataclass
from typing import Dict, Optional


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


# ── 模式→feature 映射 ──────────────────────────────────

MODE_TO_FEATURE = {
    'fscan': 'B_FScan',
    'pscan': 'B_PScan',
    'mscan': 'B_MScan',
    'sglfreq': 'B_SglFreqMeas',
}


# ── 提供者 ─────────────────────────────────────────────

class DeviceStatusProvider:
    """设备状态提供者

    职责：
    1. 从 SOAP body 提取 mfid/equid/userid
    2. 从 devinfo XML 提取 equname
    3. 从 presets 查找 mfname
    4. 判定 idle/busy 并收集 busy 字段
    5. 构建 idle 响应体
    """

    def __init__(self, preset_manager, config, session_manager):
        self._preset_manager = preset_manager
        self._config = config
        self._session_manager = session_manager

    def extract_request_ids(self, raw_body: str) -> Dict[str, str]:
        """从 SOAP body 提取 mfid/equid/userid"""
        return {
            'mfid': self._regex_extract(raw_body, r'<[^>]*:mfid[^>]*>([^<]+)</[^>]*:mfid>'),
            'equid': self._regex_extract(raw_body, r'<[^>]*:equid[^>]*>([^<]+)</[^>]*:equid>'),
            'userid': self._regex_extract(raw_body, r'<[^>]*:userid[^>]*>([^<]+)</[^>]*:userid>'),
        }

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
        # Fallback: 第一个 preset
        presets = self._config.rmcp_presets
        if presets:
            return presets[0].get('station', {}).get('name', 'Unknown')
        return 'Unknown'

    def get_status(self, mfid: str, equid: str, userid: str) -> StatusResult:
        """查询设备状态（主入口）

        Returns:
            StatusResult: 包含完整状态信息
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
        """构建 idle 状态的 responsebody XML 模板"""
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
