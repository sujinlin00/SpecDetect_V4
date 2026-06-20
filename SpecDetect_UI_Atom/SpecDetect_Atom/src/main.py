# -*- coding: utf-8 -*-
"""
SGAtom (SpecGuardAtom) 服务入口

用法:
    python main.py
    python main.py --config config/settings.json
"""

import sys
import os
import signal
import argparse
import ctypes

# 添加 src 目录到路径
_src_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _src_dir)
# 添加项目根目录到路径（供 proxy 包导入）
_project_root = os.path.dirname(_src_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ── 方案C: 同 exe 不同入口 ──────────────────────────
# 必须在所有 Logger.init / 重导入之前检查，避免 proxy 子进程
# 执行不必要的 Atom 模块级初始化。
# 方案C: 同 exe 不同入口 — 环境变量控制
# SGAtom 子进程 spawn proxy 时设置 SGATOM_PROXY_MODE=1
if __name__ == '__main__' and os.environ.get('SGATOM_PROXY_MODE') == '1':
    config_path = os.environ.get('SGATOM_PROXY_CONFIG')
    if config_path:
        try:
            from proxy.__main__ import start_proxy
            start_proxy(config_path)
        except Exception as _e:
            import traceback
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
    else:
        print("[ERROR] SGATOM_PROXY_MODE requires SGATOM_PROXY_CONFIG", file=sys.stderr)
        sys.exit(1)


def _show_error_and_exit(title: str, message: str, exit_code: int = 1):
    """显示错误对话框，按任意键后退出"""
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        print(f'\n{title}\n{message}', file=sys.stderr)
        input('\n按任意键退出...')
    sys.exit(exit_code)


_STD_OUT = -11
_RED = 12
_GREEN = 10
_GRAY = 7


def _console_color(color: int) -> None:
    """设置控制台文字颜色（Windows API）"""
    try:
        handle = ctypes.windll.kernel32.GetStdHandle(_STD_OUT)
        ctypes.windll.kernel32.SetConsoleTextAttribute(handle, color)
    except Exception:
        pass


def _print_red(msg: str) -> None:
    _console_color(_RED)
    print(msg)
    _console_color(_GRAY)

# 初始化日志（最早，避免后续 import 时日志未初始化）
if getattr(sys, 'frozen', False):
    # exe 模式：日志在 exe 同级 logs/atom 目录
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    log_dir = os.path.join(exe_dir, 'logs', 'atom')
    os.makedirs(log_dir, exist_ok=True)
    log_level = os.environ.get('ATOM_LOG_LEVEL', 'INFO')
else:
    # 开发模式：日志在 ./logs/atom
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base_dir, 'logs', 'atom')
    os.makedirs(log_dir, exist_ok=True)
    log_level = 'DEBUG'

from log.logger import Logger, info, error, LogTag
Logger.init(log_dir=log_dir, log_level=log_level)

# 导入服务（在日志初始化之后）
from atom.service import AtomService
from license.manager import verify_license, verify_license_data, activate_with_code


def _verify_license(license_dir: str) -> bool:
    """许可证验证：frozen 模式优先用嵌入式数据，回退到外部文件"""
    if getattr(sys, 'frozen', False):
        try:
            from license._data import LICENSE_DATA
            return verify_license_data(LICENSE_DATA)
        except ImportError:
            pass

    license_path = os.path.join(license_dir, 'license.dat')
    return verify_license(license_path)


def main():
    parser = argparse.ArgumentParser(description='SpecDetect_Atom 服务')
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='配置文件路径'
    )
    parser.add_argument(
        '--activate',
        type=str,
        default=None,
        metavar='AUTH_CODE',
        help='输入授权码激活设备（格式: XXXX-XXXX-XXXX-XXXX-XXXX）'
    )
    args = parser.parse_args()

    # 激活模式（命令行脚本）
    if args.activate:
        print("正在验证授权码...")
        success, msg = activate_with_code(args.activate)
        if success:
            print(msg)
            print("请重新启动 SGAtom 服务。")
            sys.exit(0)
        else:
            _print_red(f"\n  {msg}")
            print()
            input("  按任意键退出...")
            sys.exit(1)

    # 确定配置文件路径
    config_file = args.config
    if config_file is None:
        if getattr(sys, 'frozen', False):
            # exe 模式
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            exe_config = os.path.join(exe_dir, 'config', 'settings.json')
            if os.path.exists(exe_config):
                config_file = exe_config
            else:
                # 查找当前工作目录的 config
                cwd_config = os.path.join(os.getcwd(), 'config', 'settings.json')
                if os.path.exists(cwd_config):
                    config_file = cwd_config
                else:
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    config_file = os.path.join(base_dir, 'config', 'settings.json')
        else:
            # 开发模式
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_file = os.path.join(base_dir, 'config', 'settings.json')

    # 许可证验证
    license_dir = os.path.dirname(os.path.abspath(config_file))
    if not _verify_license(license_dir):
        print("\n" + "=" * 46)
        print("  设备未授权，请输入授权码激活")
        print("=" * 46)
        print()
        code = input("  授权码 (直接回车退出): ").strip()
        if not code:
            sys.exit(1)
        success, msg = activate_with_code(code)
        if success:
            print(f"\n  {msg}")
            print("  正在启动服务...\n")
        else:
            _print_red(f"\n  {msg}")
            print()
            input("  按任意键退出...")
            sys.exit(1)

    # ── 启动 RMCP Proxy 子进程 ──────────────────────────
    from atom.proxy_launcher import (
        read_rmcp_proxy_enabled, spawn_proxy, stop_proxy,
    )
    proxy_proc = None
    if read_rmcp_proxy_enabled(config_file):
        try:
            proxy_proc = spawn_proxy(config_file)
        except Exception as e:
            error(f"RMCP 代理启动失败: {e}", LogTag.ATOM)
        else:
            if proxy_proc is not None:
                info(f"RMCP 代理已启动 (pid={proxy_proc.pid})", LogTag.ATOM)
            else:
                info("rmcp_proxy.exe 未找到，跳过代理启动", LogTag.ATOM)

    # 创建服务
    service = AtomService(config_file)

    # 信号处理
    def signal_handler(signum, frame):
        info(f"收到信号 {signum}，停止服务...", LogTag.ATOM)
        stop_proxy(proxy_proc)
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动服务
    try:
        service.start()
        info("Atom 服务运行中，按 Ctrl+C 停止", LogTag.ATOM)

        # 等待
        while True:
            import time
            time.sleep(1)

    except KeyboardInterrupt:
        info("收到键盘中断", LogTag.ATOM)
    except Exception as e:
        error(f"服务异常: {e}", LogTag.ATOM)
    finally:
        stop_proxy(proxy_proc)
        service.stop()


if __name__ == '__main__':
    main()
