"""
인증(로그인) 로직

- user_info    : 사용자 계정 (다른 서비스와 공유 — 읽기만 함)
- user_devices : 브라우저(기기)별 로그인 토큰. 로그인 시 발급, 로그아웃 시 삭제

세션에는 user_id 와 device_token 만 저장하고,
요청마다 user_devices 에서 (user_id, device_token, 만료일)을 확인한다.
→ DB 에서 토큰 행을 지우면 해당 기기는 즉시 로그아웃된다.
"""
import secrets

from ..db import execute, fetch_one
from ..utils.password import verify_password


def authenticate(user_id: str, password: str) -> dict | None:
    """아이디/비밀번호 확인 → 성공 시 사용자 정보(dict), 실패 시 None"""
    user = fetch_one(
        "SELECT id, user_id, password, email, role FROM user_info WHERE user_id = %s",
        (user_id,),
    )
    if not user or not verify_password(password, user["password"]):
        return None
    user.pop("password")  # 이후 흐름에 비밀번호 저장값을 들고 다니지 않음
    return user


def issue_device_token(user_id: str, user_agent: str | None, days: int) -> str:
    """새 기기 토큰 발급 후 user_devices 에 저장 (64자 hex, 기존 데이터 형식과 동일)"""
    token = secrets.token_hex(32)
    execute(
        """
        INSERT INTO user_devices (user_id, device_token, user_agent, expires_at)
        VALUES (%s, %s, %s, NOW() + INTERVAL %s DAY)
        """,
        (user_id, token, (user_agent or "")[:255], days),
    )
    return token


def verify_device(user_id: str, device_token: str) -> dict | None:
    """
    세션의 (user_id, device_token) 검증
    - 토큰이 존재하고, user_id 가 일치하고, 만료되지 않았고, user_info 에 계정이 있어야 통과
    """
    return fetch_one(
        """
        SELECT u.id, u.user_id, u.email, u.role, d.expires_at
          FROM user_devices d
          JOIN user_info    u ON u.user_id = d.user_id
         WHERE d.device_token = %s
           AND d.user_id      = %s
           AND d.expires_at   > NOW()
        """,
        (device_token, user_id),
    )


def revoke_device(user_id: str, device_token: str) -> None:
    """로그아웃: 이 브라우저의 토큰 행만 삭제 (다른 기기 로그인은 유지)"""
    execute(
        "DELETE FROM user_devices WHERE device_token = %s AND user_id = %s",
        (device_token, user_id),
    )
