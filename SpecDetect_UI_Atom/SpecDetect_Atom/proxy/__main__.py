#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rmcp_proxy 入口 — 透明代理服务

支持:
  python -m proxy --config path/to/settings.json
  rmcp_proxy.exe --config path/to/settings.json
"""

import argparse
import os
import socket
import sys
import threading
import time
from typing import Dict, Any

from .config import load_proxy_config
from .logger import CaptureLogger
from .connection import ProxyConnection
from .state_writer import StateWriter

# 版本号: 从 workspace 根 get_version.py 读取（与 Atom 共用版本源）
try:
    # 尝试从 get_version.py 读取（开发模式）
    _ws_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    sys.path.insert(0, _ws_root)
    from get_version import RMCP_PROXY_VERSION
    __version__ = str(RMCP_PROXY_VERSION)
except ImportError:
    __version__ = "1.0.14"


# ── 父进程存活检测 (Windows) ─────────────────────────

_parent_alive_ctypes_failures: int = 0
_PARENT_ALIVE_MAX_CTYPES_FAILURES: int = 30
_parent_alive_warned: bool = False


def _parent_alive() -> bool:
    """检测父进程是否存活 (Windows only)

    Windows 上通过 Win32 WaitForSingleObject 做原子检测。
    ctypes 持续异常时降级到 os.getppid() 防止孤儿进程永久残留。
    """
    global _parent_alive_ctypes_failures, _parent_alive_warned

    if os.name != 'nt':
        return True

    parent_pid = os.getppid()
    if parent_pid == 1:
        return False

    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
        if not handle:
            return False

        ret = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
        ctypes.windll.kernel32.CloseHandle(handle)

        _parent_alive_ctypes_failures = 0
        _parent_alive_warned = False
        return ret != 0  # WAIT_TIMEOUT=258 → alive; WAIT_OBJECT_0=0 → dead

    except Exception:
        _parent_alive_ctypes_failures += 1

        if _parent_alive_ctypes_failures >= _PARENT_ALIVE_MAX_CTYPES_FAILURES:
            if not _parent_alive_warned:
                print(
                    f"[PROXY] ctypes parent-alive check failed "
                    f"{_parent_alive_ctypes_failures} times consecutively; "
                    f"falling back to os.getppid()",
                    file=sys.stderr,
                )
                _parent_alive_warned = True
            return os.getppid() != 1

        return True


# ── 主服务 ────────────────────────────────────────────

def start_proxy(config_path: str) -> None:
    """启动透明代理服务

    Args:
        config_path: settings.json 绝对路径
    """
    cfg = load_proxy_config(config_path)

    listen_host = cfg['listen']['host']
    ports = [cfg['listen']['port_1']]
    if cfg['listen'].get('port_2'):
        ports.append(cfg['listen']['port_2'])

    target_host = cfg['target']['host']
    target_port = cfg['target']['port']

    parse_enabled = cfg['parse']['enabled']
    log_cfg = cfg['log']
    log_dir = log_cfg['dir']

    # 确保日志目录为绝对路径
    if not os.path.isabs(log_dir):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) \
            else os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(exe_dir, log_dir)

    # 初始化状态文件写入器（用于 BusySource IPC）
    state_file_path = os.path.join(log_dir, 'proxy_state.json')
    state_writer = StateWriter(state_file_path)

    print("=" * 60, file=sys.stderr)
    print(f"RMCP TCP Proxy v{__version__}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Listen:  {listen_host}:{', '.join(str(p) for p in ports)}", file=sys.stderr)
    print(f"Target:  {target_host}:{target_port}", file=sys.stderr)
    print(f"Log dir: {log_dir}", file=sys.stderr)
    print(f"Parse:   {'ON' if parse_enabled else 'OFF'}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("", file=sys.stderr)

    # 为每个端口创建独立 logger 和 server socket
    port_loggers: Dict[int, CaptureLogger] = {}
    servers = []

    for port in ports:
        port_loggers[port] = CaptureLogger(
            log_dir=log_dir,
            port=port,
            text_enabled=log_cfg.get('text_enabled', False),
            raw_enabled=log_cfg.get('raw_enabled', False),
            json_enabled=log_cfg.get('json_enabled', False),
            csv_enabled=log_cfg.get('csv_enabled', False),
            per_interface_enabled=log_cfg.get('per_interface_enabled', False),
        )
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((listen_host, port))
        server.listen(5)
        server.settimeout(1.0)  # 允许 Ctrl+C 打断 accept()
        servers.append(server)
        print(f"[PROXY] Listening on {listen_host}:{port}", file=sys.stderr)

    def accept_connections(srv: socket.socket, port: int) -> None:
        """独立线程: 接受单个端口的连接"""
        logger = port_loggers[port]
        while True:
            try:
                client_socket, client_addr = srv.accept()
                handler = ProxyConnection(
                    client_socket, client_addr, logger, port,
                    target_host=target_host,
                    target_port=target_port,
                    parse_enabled=parse_enabled,
                    state_writer=state_writer,
                )
                t = threading.Thread(target=handler.run, daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                import traceback
                port_info = srv.getsockname()[1] if srv.fileno() >= 0 else 'unknown'
                print(f"[PROXY] Accept error on port {port_info}: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                break

    # 为每个端口创建独立 accept 线程
    accept_threads = []
    for srv, port in zip(servers, ports):
        t = threading.Thread(target=accept_connections, args=(srv, port), daemon=True)
        t.start()
        accept_threads.append(t)

    try:
        while True:
            time.sleep(1)
            if os.name == 'nt' and not _parent_alive():
                print("[PROXY] Parent process died, exiting...", file=sys.stderr)
                break
            # 检测 accept 线程健康状态
            dead_count = sum(1 for t in accept_threads if not t.is_alive())
            if dead_count > 0:
                print(
                    f"[PROXY] FATAL: {dead_count}/{len(accept_threads)} "
                    f"accept thread(s) died, exiting...",
                    file=sys.stderr,
                )
                sys.exit(1)
    except KeyboardInterrupt:
        print("\n[PROXY] Shutting down...", file=sys.stderr)
    finally:
        # 清理状态文件（正常退出）
        state_writer.shutdown()

        for srv in servers:
            try:
                srv.close()
            except Exception:
                pass
        for logger in port_loggers.values():
            logger.close()


# ── CLI ───────────────────────────────────────────────

def main() -> None:
    """CLI 入口"""
    parser = argparse.ArgumentParser(
        description='RMCP TCP Proxy — 透明代理服务',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m proxy --config config/settings.json
  rmcp_proxy.exe --config config/settings.json
        """,
    )
    parser.add_argument(
        '--config',
        help='settings.json 配置文件路径',
        default=None,
    )
    parser.add_argument(
        '--version', '-V',
        action='store_true',
        help='显示版本号',
    )
    args = parser.parse_args()

    if args.version:
        print(f'rmcp_proxy v{__version__}')
        return

    # 确定配置文件路径
    if args.config:
        config_path = args.config
    else:
        # 默认: 与 exe 同目录的 config/settings.json
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            exe_dir = os.getcwd()
        config_path = os.path.join(exe_dir, 'config', 'settings.json')

    if not os.path.exists(config_path):
        print(f"[ERROR] 配置文件不存在: {config_path}", file=sys.stderr)
        print(f"[ERROR] 请使用 --config 指定路径", file=sys.stderr)
        sys.exit(1)

    start_proxy(config_path)


if __name__ == '__main__':
    main()
