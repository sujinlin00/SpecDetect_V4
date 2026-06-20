# -*- coding: utf-8 -*-
"""
Proxy 配置加载 — 从共享 settings.json 读取 rmcp_proxy 段

替代旧的 rmcp_proxy/config.py 和 DEFAULT_CONFIG 字符串常量。
"""

import json
import os
from typing import Dict, Any


# ── 默认值 ────────────────────────────────────────────

DEFAULTS: Dict[str, Any] = {
    'listen': {
        'host': '0.0.0.0',
        'port_1': 9999,
        'port_2': 8888,
    },
    'target': {
        'host': '127.0.0.1',
        'port': 19999,
    },
    'parse': {
        'enabled': False,
    },
    'log': {
        'dir': 'logs/rmcp',
        'text_enabled': False,
        'raw_enabled': False,
        'json_enabled': False,
        'csv_enabled': False,
        'per_interface_enabled': False,
    },
}


# ── 深度合并 ──────────────────────────────────────────

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并两个字典，override 优先级更高"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ── 公共 API ──────────────────────────────────────────

def load_proxy_config(config_path: str) -> Dict[str, Any]:
    """从共享 settings.json 加载 rmcp_proxy 配置段

    Args:
        config_path: settings.json 的绝对路径

    Returns:
        合并了默认值的配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, 'r', encoding='utf-8-sig') as f:
        full_config = json.load(f)

    proxy_cfg = full_config.get('rmcp_proxy', {})
    return _deep_merge(DEFAULTS, proxy_cfg)
