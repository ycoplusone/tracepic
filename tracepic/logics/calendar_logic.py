"""
달력 로직 — 한 달의 날짜별 사진 수·첫/마지막 촬영 시각·이동 거리·일기 여부

- 새 테이블 없이 tracepic_photos(상태 조건)와 tracepic_daily 를 날짜(base_dt)로 묶는다.
- 쿼리는 사진·일기 한 번씩만 하고 날짜별 집계는 파이썬에서 한다 (한 달 사진 수 정도는 가볍다).
- 이동 거리 = 그날 위치 있는 사진을 촬영 시각순으로 이은 직선거리 합 (utils/geo.path_km)
"""
import calendar
import re

from ..utils import geo
from . import daily_logic, photo_logic

_MONTH = re.compile(r"\d{6}")


def check_month(month: str) -> tuple[int, int]:
    """'YYYYMM' → (연, 월). 형식이 틀리면 ValueError"""
    if not isinstance(month, str) or not _MONTH.fullmatch(month):
        raise ValueError("월 형식이 올바르지 않습니다 (YYYYMM).")
    year, mon = int(month[:4]), int(month[4:])
    if not (1 <= year <= 9999 and 1 <= mon <= 12):
        raise ValueError("월 형식이 올바르지 않습니다 (YYYYMM).")
    return year, mon


def day_stats(rows: list[dict]) -> dict:
    """
    하루치 사진 행(촬영 시각순) → {"count", "first", "last", "km"}
    - first/last: 첫·마지막 사진의 촬영 시각(datetime), 사진이 없으면 None
    - km: 위치 있는 사진을 차례로 이은 거리 (위치 있는 사진이 2장 미만이면 0)
    """
    points = [(float(r["latitude"]), float(r["longitude"])) for r in rows if photo_logic.has_location(r)]
    return {
        "count": len(rows),
        "first": rows[0]["photo_at"] if rows else None,
        "last": rows[-1]["photo_at"] if rows else None,
        "km": geo.path_km(points),
    }


def month_summary(user_id: str, month: str, statuses=photo_logic.VISIBLE_STATUSES) -> dict:
    """
    한 달 요약
    → {"start": 'YYYYMM01', "end": 'YYYYMM말일',
       "days": {base_dt: {"count", "first", "last", "km", "diary_title" | None, "has_diary"}},
       "totals": {"photos", "days_with_photos", "diaries", "km"}}
    - 사진이나 일기가 있는 날만 days 에 들어간다.
    """
    year, mon = check_month(month)
    start = f"{year:04d}{mon:02d}01"
    end = f"{year:04d}{mon:02d}{calendar.monthrange(year, mon)[1]:02d}"

    photos = photo_logic.list_photos_by_range(user_id, start, end, statuses=statuses)   # 촬영 시각순
    dailies = daily_logic.list_daily(user_id, start, end)

    by_day: dict[str, list[dict]] = {}
    for p in photos:
        by_day.setdefault(p["base_dt"], []).append(p)

    days: dict[str, dict] = {}
    for dt, rows in by_day.items():
        days[dt] = {**day_stats(rows), "has_diary": False, "diary_title": None}
    for d in dailies:
        entry = days.setdefault(d["base_dt"], {"count": 0, "first": None, "last": None, "km": 0.0})
        entry["has_diary"] = True
        entry["diary_title"] = d["title"] or ""

    return {
        "start": start,
        "end": end,
        "days": days,
        "totals": {
            "photos": len(photos),
            "days_with_photos": len(by_day),
            "diaries": len(dailies),
            "km": sum(d["km"] for d in days.values()),
        },
    }
