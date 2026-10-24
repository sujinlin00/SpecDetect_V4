# -*- coding: utf-8 -*-
"""
TCP 连接生命周期基类

统一 socket 的 connect / disconnect / is_connected 模式，
消除 RMCPClient 和 ProxyConnection 中重复的 socket 管理模式。

使用示例:
    handle = ConnectionHandle("127.0.0.1", 1449, timeout=10.0)
    if handle.connect():
        handle.send(data)
        response = handle.recv(4096)
    handle.disconnect()
"""

import socket
import threading
from typing import Optional


class ConnectionHandle:
    """TCP 连接生命周期管理基类

    封装:
    - connect(): 建立 TCP 连接
    - disconnect(): 安全断开（幂等，线程安全）
    - is_connected(): 检查连接状态
    - send(data): 发送数据
    - recv(bufsize): 接收数据

    线程安全:
    - connect() / disconnect() / sock 属性使用 _lock 保护 _sock 的创建和销毁。
    - send() / recv() / is_connected() 不持锁（避免 I/O 阻塞其他操作），
      通过 CPython GIL + 异常处理保证安全性：TOCTOU 竞态下 socket 被关闭
      导致的异常由 except 捕获，返回值语义正确。
    """

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        """初始化连接句柄

        Args:
            host: 目标主机
            port: 目标端口
            timeout: 操作超时（秒）
        """
        self.host = host
        self.port = port
        self.timeout = timeout

        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._closed = False

    def connect(self, connect_timeout: Optional[float] = None) -> bool:
        """建立 TCP 连接

        关键设计：TCP connect() 在锁外执行，避免 DNS 解析 / SYN 超时
        （可达 10s+）阻塞 disconnect() 等其他操作。

        Args:
            connect_timeout: 连接超时，默认使用 self.timeout

        Returns:
            True 连接成功，False 连接失败
        """
        ct = connect_timeout if connect_timeout is not None else self.timeout

        # 快速检查：锁内只做状态判断
        with self._lock:
            if self._sock:
                return True
            if self._closed:
                return False

        # I/O 在锁外执行，避免长时间阻塞
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(ct)
            sock.connect((self.host, self.port))
            sock.settimeout(self.timeout)
        except Exception:
            return False

        # 原子赋值：锁内检查 close() 是否在 connect 期间被调用
        with self._lock:
            if self._closed:
                # 已被 close()，丢弃刚建立的连接
                try:
                    sock.close()
                except Exception:
                    pass
                return False
            self._sock = sock
            return True

    def disconnect(self) -> None:
        """断开连接（幂等，线程安全）

        可安全重复调用。断开后 _sock 置为 None。
        """
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def is_connected(self) -> bool:
        """检查连接是否存活

        不持锁（避免 I/O 阻塞），通过 getpeername() 异常处理保证安全。

        Returns:
            True 连接存活，False 未连接/已断开
        """
        if self._sock is None:
            return False
        try:
            self._sock.getpeername()
            return True
        except Exception:
            return False

    def send(self, data: bytes) -> bool:
        """发送数据

        不持锁。TOCTOU 竞态下 disconnect() 关闭 socket 导致的异常由 except 捕获。

        Args:
            data: 待发送的字节数据

        Returns:
            True 发送成功，False 发送失败
        """
        if not self._sock:
            return False
        try:
            self._sock.sendall(data)
            return True
        except Exception:
            return False

    def recv(self, bufsize: int = 4096) -> Optional[bytes]:
        """接收数据

        不持锁。返回值语义:
        - None:  未连接 或 对端关闭 或 socket 错误
        - b'':   超时（暂无数据，连接仍存活）
        - bytes: 接收到的数据

        Args:
            bufsize: 接收缓冲区大小

        Returns:
            接收到的字节数据，或 None/b''（见上）
        """
        if not self._sock:
            return None
        try:
            data = self._sock.recv(bufsize)
            return data if data else None
        except socket.timeout:
            return b''
        except Exception:
            return None

    @property
    def sock(self) -> Optional[socket.socket]:
        """获取原始 socket 引用（只读，用于高级操作）

        注意: 返回的引用可能在使用前被 disconnect() 关闭。
        调用者应使用局部变量保存引用以避免 TOCTOU 竞态。
        """
        with self._lock:
            return self._sock

    def close(self) -> None:
        """关闭连接句柄（不可逆）

        与 disconnect() 的区别: close() 设置 _closed=True，
        阻止后续 connect() 重新连接。
        """
        with self._lock:
            self._closed = True
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
