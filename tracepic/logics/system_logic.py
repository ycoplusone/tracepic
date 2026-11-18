"""
시스템 상태 관련 로직
"""
from ..db import fetch_one


def check_db() -> tuple[bool, str]:
    """DB 연결 확인: (성공 여부, 실패 시 예외 클래스명) — 비밀번호 등 상세 정보는 노출하지 않음"""
    try:
        row = fetch_one("SELECT 1 AS ok")
        return (row is not None and row["ok"] == 1), "ok"
    except Exception as e:  # noqa: BLE001 — 상태 응답용
        return False, e.__class__.__name__
