"""
날짜 관련 순수 함수 (DB 와 무관)

- base_dt : 촬영일을 'YYYYMMDD' 8자리 문자열로 저장한다 (tracepic_photos, tracepic_daily 공통).
"""
from datetime import date, datetime


def to_base_dt(value: date | datetime) -> str:
    """date/datetime → 'YYYYMMDD' 문자열"""
    return value.strftime("%Y%m%d")


def validate_base_dt(base_dt: str) -> str:
    """
    'YYYYMMDD' 형식이고 실제로 존재하는 날짜인지 확인한 뒤 그대로 반환
    잘못된 값이면 ValueError (예: '20261332', '2026-11-17')
    """
    if not isinstance(base_dt, str) or len(base_dt) != 8 or not base_dt.isdigit():
        raise ValueError(f"base_dt 는 YYYYMMDD 8자리여야 합니다: {base_dt!r}")
    datetime.strptime(base_dt, "%Y%m%d")  # 존재하지 않는 날짜면 여기서 ValueError
    return base_dt
