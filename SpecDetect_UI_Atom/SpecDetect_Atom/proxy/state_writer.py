# -*- coding: utf-8 -*-
"""
状态文件写入器 — rmcp_proxy 端 busy 状态持久化

通过原子写入将 proxy 的连接状态同步到共享文件 (proxy_state.json)，
供 Atom 端的 ProxyBusySource 读取。

线程安全：使用 threading.Lock 保护并发写入。
原子写入：写临时文件 → os.replace，适应 Windows 环境。
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


class StateWriter:
    """proxy 端状态文件写入器

    负责维护 proxy_state.json 的写入，在连接建立/关闭时更新状态。

    使用方式:
        state_writer = StateWriter("logs/proxy_state.json")
        # 连接建立时
        state_writer.connection_opened(client_addr, target_addr)
        # 连接关闭时
        state_writer.connection_closed(client_addr)
        # 正常退出时
        state_writer.shutdown()
    """

    def __init__(self, state_file_path: str):
        """初始化状态写入器

        创建/覆盖初始状态文件 (busy: False)，初始化线程锁。

        Args:
            state_file_path: proxy_state.json 的完整路径
        """
        self._state_file_path = state_file_path
        self._lock = threading.Lock()

        # 确保目录存在
        state_dir = os.path.dirname(state_file_path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

        # 缓存最近一次写入的状态，用于 connection_closed 读取当前值
        self._cached_connections: List[Dict[str, str]] = []
        self._cached_active_count: int = 0

        self._write_initial_state()

    # ── 公开接口 ────────────────────────────────────────

    def connection_opened(
        self,
        client_addr: Tuple[str, int],
        target_addr: Tuple[str, int]
    ) -> None:
        """记录新连接建立

        递增 active_connections，设置 busy=True，追加连接条目。

        Args:
            client_addr: (host, port) 客户端地址
            target_addr: (host, port) 目标设备地址
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            self._cached_active_count += 1
            self._cached_connections.append({
                'client': f"{client_addr[0]}:{client_addr[1]}",
                'target': f"{target_addr[0]}:{target_addr[1]}",
                'opened_at': now_iso,
            })

            state = self._build_state(
                busy=True,
                active_connections=self._cached_active_count,
                connections=self._cached_connections,
            )
            self._write_atomic(state)

    def connection_closed(self, client_addr: Tuple[str, int]) -> None:
        """记录连接关闭

        递减 active_connections，移除匹配的连接条目，
        当 active_connections 归零时设置 busy=False。

        Args:
            client_addr: (host, port) 客户端地址
        """
        client_str = f"{client_addr[0]}:{client_addr[1]}"

        with self._lock:
            self._cached_active_count = max(0, self._cached_active_count - 1)

            # 移除匹配的连接条目（按客户端地址匹配）
            self._cached_connections = [
                c for c in self._cached_connections
                if c.get('client') != client_str
            ]

            busy = self._cached_active_count > 0
            state = self._build_state(
                busy=busy,
                active_connections=self._cached_active_count,
                connections=self._cached_connections,
            )
            self._write_atomic(state)

    def shutdown(self) -> None:
        """正常退出清理：删除状态文件

        在 proxy 正常退出时调用，避免 Atom 读到僵尸状态。
        异常崩溃时不清除文件，由 ProxyBusySource 的 staleness 检测兜底。
        """
        with self._lock:
            try:
                if os.path.exists(self._state_file_path):
                    os.remove(self._state_file_path)
            except OSError:
                pass

    # ── 内部方法 ────────────────────────────────────────

    def _write_initial_state(self) -> None:
        """写入初始状态 (busy: False)"""
        initial = self._build_state(
            busy=False,
            active_connections=0,
            connections=[],
        )
        self._write_atomic(initial)
        self._cached_connections = []
        self._cached_active_count = 0

    def _build_state(
        self,
        busy: bool,
        active_connections: int,
        connections: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """构建完整的状态 JSON 字典

        Args:
            busy: 是否有活跃连接
            active_connections: 活跃连接数
            connections: 连接详情列表

        Returns:
            包含所有状态字段的字典
        """
        return {
            'busy': busy,
            'active_connections': active_connections,
            'connections': connections,
            'last_update': datetime.now(timezone.utc).isoformat(),
            'version': 1,
        }

    def _write_atomic(self, data: Dict[str, Any]) -> None:
        """原子写入 JSON 到状态文件

        先写入临时文件，再通过 os.replace 原子替换。
        os.replace 在 Windows 上也是原子操作，确保读者读到完整的 JSON。

        Args:
            data: 待写入的状态字典
        """
        temp_path = self._state_file_path + '.tmp'
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self._state_file_path)
        except OSError as e:
            print(f"[STATE_WRITER] 写入状态文件失败: {e}", file=sys.stderr)
            # 写入失败时尝试清理临时文件
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
