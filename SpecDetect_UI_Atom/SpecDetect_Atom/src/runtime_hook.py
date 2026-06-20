# -*- coding: utf-8 -*-
"""
Runtime hook: 设置 DLL 搜索路径 + 复制 config 到 exe 同级目录 + 初始化日志
"""
import sys
import os
import shutil
import ctypes

if getattr(sys, 'frozen', False):
    # 方案C: proxy 子进程跳过 Atom Logger 初始化
    # （proxy 使用自己的 CaptureLogger 写 logs/rmcp/）
    _is_proxy_subprocess = os.environ.get('SGATOM_PROXY_MODE') == '1'

    exe_dir = os.path.dirname(os.path.abspath(sys.executable))

    # 将 exe 所在目录添加到 DLL 搜索路径最早位置
    try:
        k32 = ctypes.WinDLL('kernel32')
        AddDllDirectory = getattr(k32, 'AddDllDirectory', None)
        if AddDllDirectory:
            k32.AddDllDirectory(exe_dir)
    except Exception:
        pass

    # onedir 模式: config 直接在 exe 同级目录，不需要复制
    # onefile 模式: config 在 _MEIPASS 中
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        # onefile 模式: config 在 _MEIPASS 中，需要复制出来
        src_config = os.path.join(meipass, 'config')
        dst_config = os.path.join(exe_dir, 'config')

        # 如果目标 config 不存在，复制一份
        if not os.path.exists(dst_config):
            if os.path.exists(src_config):
                shutil.copytree(src_config, dst_config)
    else:
        # onedir 模式: config 已经在 exe 同级目录，不需要复制
        pass

    # 创建 logs 目录（与 config 同级）
    if not _is_proxy_subprocess:
        log_dir = os.path.join(exe_dir, 'logs', 'atom')
        os.makedirs(log_dir, exist_ok=True)

        # 初始化日志（最早捕获启动期异常）
        # 将 _MEIPASS 中的 logger 模块加入路径以便导入
        src_log_module = os.path.join(sys._MEIPASS, 'src', 'log')
        if src_log_module not in sys.path:
            sys.path.insert(0, src_log_module)

        try:
            from log.logger import Logger, LogTag
            log_level = os.environ.get('ATOM_LOG_LEVEL', 'INFO')
            Logger.init(log_dir=log_dir, log_level=log_level)
            logger_instance = Logger.get_instance()
            if logger_instance:
                logger_instance.info("=== SGAtom runtime_hook 启动 ===", tag=LogTag.ATOM)
            else:
                raise Exception("Logger.get_instance() 返回 None")
        except Exception as e:
            # 日志初始化失败，写到 stderr 供排查
            import traceback
            try:
                error_msg = f"[STARTUP ERROR] runtime_hook 日志初始化失败\n"
                error_msg += f"exe_dir: {exe_dir}\n"
                error_msg += f"log_dir: {log_dir}\n"
                error_msg += f"_MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}\n"
                error_msg += f"sys.path[:3]: {sys.path[:3]}\n"
                error_msg += f"Exception: {e}\n"
                error_msg += traceback.format_exc()
                with open(os.path.join(log_dir, 'startup_error.log'), 'a', encoding='utf-8') as f:
                    f.write(error_msg)
            except Exception:
                pass
        # 继续启动，让主程序尝试初始化
