# -*- coding: utf-8 -*-
"""
BusySource 抽象 — 多来源 busy 状态判定

提供统一的 busy 判定接口，支持扩展多种来源：
- SessionBusySource: 封装现有 SessionManager
- ProxyBusySource: 通过共享状态文件读取 rmcp_proxy 的连接状态

使用场景: DeviceStatusProvider.get_status() 遍历 busy_sources 列表判定 idle/busy
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

# ── 模式→feature 映射 ──────────────────────────────────
# 从 device_status.py 导入，保持单一事实来源
from atom.device_status import MODE_TO_FEATURE as _MODE_TO_FEATURE

logger = logging.getLogger(__name__)


# ── 接口 ───────────────────────────────────────────────
# 注：不使用 typing.Protocol（Python 3.7 不支持），
# BusySource 作为鸭子类型基类，子类继承并实现 is_busy() / detail

class BusySource:
    """busy 判定来源基类（鸭子类型）

    所有 busy 来源必须实现 is_busy() 和 detail 属性。
    DeviceStatusProvider 遍历 busy_sources 列表，
    只要任一来源 is_busy() 返回 True 即判定为 busy。
    """

    def is_busy(self) -> bool:
        """返回 True 表示此来源判定为 busy"""
        raise NotImplementedError

    @property
    def detail(self) -> Optional[Dict[str, Any]]:
        """busy 详情（taskid/userid/feature 等），idle 时返回 None"""
        raise NotImplementedError


# ── Session 来源 ───────────────────────────────────────

class SessionBusySource:
    """封装现有 SessionManager 作为 busy 来源

    通过 SessionManager.get_active_sessions() 判定：
    - 有 ACTIVE session → busy
    - 无 ACTIVE session → idle
    """

    def __init__(self, session_manager):
        """初始化 Session 来源

        Args:
            session_manager: SessionManager 实例
        """
        self._session_manager = session_manager

    def is_busy(self) -> bool:
        """返回 True 如果存在 ACTIVE session"""
        active_sessions = self._session_manager.get_active_sessions()
        return len(active_sessions) > 0

    @property
    def detail(self) -> Optional[Dict[str, Any]]:
        """返回第一个 ACTIVE session 的详情，idle 时返回 None"""
        active_sessions = self._session_manager.get_active_sessions()
        if not active_sessions:
            return None

        session = active_sessions[0]
        params = session.fscan_params
        mode = params.get('mode', 'fscan')

        return {
            'source': 'session',
            'taskid': session.taskid,
            'userid': params.get('userid', ''),
            'feature': _MODE_TO_FEATURE.get(mode, ''),
            'appid': params.get('appid', ''),
            'stc': params.get('stc', 0),
        }


# ── Proxy 来源 ─────────────────────────────────────────

class ProxyBusySource:
    """通过共享状态文件读取 rmcp_proxy 的连接状态

    状态文件格式 (proxy_state.json):
    {
      "busy": false,
      "active_connections": 0,
      "connections": [],
      "last_update": "2026-06-21T10:30:00",
      "version": 1
    }

    容错设计：
    - 文件不存在 → 返回 False (proxy 未运行或已正常退出)
    - 文件 JSON 损坏 → 返回 False + 记录 ERROR 日志
    - last_update 超过 staleness_seconds → 返回 False + 记录 WARNING 日志
    - busy: true 且未过期 → 返回 True
    """

    def __init__(self, state_file_path: str, staleness_seconds: float = 30.0):
        """初始化 Proxy 来源

        Args:
            state_file_path: proxy_state.json 的完整路径
            staleness_seconds: 状态文件超过此秒数视为僵死，默认为 30.0 秒
        """
        self._state_file_path = state_file_path
        self._staleness_seconds = staleness_seconds

    def is_busy(self) -> bool:
        """读取 proxy_state.json，判定 proxy 是否有活跃外部连接

        Returns:
            True: 文件存在、busy 字段为 true 且 last_update 未过期
            False: 文件不存在、JSON 损坏、busy=false 或 last_update 过期
        """
        state = self._read_state()
        if state is None:
            return False

        # 检查 busy 字段
        if not state.get('busy', False):
            return False

        # 检查 staleness
        if self._is_stale(state):
            logger.warning(
                "proxy_state.json 超过 %.0f 秒未更新 (last_update=%s)，"
                "视为僵死状态，忽略 busy 判定",
                self._staleness_seconds,
                state.get('last_update', 'unknown')
            )
            return False

        return True

    @property
    def detail(self) -> Optional[Dict[str, Any]]:
        """返回 proxy 连接详情，idle 时返回 None"""
        state = self._read_state()
        if state is None:
            return None

        if not state.get('busy', False):
            return None

        if self._is_stale(state):
            return None

        return {
            'source': 'proxy',
            'active_connections': state.get('active_connections', 0),
            'connections': state.get('connections', []),
        }

    def _read_state(self) -> Optional[Dict[str, Any]]:
        """读取并解析 proxy_state.json

        Returns:
            dict: 解析成功的状态数据
            None: 文件不存在或 JSON 损坏
        """
        if not os.path.exists(self._state_file_path):
            return None

        try:
            with open(self._state_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(
                "无法解析 proxy_state.json: %s (路径: %s)",
                e, self._state_file_path
            )
            return None

    def _is_stale(self, state: Dict[str, Any]) -> bool:
        """检查状态文件是否超过 staleness_seconds

        Args:
            state: 已解析的状态字典

        Returns:
            True: last_update 在文件中不存在、格式错误或超过 staleness_seconds
            False: last_update 在有效期内
        """
        last_update_str = state.get('last_update')
        if not last_update_str:
            logger.warning("proxy_state.json 缺少 last_update 字段")
            return True

        try:
            # 解析 ISO 8601 时间戳
            # StateWriter 使用 datetime.now(timezone.utc).isoformat() 写入
            # 格式示例: "2026-06-21T10:30:00.123456+00:00"
            last_update_dt = datetime.fromisoformat(last_update_str)
            last_update_ts = last_update_dt.timestamp()
            now_ts = time.time()
            return (now_ts - last_update_ts) > self._staleness_seconds

        except (ValueError, TypeError) as e:
            logger.warning(
                "proxy_state.json 的 last_update 解析失败: %s (值: %s)",
                e, last_update_str
            )
            return True
