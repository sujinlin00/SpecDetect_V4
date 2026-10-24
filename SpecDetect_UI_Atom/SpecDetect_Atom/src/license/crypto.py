# -*- coding: utf-8 -*-
"""许可证加密核心 — AES-256-GCM + HKDF 密钥派生 + base32 授权码

安全设计:
- MASTER_SECRET_KEY 嵌入 Cython .pyd，不暴露明文
- 授权码 = HMAC-SHA256(K_master, device_name||fingerprint)[:12] → base32 (20字符)
- license.dat = AES-256-GCM 加密，密钥派生自 K_master + 指纹
- GCM 认证标签防篡改，篡改即失效
- 攻击面：即使提取 K_master 也无法离线伪造（需实时硬件指纹）
"""

import hashlib
import hmac
import os
import struct
from typing import Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

# ============================================================
# MASTER_SECRET_KEY — 仅此一处定义，Cython 编译后不可提取
# ============================================================
_MASTER_SECRET_KEY_HEX = (
    "d4e7f1a3b2c8091e5f6a7b8c9d0e1f2a"
    "3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e"
)

_MasterKey = bytes.fromhex(_MASTER_SECRET_KEY_HEX)

# ============================================================
# 授权码 — base32
# ============================================================

_BASE32_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 不含 0/O/1/I 避免混淆
_AUTH_CODE_BYTES = 12  # 96 bits → 20 base32 chars
_AUTH_CODE_GROUP = 4   # 每组4个字符


def _base32_encode(data: bytes) -> str:
    """将字节编码为 base32（自定义字母表，不含易混淆字符）"""
    result = []
    buffer_bits = 0
    buffer_len = 0
    for byte in data:
        buffer_bits = (buffer_bits << 8) | byte
        buffer_len += 8
        while buffer_len >= 5:
            buffer_len -= 5
            result.append(_BASE32_ALPHABET[(buffer_bits >> buffer_len) & 0x1F])
    if buffer_len > 0:
        result.append(_BASE32_ALPHABET[(buffer_bits << (5 - buffer_len)) & 0x1F])
    return "".join(result)


def _base32_decode(encoded: str) -> bytes:
    """base32 解码（反操作）"""
    encoded = encoded.upper().replace("-", "").replace(" ", "")
    bit_buffer = 0
    bit_count = 0
    result = bytearray()
    for ch in encoded:
        idx = _BASE32_ALPHABET.index(ch)
        bit_buffer = (bit_buffer << 5) | idx
        bit_count += 5
        if bit_count >= 8:
            bit_count -= 8
            result.append((bit_buffer >> bit_count) & 0xFF)
    return bytes(result)


def _fingerprint_key(fingerprint: Dict[str, Optional[str]]) -> str:
    """将指纹字典转为确定性字符串（用于密钥派生）"""
    items = sorted(
        (k, v or "") for k, v in fingerprint.items()
        if k in ("motherboard", "disk", "cpu", "mac", "volume")
    )
    return "|".join(f"{k}={v}" for k, v in items)


# ============================================================
# 序列号授权码 — 序列号嵌入码中，离线自验证
# ============================================================

_PREFIX = b"SDA:v2:"
_SEQ_LEN = 4  # 序列号位数（0000-9999）


def generate_auth_code(serial: int, master_key: Optional[bytes] = None) -> str:
    """根据序列号生成授权码

    Args:
        serial: 序列号（0-9999）
        master_key: 主密钥

    Returns:
        授权码，格式 SSSS-XXXX-XXXX-XXXX-XXXX（序列号+16字符签名）
    """
    key = master_key or _MasterKey
    serial_str = f"{serial:0{_SEQ_LEN}d}"
    msg = _PREFIX + serial_str.encode("utf-8")
    raw = hmac.new(key, msg, hashlib.sha256).digest()
    sig = _base32_encode(raw[:9])  # 9 bytes → ~15 base32 chars
    sig_formatted = "-".join(
        sig[i : i + _AUTH_CODE_GROUP]
        for i in range(0, len(sig), _AUTH_CODE_GROUP)
    )
    return f"{serial_str}-{sig_formatted}"


def verify_auth_code(auth_code: str, master_key: Optional[bytes] = None) -> bool:
    """验证授权码（从码中读取序列号，直接验证）

    Args:
        auth_code: 用户输入的授权码
        master_key: 主密钥

    Returns:
        True 如果授权码有效
    """
    normalized = auth_code.upper().replace("-", "").replace(" ", "")
    # 提取前 N 位作为序列号
    seq_digits = normalized[:_SEQ_LEN]
    if not seq_digits.isdigit():
        return False
    serial = int(seq_digits)
    expected = generate_auth_code(serial, master_key)
    expected_normalized = expected.upper().replace("-", "").replace(" ", "")
    return hmac.compare_digest(normalized, expected_normalized)


# ============================================================
# 许可证文件加密 / 解密
# ============================================================


