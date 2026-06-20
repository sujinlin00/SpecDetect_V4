# -*- coding: utf-8 -*-
"""
rmcp_proxy 入口脚本 — 供 PyInstaller 使用

解决 PyInstaller 冻结后 __main__.py 相对导入失效的问题。
"""
from proxy.__main__ import main

if __name__ == '__main__':
    main()
