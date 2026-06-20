# -*- coding: utf-8 -*-
"""
TCP 透明代理连接处理

来源: rmcp_proxy.py L909-1131 (ProxyConnection 类)
"""

import re
import socket
import sys
import threading
import time
from typing import Optional, Tuple

from .constants import RMCP_FRAME_HEADER_SIZE, MSG_TYPE_REQUEST, FUNCID_TO_NAME
from .frame import RMCPFrame


class ProxyConnection:
    """TCP 透明代理 — 双向转发客户端 ↔ 设备

    基础层: TCP 透传始终执行
    解析层: funcid 提取 + 帧记录 (parse_enabled)
    """

    def __init__(
        self,
        client_socket: socket.socket,
        client_addr: Tuple[str, int],
        logger,
        listen_port: int,
        target_host: str,
        target_port: int,
        parse_enabled: bool = False,
    ):
        self.client_socket = client_socket
        self.client_addr = client_addr
        self.logger = logger
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.parse_enabled = parse_enabled

        self.device_socket: Optional[socket.socket] = None
        self.running = True
        self.close_lock = threading.Lock()
        self.start_time: Optional[float] = None
        self.bytes_sent = 0
        self.bytes_recv = 0

        # funcid 跟踪 (解析层)
        self.last_funcid: Optional[int] = None
        self.last_funcid_name: Optional[str] = None

    # ── 主循环 ────────────────────────────────────────

    def run(self) -> None:
        """运行代理连接"""
        self.start_time = time.time()
        self.logger.log_connection(
            'CONNECT', self.client_addr, (self.target_host, self.target_port)
        )
        print(f"[PROXY] New connection from {self.client_addr} (port={self.listen_port})",
              file=sys.stderr)

        try:
            self.device_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            print(f"[PROXY] Connecting to {self.target_host}:{self.target_port}...",
                  file=sys.stderr)
            self.device_socket.connect((self.target_host, self.target_port))
            self.logger.log_connection(
                'DEVICE_CONNECT', (self.target_host, self.target_port),
                (self.target_host, self.target_port)
            )
            print(f"[PROXY] Connected to {self.target_host}:{self.target_port}",
                  file=sys.stderr)

            t1 = threading.Thread(target=self._forward_client_to_device, daemon=True)
            t2 = threading.Thread(target=self._forward_device_to_client, daemon=True)
            t1.start()
            t2.start()

            while self.running:
                t1.join(timeout=0.5)
                t2.join(timeout=0.5)
                if not t1.is_alive() and not t2.is_alive():
                    break

        except Exception as e:
            print(f"[ERROR] Proxy error: {e}", file=sys.stderr)
            self.logger.log_connection(
                'ERROR', self.client_addr,
                (self.target_host, self.target_port)
            )
        finally:
            self._log_connection_close()
            self.close()

    # ── 客户端 → 设备 ─────────────────────────────────

    def _forward_client_to_device(self) -> None:
        """转发: 客户端 → 设备"""
        # 获取本地引用，避免 close() 并发置 None 导致 TOCTOU
        client_sock = self.client_socket
        device_sock = self.device_socket
        try:
            client_sock.settimeout(2.0)
            while self.running:
                try:
                    data = client_sock.recv(8192)
                    if not data:
                        print("[PROXY] Client disconnected", file=sys.stderr)
                        self.logger.log_connection(
                            'CLIENT_DISCONNECT', self.client_addr,
                            (self.target_host, self.target_port)
                        )
                        self.close()
                        break

                    self.bytes_sent += len(data)
                    if device_sock:
                        try:
                            # 解析层: 提取 funcid (仅 parse_enabled)
                            if self.parse_enabled:
                                self._parse_and_store_funcid(data)
                            # 日志层: 独立于解析层，始终记录帧
                            self.logger.log_frame(
                                'C->S', data, self.client_addr, self.listen_port
                            )
                            device_sock.sendall(data)
                        except Exception as e:
                            print(f"[PROXY] Send to device failed: {e}", file=sys.stderr)
                            self.close()
                            break

                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    print("[PROXY] Client disconnected", file=sys.stderr)
                    self.logger.log_connection(
                        'CLIENT_DISCONNECT', self.client_addr,
                        (self.target_host, self.target_port)
                    )
                    self.close()
                    break
                except Exception as e:
                    print(f"[PROXY] Client recv error: {e}", file=sys.stderr)
                    self.close()
                    break
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            self.running = False

    # ── 设备 → 客户端 ─────────────────────────────────

    def _forward_device_to_client(self) -> None:
        """转发: 设备 → 客户端"""
        # 获取本地引用，避免 close() 并发置 None 导致 TOCTOU
        client_sock = self.client_socket
        device_sock = self.device_socket
        if device_sock is None:
            return
        try:
            device_sock.settimeout(2.0)
            while self.running:
                try:
                    data = device_sock.recv(8192)
                    if not data:
                        print("[PROXY] Device disconnected", file=sys.stderr)
                        self.logger.log_connection(
                            'DEVICE_DISCONNECT', self.client_addr,
                            (self.target_host, self.target_port)
                        )
                        self.close()
                        break

                    self.bytes_recv += len(data)
                    try:
                        client_sock.sendall(data)
                    except Exception as e:
                        print(f"[PROXY] Send to client failed: {e}", file=sys.stderr)
                        self.close()
                        break

                    # 记录帧: 日志层独立于解析层
                    # funcid 关联仅在 parse_enabled 时有意义
                    self.logger.log_frame(
                        'S->C', data,
                        (self.target_host, self.target_port),
                        self.listen_port,
                        related_funcid=self.last_funcid if self.parse_enabled else None,
                        related_funcid_name=self.last_funcid_name if self.parse_enabled else None,
                    )

                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    print("[PROXY] Device disconnected", file=sys.stderr)
                    self.logger.log_connection(
                        'DEVICE_DISCONNECT', self.client_addr,
                        (self.target_host, self.target_port)
                    )
                    self.close()
                    break
                except Exception as e:
                    print(f"[PROXY] Device recv error: {e}", file=sys.stderr)
                    self.close()
                    break
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            self.running = False

    # ── funcid 解析 ───────────────────────────────────

    def _parse_and_store_funcid(self, data: bytes) -> None:
        """从 SOAP 请求帧提取 funcid (用于 RMCP 回调关联)"""
        try:
            if len(data) < RMCP_FRAME_HEADER_SIZE + 10:
                return

            header = RMCPFrame.parse_header(data)
            if not header or header['nMsgType'] != MSG_TYPE_REQUEST:
                return

            xml_data = data[RMCP_FRAME_HEADER_SIZE:]
            xml_start_idx = xml_data.find(b'<?xml')
            if xml_start_idx < 0:
                return

            xml_str = xml_data[xml_start_idx:].decode('gb2312', errors='ignore')
            funcid_match = re.search(r'funcid[=,]?\s*["\']?(\d+)', xml_str)
            if funcid_match:
                fid = int(funcid_match.group(1))
                funcid_name = FUNCID_TO_NAME.get(fid, f'FUNC{fid}')
                self.last_funcid = fid
                self.last_funcid_name = funcid_name
                print(f"[PROXY] Parsed funcid={fid} ({funcid_name})", file=sys.stderr)
        except (ValueError, AttributeError, IndexError):
            # XML 解析失败或 funcid 格式异常 — 非致命，跳过
            pass

    # ── 连接关闭 ──────────────────────────────────────

    def _log_connection_close(self) -> None:
        """记录连接关闭"""
        if self.start_time:
            duration_ms = int((time.time() - self.start_time) * 1000)
            self.logger.log_connection(
                'CLOSE', self.client_addr,
                (self.target_host, self.target_port),
                duration_ms=duration_ms,
                bytes_sent=self.bytes_sent,
                bytes_recv=self.bytes_recv,
            )

    def close(self) -> None:
        """关闭连接（线程安全）"""
        with self.close_lock:
            if not self.running:
                return
            self.running = False

            if self.client_socket:
                try:
                    self.client_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self.client_socket.close()
                except Exception:
                    pass
                self.client_socket = None

            if self.device_socket:
                try:
                    self.device_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self.device_socket.close()
                except Exception:
                    pass
                self.device_socket = None

            print("[PROXY] Connection closed", file=sys.stderr)
