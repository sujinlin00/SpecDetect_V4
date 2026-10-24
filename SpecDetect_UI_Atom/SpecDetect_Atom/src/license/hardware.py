# -*- coding: utf-8 -*-
"""硬件指纹采集 — 主板、硬盘、CPU、MAC 地址、系统卷序列号

Windows 7 兼容性（现场实测，PS 2.0 / WMIC 齐全）:
- Win7 没有 Get-CimInstance / Get-Partition / Get-Disk（PS3+ 才有），
  采集只依赖 WMIC 与 Get-WmiObject，不使用 Storage 模块
- Win7 上 PowerShell 冷启动实测约 22 秒，PS 回退的超时必须远大于 10 秒
- 部分系统上 WMIC 输出为 UTF-16LE（字符之间夹 NUL/空格），取值必须去空白
- WMIC 的 where 子句必须拆成独立 argv，否则报 "Alias not found"
"""

import ctypes
import locale
import logging
import os
import re
import subprocess
import uuid
from typing import Dict, List, Optional

_logger = logging.getLogger(__name__)

_CACHE: Dict[str, Optional[str]] = {}
_CACHE_MACS: Optional[List[str]] = None

_SAFE_ID = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_WMIC_TIMEOUT = 15
# Win7 实测 PowerShell 冷启动 ~22s，10s 超时会稳定砍掉 PS 回退
_PS_TIMEOUT = 90
_FLAGS = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
_WHITESPACE = re.compile(r'\s+')


def _decode(raw: bytes) -> str:
    """解码子进程输出 — WMIC 可能是 UTF-16LE（含 NUL），也可能是 ANSI"""
    if b'\x00' in raw:
        try:
            return raw.decode('utf-16-le')
        except UnicodeDecodeError:
            pass
    for enc in (locale.getpreferredencoding(), 'mbcs', 'utf-8'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('latin-1', errors='ignore')


def _clean(text: str, header: str = '') -> Optional[str]:
    """从命令输出中取第一行有效值：去空白、跳过表头

    去空白同时解决 WMIC UTF-16LE 输出（"S e r i a l N u m b e r"）的问题
    """
    for line in text.splitlines():
        value = _WHITESPACE.sub('', line)
        if not value or value.lower() == header.lower():
            continue
        return value
    return None


def _run_wmic(cls: str, prop: str, where: str = '') -> Optional[str]:
    """WMIC 查询 — where 子句作为独立 argv 传入"""
    cmd = ['wmic', cls]
    if where:
        cmd += ['where', where]
    cmd += ['get', prop]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, timeout=_WMIC_TIMEOUT,
            creationflags=_FLAGS
        )
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return None
    return _clean(_decode(result.stdout), prop)


def _run_powershell(cls: str, prop: str) -> Optional[str]:
    """PowerShell 回退 — Win7 PS 2.0 可用，但冷启动慢，超时放宽到 90s"""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', f'(Get-WmiObject Win32_{cls}).{prop}'],
            capture_output=True, timeout=_PS_TIMEOUT,
            creationflags=_FLAGS
        )
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return None
    return _clean(_decode(result.stdout), prop)


def _query(cls: str, prop: str, where: str = '') -> Optional[str]:
    """先 WMIC（快），失败再 PowerShell（慢但兼容），都失败返回 None"""
    if not _SAFE_ID.match(cls) or not _SAFE_ID.match(prop):
        raise ValueError(f"Invalid hardware identifier: {cls}.{prop}")

    for attempt in (
        _run_wmic(cls, prop, where),
        _run_powershell(cls, prop),
    ):
        if attempt:
            return attempt
    return None


def get_motherboard_serial() -> Optional[str]:
    """获取主板序列号"""
    if 'mb' not in _CACHE:
        _CACHE['mb'] = _query('baseboard', 'serialnumber')
        if _CACHE['mb'] is None:
            _logger.warning('无法获取主板序列号')
    return _CACHE['mb']


def get_disk_serial() -> Optional[str]:
    """获取物理磁盘序列号（Index=0，即系统盘所在盘的枚举首项）

    WMIC 必须把 where 拆成独立参数：
        wmic diskdrive where Index=0 get serialnumber
    之前写成单 token（'diskdrive where Index=0'）会返回 "Alias not found"。
    """
    if 'disk' not in _CACHE:
        serial = _run_wmic('diskdrive', 'serialnumber', where='Index=0')
        if not serial:
            # 退化：取任意一块有序列号的物理盘
            serial = _run_wmic('diskdrive', 'serialnumber')
        if not serial:
            serial = _run_powershell('diskdrive', 'serialnumber')
        _CACHE['disk'] = serial
        if _CACHE['disk'] is None:
            _logger.warning('无法获取系统盘序列号')
    return _CACHE['disk']


def get_cpu_id() -> Optional[str]:
    """获取 CPU 序列号"""
    if 'cpu' not in _CACHE:
        _CACHE['cpu'] = _query('cpu', 'processorid')
        if _CACHE['cpu'] is None:
            _logger.warning('无法获取 CPU 序列号')
    return _CACHE['cpu']


def get_volume_serial() -> Optional[str]:
    """获取系统盘卷序列号（NTFS Volume Serial）

    走 kernel32.GetVolumeInformationW，不依赖 WMI/WMIC，几乎零开销，
    即使所有 WMI 查询都失败也能提供一个稳定的硬件标识。
    """
    if 'volume' not in _CACHE:
        serial = None
        try:
            drive = os.environ.get('SystemDrive', 'C:').rstrip('\\')
            root = drive + '\\'
            serial_no = ctypes.c_ulong(0)
            name_buf = ctypes.create_unicode_buffer(261)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root),
                name_buf, 261,
                ctypes.byref(serial_no),
                None, None, None, 0,
            )
            if ok:
                serial = '%08X' % serial_no.value
        except Exception as exc:  # noqa: BLE001 — 指纹采集不允许因单项失败中断
            _logger.warning('获取卷序列号异常: %s', exc)
        _CACHE['volume'] = serial
        if serial is None:
            _logger.warning('无法获取系统盘卷序列号')
    return _CACHE['volume']


def get_mac_list() -> List[str]:
    """获取所有物理网卡 MAC 地址（去除分隔符，大写）

    VM 注意：无物理网卡时 uuid.getnode() 可能返回 0，会被过滤。
    """
    global _CACHE_MACS
    if _CACHE_MACS is not None:
        return _CACHE_MACS

    macs: List[str] = []
    try:
        result = subprocess.run(
            ['wmic', 'nic', 'where', 'PhysicalAdapter=True', 'get', 'MACAddress'],
            capture_output=True, timeout=_WMIC_TIMEOUT,
            creationflags=_FLAGS
        )
        for line in _decode(result.stdout).splitlines()[1:]:
            mac = _WHITESPACE.sub('', line).replace(':', '').replace('-', '').upper()
            if mac:
                macs.append(mac)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        pass

    if not macs:
        fallback = uuid.getnode()
        if fallback == 0:
            _logger.warning('无物理网卡且 uuid.getnode() 返回 0，MAC 指纹不可用')
        else:
            macs.append(format(fallback, '012X'))

    _CACHE_MACS = macs
    return _CACHE_MACS


def collect_fingerprint() -> Dict[str, Optional[str]]:
    """采集全部硬件指纹，MAC 取第一个物理网卡"""
    macs = get_mac_list()
    return {
        'motherboard': get_motherboard_serial(),
        'disk': get_disk_serial(),
        'cpu': get_cpu_id(),
        'mac': macs[0] if macs else None,
        'volume': get_volume_serial(),
    }
