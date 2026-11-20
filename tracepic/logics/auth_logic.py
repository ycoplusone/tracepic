"""
인증(로그인) 로직

- user_info    : 사용자 계정 (다른 서비스와 공유 — 읽기만 함.
                 예외: hash_plain_passwords() 의 평문 → bcrypt 일괄 변환, 2026-11-20 사용자 결정)
- user_devices : 브라우저(기기)별 로그인 토큰. 로그인 시 발급, 로그아웃 시 삭제

세션에는 user_id 와 device_token 만 저장하고,
요청마다 user_devices 에서 (user_id, device_token, 만료일)을 확인한다.
→ DB 에서 토큰 행을 지우면 해당 기기는 즉시 로그아웃된다.
"""
import secrets

from ..db import execute, fetch_one, transaction
from ..utils.password import hash_password, is_hashed, verify_password


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


def hash_plain_passwords(dry_run: bool = False) -> dict:
    """user_info 의 평문 비밀번호를 bcrypt 해시로 일괄 변환 (한 트랜잭션, 다시 실행해도 안전)

    - 이미 해시인 행은 건너뛴다. 비밀번호 값은 반환하거나 출력하지 않고 건수만 돌려준다.
    - 해시를 만든 뒤 원래 평문으로 검증이 통과하는지 확인하고 나서 UPDATE 한다.
    - UPDATE 에 원래 값 조건(password = %s)을 걸어, 그사이 다른 서비스가 바꾼 행은 덮어쓰지 않는다.
    - 하나라도 실패하면 전체 롤백. dry_run=True 면 세기만 하고 바꾸지 않는다.
    """
    result = {"total": 0, "already_hashed": 0, "converted": 0, "skipped": 0}
    with transaction() as cur:
        cur.execute("SELECT id, password FROM user_info FOR UPDATE")
        rows = cur.fetchall()
        result["total"] = len(rows)
        for row in rows:
            stored = row["password"]
            if is_hashed(stored):
                result["already_hashed"] += 1
                continue
            if not stored:  # 빈 비밀번호는 해시하지 않음 (로그인 불가 상태 유지)
                result["skipped"] += 1
                continue
            hashed = hash_password(stored)
            if not verify_password(stored, hashed):
                raise RuntimeError("해시 검증 실패 — 변환을 중단하고 롤백합니다.")
            if dry_run:
                result["converted"] += 1
                continue
            cur.execute(
                "UPDATE user_info SET password = %s WHERE id = %s AND password = %s",
                (hashed, row["id"], stored),
            )
            if cur.rowcount == 1:
                result["converted"] += 1
            else:
                result["skipped"] += 1
        if dry_run:
            cur.connection.rollback()
    return result


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
