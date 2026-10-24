# -*- coding: utf-8 -*-
"""许可证管理 — 生成、验证、签名（RSA-2048 非对称加密）"""

import hashlib
import json
import os
import socket
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature

from license.hardware import collect_fingerprint
from license.crypto import (
    generate_auth_code,
    verify_auth_code,
    save_license_v2,
    load_license_v2,
    is_v2_format,
)

# 公钥嵌入 — 仅可用于验签，无法用于签发许可证
_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuq6UPr77ZSRE8SbfvDV/
pykdpXxQ605eS3CYxLUiaEYlV26mS9VMPTMh71kFUIwBatxcIxiJ0LDB6qiOt92J
JsO7EPQzAqiBzBgmqZfLwxeNhuMmXzEx21/UQtFEwgQXzhTSiyOTONLtiAe9PY78
eO49cNePF/pzhogEKQilPo/Yd1Ox/2tleO8G5ac5Nlhg/En7K/OQdupHFbsXKiid
IjGLD6FEBUojMohzOqahXLFowVdKxmVX0qErgyAx04aqFa1UcfoxjWa0Bgq2kwVe
rhAl4e22+xaKjyCepo4k5DOBeOlVNutQBYkTeysFXxTK0Fr/K9MBxbrQDZC18/AB
UQIDAQAB
-----END PUBLIC KEY-----"""

LICENSE_FILENAME = 'license.dat'
MATCH_REQUIRED = 2
MATCH_KEYS = ('motherboard', 'disk', 'cpu', 'mac', 'volume')

# 缓存公钥对象
_public_key = serialization.load_pem_public_key(_PUBLIC_KEY_PEM)


def _load_private_key(key_path: str) -> rsa.RSAPrivateKey:
    """加载 RSA 私钥文件"""
    with open(key_path, 'rb') as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError('私钥文件格式不正确，需要 RSA 私钥')
    return key


def _sign(data: str, signing_key: rsa.RSAPrivateKey) -> str:
    """RSA-PSS SHA256 签名"""
    signature = signing_key.sign(
        data.encode('utf-8'),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return signature.hex()


def hash_fingerprint(fp: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    """对硬件指纹做 SHA256 哈希，None 值保持为 None"""
    return {
        k: hashlib.sha256(v.encode()).hexdigest() if v else None
        for k, v in fp.items()
    }


def _verify_signature(data: dict) -> bool:
    """RSA 公钥验签"""
    stored_sig = data.get('signature', '')
    if not stored_sig:
        return False
    payload = {k: v for k, v in data.items() if k != 'signature'}
    payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    try:
        _public_key.verify(
            bytes.fromhex(stored_sig),
            payload_str.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def _find_license_path(license_path: Optional[str] = None) -> str:
    if license_path:
        return license_path

    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        return os.path.join(exe_dir, 'config', LICENSE_FILENAME)

    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        cfg = os.path.join(current, 'config')
        if os.path.isdir(cfg):
            return os.path.join(cfg, LICENSE_FILENAME)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise FileNotFoundError("找不到项目根目录的 config/ 文件夹，无法定位许可证文件")


def _verify_devices(devices: List[Dict[str, Any]]) -> bool:
    """核心：用当前硬件指纹与已注册设备列表比对（4 选 2）"""
    current_fp = hash_fingerprint(collect_fingerprint())

    for device in devices:
        stored_fp: Dict[str, Optional[str]] = device.get('fingerprint', {})
        matches = 0
        for key in MATCH_KEYS:
            cur_val = current_fp.get(key)
            sto_val = stored_fp.get(key)
            if cur_val is not None and sto_val is not None and cur_val == sto_val:
                matches += 1
        if matches >= MATCH_REQUIRED:
            return True

    return False


def verify_license(license_path: Optional[str] = None) -> bool:
    """从 license.dat 文件验证当前设备是否已授权

    支持两种格式:
    - V1 (旧): RSA 签名的明文 JSON（向后兼容）
    - V2 (新): AES-256-GCM 加密二进制

    对每个已注册设备，比对 4 项硬件指纹（主板/硬盘/CPU/MAC）。
    跳过不可用的标识符（None），4 项中 ≥ 2 项匹配即视为授权通过。

    Returns:
        True 如果至少一个已注册设备匹配 ≥ 2 项
    """
    path = _find_license_path(license_path)
    if not os.path.exists(path):
        return False

    # V2 加密格式
    if is_v2_format(path):
        current_fp = collect_fingerprint()
        raw = load_license_v2(path, current_fp)
        if raw is None:
            return False
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        # V2 格式自带硬件绑定（密钥派生自指纹），仍需验证签名一致性
        return _verify_devices(data.get("devices", []))

    # V1 明文 JSON 格式
    try:
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    return verify_license_data(data)


def verify_license_data(data: dict) -> bool:
    """用内存中的许可证数据验证当前设备（用于嵌入式许可证）

    Args:
        data: 已加载的许可证字典（须包含 signature 和 devices）

    Returns:
        True 如果至少一个已注册设备匹配 ≥ 2 项
    """
    if not _verify_signature(data):
        return False

    devices: List[Dict[str, Any]] = data.get('devices', [])
    if not devices:
        return False

    return _verify_devices(devices)


def generate_license(
    license_path: Optional[str] = None,
    device_name: str = '',
    merge: bool = False,
    signing_key: Optional[rsa.RSAPrivateKey] = None
) -> Tuple[str, Dict[str, Optional[str]]]:
    """为当前设备生成/追加许可证

    Args:
        license_path: 许可证文件路径，默认 config/license.dat
        device_name: 设备名称，默认取主机名
        merge: 是否追加到已有许可证（默认覆盖）
        signing_key: RSA 私钥（gen_license.py 必须提供，exe 运行时不可用）

    Returns:
        (许可证文件路径, 当前硬件指纹哈希)

    Raises:
        ValueError: 设备已注册、设备名冲突、或已有许可证被篡改
        RuntimeError: 未提供 signing_key
    """
    if signing_key is None:
        raise RuntimeError('签名需要 RSA 私钥，请通过 gen_license.py 生成许可证')

    path = _find_license_path(license_path)

    current_fp = hash_fingerprint(collect_fingerprint())
    hostname = device_name or socket.gethostname()

    new_device: Dict[str, Any] = {
        'name': hostname,
        'fingerprint': current_fp,
        'registered_at': datetime.now().isoformat()
    }

    if merge and os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            raise ValueError('许可证文件已损坏，无法读取')

        if not _verify_signature(data):
            raise ValueError('已有许可证签名无效，可能已被篡改')

        devices: List[Dict[str, Any]] = data.setdefault('devices', [])

        existing_names = {d.get('name', '') for d in devices}
        existing_fps = {
            json.dumps(d.get('fingerprint', {}), sort_keys=True)
            for d in devices
        }
        new_fp_str = json.dumps(current_fp, sort_keys=True)

        if new_fp_str in existing_fps:
            raise ValueError('设备已注册（指纹匹配已存在的设备）')
        if hostname in existing_names:
            raise ValueError(f'设备名 "{hostname}" 已存在，请使用 --name 指定其他名称')

        devices.append(new_device)
    else:
        data = {
            'version': 1,
            'devices': [new_device]
        }

    data.pop('signature', None)
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    data['signature'] = _sign(payload, signing_key)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return path, current_fp


def activate_with_code(
    auth_code: str,
    license_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """使用授权码激活当前设备，生成加密 V2 许可证

    授权码是通用的（与设备无关），验证通过后用当前设备指纹生成加密许可证。

    Args:
        auth_code: 用户输入的 20 字符授权码
        license_path: 许可证输出路径

    Returns:
        (成功/失败, 消息)
    """
    current_fp = collect_fingerprint()
    hostname = socket.gethostname()

    if not verify_auth_code(auth_code):
        return False, "授权码无效，请检查输入或联系管理员重新生成"

    # 生成许可证内容
    hashed_fp = hash_fingerprint(current_fp)
    license_data = {
        "version": 2,
        "devices": [
            {
                "name": hostname,
                "fingerprint": hashed_fp,
                "registered_at": datetime.now().isoformat(),
            }
        ],
    }
    payload = json.dumps(license_data, sort_keys=True, ensure_ascii=False).encode("utf-8")

    path = _find_license_path(license_path)
    save_license_v2(path, payload, current_fp)

    return True, f"激活成功！许可证已生成到 {path}"


def import_devices_from_file(
    source_path: str,
    target_path: Optional[str] = None,
    signing_key: Optional[rsa.RSAPrivateKey] = None,
    skip_source_verify: bool = False
) -> Tuple[str, int]:
    """从外部 .dat 文件导入设备到当前许可证

    Args:
        source_path: 源 .dat 文件路径（要导入的设备）
        target_path: 目标许可证路径，默认 config/license.dat
        signing_key: RSA 私钥
        skip_source_verify: 跳过源文件签名验证（用于 HMAC→RSA 迁移）

    Returns:
        (目标许可证路径, 新增设备数)

    Raises:
        FileNotFoundError: 源文件不存在
        ValueError: 源文件签名无效、格式损坏、或所有设备已存在
        RuntimeError: 未提供 signing_key
    """
    if signing_key is None:
        raise RuntimeError('签名需要 RSA 私钥，请通过 gen_license.py 操作')

    if not os.path.exists(source_path):
        raise FileNotFoundError(f'源许可证文件不存在: {source_path}')

    with open(source_path, 'r', encoding='utf-8') as f:
        source_data = json.load(f)

    if not skip_source_verify and not _verify_signature(source_data):
        raise ValueError(f'源许可证签名无效（可能已被篡改）: {source_path}')

    source_devices: List[Dict[str, Any]] = source_data.get('devices', [])
    if not source_devices:
        raise ValueError('源许可证中没有已注册的设备')

    target = _find_license_path(target_path)
    if os.path.exists(target):
        with open(target, 'r', encoding='utf-8') as f:
            target_data = json.load(f)
        if not _verify_signature(target_data):
            raise ValueError('目标许可证签名无效，可能已被篡改')
    else:
        target_data = {'version': 1, 'devices': []}

    existing_devices: List[Dict[str, Any]] = target_data.setdefault('devices', [])
    existing_names = {d.get('name', '') for d in existing_devices}
    existing_fps = {
        json.dumps(d.get('fingerprint', {}), sort_keys=True)
        for d in existing_devices
    }

    added = 0
    skipped = 0
    for device in source_devices:
        name = device.get('name', '')
        fp_str = json.dumps(device.get('fingerprint', {}), sort_keys=True)

        if fp_str in existing_fps:
            print(f'  [跳过] 指纹已存在: {name}')
            skipped += 1
            continue
        if name and name in existing_names:
            print(f'  [跳过] 设备名冲突: {name}')
            skipped += 1
            continue

        existing_devices.append(device)
        existing_names.add(name)
        existing_fps.add(fp_str)
        print(f'  [导入] {name}')
        added += 1

    if added == 0:
        raise ValueError(f'没有新设备被导入（{skipped} 个设备已存在或冲突）')

    target_data.pop('signature', None)
    payload = json.dumps(target_data, sort_keys=True, ensure_ascii=False)
    target_data['signature'] = _sign(payload, signing_key)

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(target_data, f, indent=2, ensure_ascii=False)

    return target, added
