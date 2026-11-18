"""
여행기(스토리) 로직 — 기간 안의 날짜별로 '그날 일기 + 그날 사진(촬영순) + 사진 설명'을 묶는다

- 새 테이블 없이 날짜(base_dt)와 사용자로 tracepic_daily · tracepic_photos · tracepic_notes 를 잇는다.
- 쿼리는 기간 전체에 대해 종류별 1번씩(사진·일기·설명)만 하고, 날짜별로 나누는 일은 파이썬에서 한다.
- 사진은 있는데 일기가 없는 날, 일기는 있는데 사진이 없는 날도 모두 포함한다.
"""
from datetime import datetime

from ..utils.dates import validate_base_dt
from . import daily_logic, note_logic, photo_logic

MAX_DAYS = 366   # 한 번에 볼 수 있는 최대 기간 (화면이 너무 길어지지 않게)


def build_story(user_id: str, start_dt: str, end_dt: str,
                statuses=photo_logic.VISIBLE_STATUSES) -> list[dict]:
    """
    기간(양끝 포함)의 여행기 → 날짜 오름차순 목록
      [{"base_dt", "daily": 일기 행 | None, "photos": [사진 행...촬영순], "notes": {pic_id: 설명 행}}]
    - 사진은 상태 조건(statuses)에 맞는 것만. 일기는 상태와 관계없이 그날 것.
    - 잘못된 날짜·기간이면 ValueError
    """
    start_dt, end_dt = validate_base_dt(start_dt), validate_base_dt(end_dt)
    if start_dt > end_dt:
        raise ValueError("시작일이 종료일보다 늦습니다.")
    days_between = (datetime.strptime(end_dt, "%Y%m%d") - datetime.strptime(start_dt, "%Y%m%d")).days
    if days_between >= MAX_DAYS:
        raise ValueError(f"여행기는 한 번에 {MAX_DAYS}일까지 볼 수 있습니다. 기간을 줄여 주세요.")

    photos = photo_logic.list_photos_by_range(user_id, start_dt, end_dt, statuses=statuses)
    dailies = daily_logic.list_daily(user_id, start_dt, end_dt)
    notes = note_logic.first_notes_by_photo(user_id, [p["pic_id"] for p in photos])

    days: dict[str, dict] = {}

    def day(dt: str) -> dict:
        if dt not in days:
            days[dt] = {"base_dt": dt, "daily": None, "photos": [], "notes": {}}
        return days[dt]

    for d in dailies:
        day(d["base_dt"])["daily"] = d          # 하루 1건 규칙 (여러 건이면 마지막 것)
    for p in photos:                            # 이미 촬영 시각순
        entry = day(p["base_dt"])
        entry["photos"].append(p)
        if p["pic_id"] in notes:
            entry["notes"][p["pic_id"]] = notes[p["pic_id"]]
    return [days[dt] for dt in sorted(days)]
