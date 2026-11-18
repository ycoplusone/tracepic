"""
비밀번호 검증 유틸

user_info.password 는 다른 서비스와 공유하는 컬럼이라 저장 형식을 TracePic 이 바꾸지 않는다.
저장값 형식을 보고 알맞은 방식으로 검증한다.
- bcrypt      : $2a$ / $2b$ / $2y$ 로 시작
- werkzeug    : pbkdf2:... / scrypt:... 로 시작
- 그 외(평문) : 타이밍 공격을 막기 위해 hmac.compare_digest 로 비교
  ※ 평문 저장은 레거시 호환용. 해시로 이전되면 이 분기는 자연히 쓰이지 않는다.
"""
import hmac

import bcrypt
from werkzeug.security import check_password_hash

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")
_WERKZEUG_PREFIXES = ("pbkdf2:", "scrypt:")


def verify_password(plain: str, stored: str | None) -> bool:
    """입력 비밀번호(plain)가 DB 저장값(stored)과 일치하는지 검증"""
    if not plain or not stored:
        return False
    try:
        if stored.startswith(_BCRYPT_PREFIXES):
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        if stored.startswith(_WERKZEUG_PREFIXES):
            return check_password_hash(stored, plain)
    except ValueError:
        # 해시 형식이 깨진 경우 → 실패 처리
        return False
    # 평문 저장값 (레거시)
    return hmac.compare_digest(plain.encode("utf-8"), stored.encode("utf-8"))
