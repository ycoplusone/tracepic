"""
이미지 파일 암호화 / 복호화 (DB 와 무관)

키 유도 (CLAUDE.md "보안·암호화 결정사항", 2026-11-17 사용자 결정)
- HKDF-SHA256(key material = MASTER_SALT, info = user_id) → 32바이트 키 → Fernet
- 사용자마다 키가 하나다. 같은 사용자의 파일은 같은 키를 쓰지만,
  Fernet 이 파일마다 무작위 IV 를 쓰고 HMAC 으로 변조를 검사하므로 같은 사진이라도 암호문은 매번 다르다.
- user_id 는 DB·폴더 이름에 평문으로 남는다 → 실질적인 비밀은 MASTER_SALT 하나.
  MASTER_SALT 를 잃으면 기존 파일은 복호화할 수 없다.
"""
import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

__all__ = ["encrypt_bytes", "decrypt_bytes", "InvalidToken"]


def _fernet(master_salt: str, user_id: str) -> Fernet:
    """(MASTER_SALT, user_id) → 사용자 전용 Fernet 객체"""
    if not master_salt:
        # 빈 값으로 암호화하면 나중에 MASTER_SALT 를 설정한 뒤 복호화할 수 없게 된다 → 아예 막는다
        raise RuntimeError("MASTER_SALT 가 설정되지 않아 이미지를 암호화/복호화할 수 없습니다.")
    if not user_id:
        raise ValueError("user_id 가 비어 있어 암호화 키를 만들 수 없습니다.")
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,  # 비밀은 key material(MASTER_SALT)이 담당하고, 사용자 구분은 info 가 담당한다
        info=user_id.encode("utf-8"),
    ).derive(master_salt.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_bytes(data: bytes, master_salt: str, user_id: str) -> bytes:
    """평문 바이트 → 암호문(Fernet 토큰). 같은 입력이어도 매번 다른 IV 를 써서 결과가 달라진다."""
    return _fernet(master_salt, user_id).encrypt(data)


def decrypt_bytes(token: bytes, master_salt: str, user_id: str) -> bytes:
    """암호문 → 평문 바이트. 키가 다르거나(다른 사용자·MASTER_SALT 변경) 파일이 변조되면 InvalidToken"""
    return _fernet(master_salt, user_id).decrypt(token)
