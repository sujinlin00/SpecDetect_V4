# -*- coding: utf-8 -*-
"""
RMCP 协议常量与映射表

来源: rmcp_proxy.py (POC), 实测校正
"""

# ── 帧头常量 ──────────────────────────────────────────

RMCP_FRAME_HEADER_SIZE = 18

# ── 消息类型 ──────────────────────────────────────────

MSG_TYPE_REQUEST = 90     # 0x5A — 设备控制请求
MSG_TYPE_RESPONSE = 6     # 响应消息
MSG_TYPE_DATA_1 = 29      # 0x1D — 数据帧类型1
MSG_TYPE_DATA_2 = 95      # 0x5F — 数据帧类型2

# ── SOAP 接口映射 (funcid → SOAP 接口名) ─────────────

FUNCID_TO_NAME: dict = {
    11: 'B_SglFreqMeas',
    12: 'B_FScan',
    14: 'B_MScan',
    15: 'B_FScan',
    16: 'B_PScan',
}

# ── RMCP 回调映射 (nBdType → RMCP 回调类型名) ─────────

NBDTYPE_TO_NAME: dict = {
    0x0B: 'IFANALYSIS',
    0x0E: 'SGLFREQ',
    0x0F: 'FSCAN',
    0x10: 'DSCAN',
    0x01: 'PSCAN',
}