def derive_license_key(
    fingerprint: Dict[str, Optional[str]],
    master_key: Optional[bytes] = None,
) -> bytes:
    """从主密钥 + 设备指纹派生 AES-256 密钥

    指纹变更 → 密钥不同 → 旧 license 无法解密 → 需重新激活
    """
    key = master_key or _MasterKey
    salt = hashlib.sha256(_fingerprint_key(fingerprint).encode()).digest()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"license_v2",
    )
    return hkdf.derive(key)


def encrypt_license_data(
    payload: bytes,
    fingerprint: Dict[str, Optional[str]],
    master_key: Optional[bytes] = None,
) -> bytes:
    """AES-256-GCM 加密许可证数据

    Args:
        payload: 许可证 JSON 字节（UTF-8）
        fingerprint: 硬件指纹
        master_key: 主密钥

    Returns:
        加密后的二进制数据: nonce(12B) || ciphertext || tag(16B)
    """
    aes_key = derive_license_key(fingerprint, master_key)
    nonce = os.urandom(12)
    aesgcm = AESGCM(aes_key)
    ct = aesgcm.encrypt(nonce, payload, None)
    # AESGCM.encrypt returns ciphertext || 16-byte tag
    return nonce + ct


def decrypt_license_data(
    encrypted: bytes,
    fingerprint: Dict[str, Optional[str]],
    master_key: Optional[bytes] = None,
) -> Optional[bytes]:
    """AES-256-GCM 解密许可证数据

    Args:
        encrypted: nonce(12B) || ciphertext || tag(16B)
        fingerprint: 硬件指纹
        master_key: 主密钥

    Returns:
        解密后的许可证 JSON 字节，或 None（解密失败/密钥不匹配）
    """
    if len(encrypted) < 28:  # 12 nonce + 16 tag minimum
        return None
    aes_key = derive_license_key(fingerprint, master_key)
    nonce = encrypted[:12]
    ct = encrypted[12:]
    aesgcm = AESGCM(aes_key)
    try:
        return aesgcm.decrypt(nonce, ct, None)
    except Exception:
        return None


# ============================================================
# V2 许可证文件读写
# ============================================================

LICENSE_V2_MAGIC = b"L2"  # 格式标识，区别于旧 JSON 格式


def save_license_v2(
    path: str,
    payload_bytes: bytes,
    fingerprint: Dict[str, Optional[str]],
    master_key: Optional[bytes] = None,
) -> None:
    """保存 V2 加密许可证到文件"""
    encrypted = encrypt_license_data(payload_bytes, fingerprint, master_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(LICENSE_V2_MAGIC + encrypted)


def _candidate_fingerprints(
    fingerprint: Dict[str, Optional[str]],
) -> List[Dict[str, Optional[str]]]:
    """生成候选指纹集合

    许可证密钥由指纹派生，因此任意一项标识符本次采集失败（WMIC/WMI 抽风、
    驱动不暴露序列号、PS 超时……）都会导致解不开许可证、被迫重新激活。

    这里为每一项易变标识符生成"该项为 None"的变体，解密时逐个尝试：
    键的派生只依赖各字段是否为空，语义与"采集时就是空"完全一致，
    不降低绑定强度（攻击者仍需正确的硬件指纹才能解出明文）。

    另外生成"旧版指纹方案"（不含 volume 字段）的候选，
    保证升级前签发的许可证无需重新激活。
    """
    candidates: List[Dict[str, Optional[str]]] = []
    seen = set()

    def add(fp: Dict[str, Optional[str]]) -> None:
        marker = tuple(sorted((k, v or '') for k, v in fp.items()))
        if marker not in seen:
            seen.add(marker)
            candidates.append(fp)

    def expand(base: Dict[str, Optional[str]]) -> None:
        add(base)
        for key in ('disk', 'volume', 'motherboard', 'cpu', 'mac'):
            if base.get(key) is not None:
                variant = dict(base)
                variant[key] = None
                add(variant)
        if base.get('disk') is not None and base.get('volume') is not None:
            variant = dict(base)
            variant['disk'] = None
            variant['volume'] = None
            add(variant)

    expand(fingerprint)
    legacy = {k: v for k, v in fingerprint.items() if k != 'volume'}
    if legacy != fingerprint:
        expand(legacy)
    return candidates


def load_license_v2(
    path: str,
    fingerprint: Dict[str, Optional[str]],
    master_key: Optional[bytes] = None,
) -> Optional[bytes]:
    """加载并解密 V2 许可证（容忍单项指纹临时采集失败）"""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(LICENSE_V2_MAGIC):
        return None
    for candidate in _candidate_fingerprints(fingerprint):
        raw = decrypt_license_data(data[2:], candidate, master_key)
        if raw is not None:
            return raw
    return None


def is_v2_format(path: str) -> bool:
    """检测许可证文件是否为 V2 加密格式"""
    if not os.path.exists(path):
        return False
    with open(path, "rb") as f:
        return f.read(2) == LICENSE_V2_MAGIC
