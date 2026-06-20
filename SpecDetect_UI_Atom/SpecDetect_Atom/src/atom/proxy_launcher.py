# -*- coding: utf-8 -*-
"""
RMCP Proxy 子进程启动器
从 main.py 拆出，零副作用，可安全 import 测试。
"""
import glob as _glob
import json
import os
import subprocess
import sys
import time
from typing import Optional


def read_rmcp_proxy_enabled(config_path: str) -> bool:
    """从 settings.json 读取 rmcp_proxy.enabled"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg.get('rmcp_proxy', {}).get('enabled', False)
    except Exception:
        return False


def find_proxy_exe() -> str:
    """查找 proxy 可执行文件

    frozen 模式: 方案C — proxy 与 Atom 同 exe，通过 --proxy-subprocess 入口
    dev 模式: 查找当前目录下的 rmcp_proxy_v*.exe

    Returns:
        可执行文件路径 (frozen 时为 sys.executable)

    Raises:
        FileNotFoundError: 未找到 proxy
    """
    if getattr(sys, 'frozen', False):
        # 方案C: 同 exe 不同入口，直接返回自身
        return sys.executable

    # dev 模式: 查找外部 exe
    search_dir = os.getcwd()
    candidates = sorted(
        _glob.glob(os.path.join(search_dir, 'rmcp_proxy_v*.exe')),
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"未找到 rmcp_proxy_v*.exe (搜索路径: {search_dir})"
        )
    return candidates[0]


def spawn_proxy(config_path: str, proxy_exe: Optional[str] = None) -> Optional[subprocess.Popen]:
    """启动 proxy 子进程

    frozen 模式 (方案C): SGAtom.exe --proxy-subprocess --config <path>
    dev 模式: rmcp_proxy_v*.exe --config <path>

    Args:
        config_path: settings.json 绝对路径
        proxy_exe: 可执行文件路径，None 则自动查找

    Returns:
        Popen 对象，或 None（exe 未找到）

    Raises:
        RuntimeError: proxy 启动后立即退出
    """
    if proxy_exe is None:
        try:
            proxy_exe = find_proxy_exe()
        except FileNotFoundError:
            return None

    # 方案C: 同 exe 不同入口 — 环境变量传递
    if getattr(sys, 'frozen', False):
        proc_env = os.environ.copy()
        proc_env['SGATOM_PROXY_MODE'] = '1'
        proc_env['SGATOM_PROXY_CONFIG'] = config_path
        cmd = [proxy_exe]
    else:
        proc_env = None
        cmd = [proxy_exe, '--config', config_path]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=proc_env,
    )

    # 短暂等待，检测立即崩溃
    time.sleep(0.5)
    if proc.poll() is not None:
        raise RuntimeError(
            f"RMCP 代理启动失败 (exit code={proc.returncode})"
        )

    return proc


def stop_proxy(proc: Optional[subprocess.Popen]) -> None:
    """安全停止 rmcp_proxy 子进程

    Args:
        proc: Popen 对象或 None
    """
    if proc is None:
        return
    if proc.poll() is not None:
        return  # 已退出

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
