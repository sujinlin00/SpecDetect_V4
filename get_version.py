# -*- coding: utf-8 -*-
"""
版本号统一管理 — 唯一版本源

所有版本号只在这里定义。其他文件通过以下方式读取：
  - Python:  sys.path.insert(0, <workspace_root>); from get_version import ATOM_VERSION
  - Spec:    sys.path / regex 读取本文件
  - Batch:   python get_version.py <output_dir> → 生成 _version.env
"""

ATOM_VERSION = "1.7.6"
PROXY_VERSION = "1.2.11"
RMCP_PROXY_VERSION = "1.0.12"

__all__ = ['ATOM_VERSION', 'PROXY_VERSION', 'RMCP_PROXY_VERSION']


def write_env(output_dir: str):
    """生成 _version.env 供 batch 脚本使用"""
    import os
    env_path = os.path.join(output_dir, '_version.env')
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(f'ATOM_VERSION={ATOM_VERSION}\n')
        f.write(f'PROXY_VERSION={PROXY_VERSION}\n')
        f.write(f'RMCP_PROXY_VERSION={RMCP_PROXY_VERSION}\n')


if __name__ == '__main__':
    import sys
    output_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    # 处理 Windows batch 传参时可能带上的尾部反斜杠或引号
    output_dir = output_dir.strip('"').rstrip('\\/')
    write_env(output_dir)
    print(f"ATOM_VERSION={ATOM_VERSION}")
    print(f"PROXY_VERSION={PROXY_VERSION}")
    print(f"RMCP_PROXY_VERSION={RMCP_PROXY_VERSION}")
