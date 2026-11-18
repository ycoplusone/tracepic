"""
JSON API (/api) — 지도 화면의 JS 가 호출한다

- GET /api/photo-dates?status=A,B,C[&start=&end=]   사진이 있는 날짜 목록과 날짜별 장수 (상태·기간 조건)
                                            기간을 주면 그 기간의 일기 요약(diaries)도 함께
- GET /api/map-photos?start=YYYYMMDD&end=YYYYMMDD&status=A,B,C
                                            기간·상태 조건의 사진 전체(촬영 시각순, 위치 없는 사진 포함)
- GET/PATCH /api/photos/<pic_id>            사진 상세(설명 포함) / 상태 또는 위치 변경
- PUT/DELETE /api/photos/<pic_id>/note      사진 설명(마크다운) 저장 / 삭제
- POST /api/markdown/preview                마크다운 미리보기 (저장하지 않음)
- GET/PUT/DELETE /api/diary[/<base_dt>], POST /api/diary/preview   일기(일별 마크다운 기록)
- GET /api/story?start=&end=&status=        여행기: 날짜별 일기 + 사진(촬영순) + 사진 설명 + 하루 통계(시각·이동 거리)
- GET /api/calendar?month=YYYYMM&status=    달력: 날짜별 사진 수·첫/마지막 촬영 시각·이동 거리·일기 여부
- GET /api/search?q=                        검색: 일기·사진 설명의 제목/본문
로그인하지 않았으면 전역 가드(routes/auth.py)가 401 JSON 을 돌려준다.
"""
import math
from datetime import date

from flask import Blueprint, g, jsonify, request, url_for

from ..logics import calendar_logic, daily_logic, note_logic, photo_logic, story_logic
from ..utils import md

bp = Blueprint("api", __name__)


def _status_arg() -> tuple[str, ...]:
    """?status=A,B,C → 검증된 상태 튜플 (없으면 기본 A/B/C). 잘못된 값이면 ValueError"""
    raw = request.args.get("status")
    if raw is None:
        return photo_logic.VISIBLE_STATUSES
    return photo_logic.check_status_filter(raw.split(","))


@bp.get("/photo-dates")
def photo_dates():
    """
    사진이 있는 날짜 목록 (최근 날짜부터, 상태 조건에 맞는 사진만). start·end 를 주면 그 기간만
    - 기간을 주면 그 기간의 일기 요약(diaries: 날짜·제목·요약문)도 함께 보낸다 → 지도 날짜 목록의 📖 표시용
      (기간 없이 부르는 '전체' 버튼은 날짜 범위만 필요하므로 빈 목록)
    """
    user_id = g.user["user_id"]
    start, end = request.args.get("start") or None, request.args.get("end") or None
    try:
        rows = photo_logic.list_photo_dates(user_id, _status_arg(), start, end)
        dailies = daily_logic.list_daily(user_id, start, end) if start else []
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(
        dates=[{"base_dt": r["base_dt"], "count": r["photo_count"]} for r in rows],
        diaries=[_diary_brief(d) for d in dailies],
    )


def _diary_brief(row: dict) -> dict:
    """일기 행 → 요약 JSON (본문 대신 짧은 평문 요약)"""
    return {"base_dt": row["base_dt"], "title": row["title"] or "", "excerpt": md.excerpt(row["note"])}


@bp.get("/map-photos")
def map_photos():
    """기간·상태 조건의 사진 (촬영 시각순). 위치 없는 사진은 lat/lng 가 null"""
    start, end = request.args.get("start", ""), request.args.get("end", "")
    try:
        result = photo_logic.list_map_photos(g.user["user_id"], start, end, _status_arg())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    user_id = g.user["user_id"]
    noted = note_logic.photo_ids_with_notes(user_id, [r["pic_id"] for r in result["photos"]])
    return jsonify(photos=[_photo_json(r, r["pic_id"] in noted) for r in result["photos"]],
                   unlocated_count=result["unlocated_count"])


def _photo_json(r: dict, has_note: bool = False) -> dict:
    """사진 행 → 화면용 JSON (좌표 Decimal → float, 위치 없으면 null, has_note = 설명이 있는지)"""
    located = photo_logic.has_location(r)
    return {
        "pic_id": r["pic_id"],
        "base_dt": r["base_dt"],
        "photo_at": r["photo_at"].strftime("%Y-%m-%d %H:%M"),
        "lat": float(r["latitude"]) if located else None,
        "lng": float(r["longitude"]) if located else None,
        "name": r["original_file_name"] or "",
        "status": r["status"].upper(),
        "has_note": has_note,
        "thumb_url": url_for("photo.thumb", pic_id=r["pic_id"]),
        "mini_url": url_for("photo.mini", pic_id=r["pic_id"]),   # 마커·필름용 (128px 정사각형)
        "image_url": url_for("photo.image", pic_id=r["pic_id"]),
    }


# ============================================================
# 사진 1장 (상세 · 상태 변경 · 설명)
# ============================================================
@bp.get("/photos/<int:pic_id>")
def photo_detail(pic_id: int):
    """사진 상세 + 설명(마크다운 원문·살균 HTML). 휴지통 사진은 설명을 보여 주지 않는다"""
    user_id = g.user["user_id"]
    row = photo_logic.get_photo(user_id, pic_id, include_deleted=True)
    if row is None:
        return jsonify(error="사진이 없습니다."), 404
    note = note_logic.get_photo_note(user_id, pic_id)
    return jsonify(
        **_photo_json(row, note is not None),
        note=None if note is None else {
            "note_id": note["note_id"],
            "title": note["title"] or "",
            "note": note["note"],
            "html": md.render(note["note"]),
            "updated_at": (note["updated_at"] or note["created_at"]).strftime("%Y-%m-%d %H:%M"),
        },
    )


@bp.patch("/photos/<int:pic_id>")
def photo_update(pic_id: int):
    """
    사진 정보 변경 — body 에 보낸 항목만 바꾼다
    - {"status": "A" | "B" | "C" | "D"}: 상태 변경 (D 는 휴지통, D → A/B/C 는 복구)
    - {"latitude": 33.4, "longitude": 126.5}: 위치 지정·수정 (둘 다 null 이면 위치 지우기). 휴지통 사진은 안 됨
    """
    data = request.get_json(silent=True) or {}
    has_status = "status" in data
    has_location = "latitude" in data or "longitude" in data
    if not has_status and not has_location:
        return jsonify(error="status 또는 latitude/longitude 를 보내야 합니다."), 400
    if has_status and has_location:
        return jsonify(error="상태와 위치는 따로 바꿔 주세요."), 400
    user_id = g.user["user_id"]

    if has_status:
        status = data.get("status")
        if not isinstance(status, str):
            return jsonify(error="status 는 문자열이어야 합니다."), 400
        try:
            changed = photo_logic.change_status(user_id, pic_id, status)
        except ValueError as e:
            return jsonify(error=str(e)), 400
        if not changed:
            return jsonify(error="사진이 없습니다."), 404
        return jsonify(ok=True, status=status.upper())

    lat, lng = data.get("latitude"), data.get("longitude")
    for v in (lat, lng):
        # bool 은 int 의 하위 타입이라 따로 막는다 (true → 1.0 이 되지 않게)
        # NaN·Infinity 도 JSON 으로 들어올 수 있으므로 유한한 수만 받는다
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
            return jsonify(error="위도·경도는 숫자여야 합니다."), 400
    try:
        changed = photo_logic.update_location(user_id, pic_id, lat, lng)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if not changed:
        return jsonify(error="위치를 바꿀 수 없는 사진입니다. 휴지통에 있다면 먼저 복구해 주세요."), 404
    row = photo_logic.get_photo(user_id, pic_id)
    j = _photo_json(row) if row else {"lat": None, "lng": None}
    return jsonify(ok=True, lat=j["lat"], lng=j["lng"])


@bp.put("/photos/<int:pic_id>/note")
def photo_note_save(pic_id: int):
    """사진 설명 저장 (있으면 고치고 없으면 새로 씀) — body: {"title", "note"}"""
    data = request.get_json(silent=True) or {}
    note, title = data.get("note"), data.get("title") or ""
    if not isinstance(note, str) or not isinstance(title, str):
        return jsonify(error="제목·본문은 문자열이어야 합니다."), 400
    try:
        note_id = note_logic.save_photo_note(g.user["user_id"], pic_id, note, title)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if note_id is None:
        # 남의 사진·없는 사진·휴지통 사진 (휴지통 사진의 기록은 보이지 않으므로 쓰지도 못하게 한다)
        return jsonify(error="설명을 쓸 수 없는 사진입니다. 휴지통에 있다면 먼저 복구해 주세요."), 404
    return jsonify(ok=True, note_id=note_id, html=md.render(note))


@bp.delete("/photos/<int:pic_id>/note")
def photo_note_delete(pic_id: int):
    """사진 설명 삭제 (use_yn → N)"""
    user_id = g.user["user_id"]
    current = note_logic.get_photo_note(user_id, pic_id)
    if current is None or not note_logic.delete_note(user_id, current["note_id"]):
        return jsonify(error="설명이 없습니다."), 404
    return jsonify(ok=True)


@bp.post("/markdown/preview")
def markdown_preview():
    """작성 중 미리보기: 마크다운 → 살균된 HTML (저장하지 않음, 일기·사진 설명 공용)"""
    data = request.get_json(silent=True) or {}
    note = data.get("note")
    return jsonify(html=md.render(note if isinstance(note, str) else ""))


# ============================================================
# 일기 (tracepic_daily — 하루 1건, 마크다운)
# ============================================================
@bp.get("/diary")
def diary_list():
    """
    연도별 일기 목록 (날짜 오름차순) + 기록이 있는 연도 목록
    - year 를 안 주면 가장 최근 연도. 카드에 쓸 요약문(excerpt)만 보내고 본문은 보내지 않는다.
    """
    user_id = g.user["user_id"]
    years = [{"year": r["year"], "count": r["count"]} for r in daily_logic.list_daily_years(user_id)]
    year = request.args.get("year") or (years[0]["year"] if years else str(date.today().year))
    if not (len(year) == 4 and year.isdigit()):
        return jsonify(error="연도 형식이 올바르지 않습니다."), 400

    rows = daily_logic.list_daily(user_id, f"{year}0101", f"{year}1231")
    entries = [
        {
            "base_dt": r["base_dt"],
            "title": r["title"] or "",
            "excerpt": md.excerpt(r["note"]),
            "updated_at": r["updated_at"].strftime("%Y-%m-%d %H:%M"),
        }
        for r in rows
    ]
    return jsonify(year=year, years=years, entries=entries)


@bp.get("/diary/<base_dt>")
def diary_get(base_dt: str):
    """일기 1건: 마크다운 원문 + 살균된 HTML + 그날 사진 썸네일"""
    user_id = g.user["user_id"]
    try:
        row = daily_logic.get_daily(user_id, base_dt)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if row is None:
        return jsonify(error="기록이 없습니다."), 404
    return jsonify(
        base_dt=row["base_dt"],
        title=row["title"] or "",
        note=row["note"],
        html=md.render(row["note"]),
        updated_at=row["updated_at"].strftime("%Y-%m-%d %H:%M"),
        photos=_day_photos(user_id, base_dt),
    )


@bp.put("/diary/<base_dt>")
def diary_save(base_dt: str):
    """
    일기 저장
    - body: {"mode": "create" | "update", "title", "note", "date"(update 에서 날짜를 옮길 때, YYYYMMDD)}
    - create: 새로 쓰기 — 그날 기록이 이미 있으면 409 (실수로 덮어쓰지 않게)
    - update: 고치기 — 기록이 없으면 404, date 로 옮길 날짜에 기록이 있으면 409
    - 응답의 base_dt 는 저장된 최종 날짜
    """
    data = request.get_json(silent=True) or {}
    note, title, new_dt = data.get("note"), data.get("title") or "", data.get("date") or None
    if not isinstance(note, str) or not isinstance(title, str) or not isinstance(new_dt or "", str):
        return jsonify(error="제목·본문·날짜는 문자열이어야 합니다."), 400
    user_id = g.user["user_id"]
    try:
        if data.get("mode") == "create":
            daily_logic.create_daily(user_id, base_dt, note, title)
            saved_dt = base_dt
        else:
            if daily_logic.update_daily(user_id, base_dt, note, title, new_dt) is None:
                return jsonify(error="고칠 기록이 없습니다. 이미 삭제되었을 수 있습니다."), 404
            saved_dt = new_dt or base_dt
    except daily_logic.DailyConflictError as e:
        return jsonify(error=str(e), conflict=True), 409
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, base_dt=saved_dt)


@bp.delete("/diary/<base_dt>")
def diary_delete(base_dt: str):
    """일기 삭제 (use_yn → N)"""
    try:
        deleted = daily_logic.delete_daily(g.user["user_id"], base_dt)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if not deleted:
        return jsonify(error="기록이 없습니다."), 404
    return jsonify(ok=True)


@bp.post("/diary/preview")
def diary_preview():
    """작성 중 미리보기: 마크다운 → 살균된 HTML (저장하지 않음)"""
    data = request.get_json(silent=True) or {}
    note = data.get("note")
    return jsonify(html=md.render(note if isinstance(note, str) else ""))


def _day_photos(user_id: str, base_dt: str) -> list[dict]:
    """그날 사진 목록 (촬영순, 지도와 같은 형식) — 일기 읽기 화면의 '그날 동선' 지도와 사진 줄에 쓴다"""
    rows = photo_logic.list_photos_by_date(user_id, base_dt)
    noted = note_logic.photo_ids_with_notes(user_id, [r["pic_id"] for r in rows])
    return [_photo_json(r, r["pic_id"] in noted) for r in rows]


# ============================================================
# 여행기 (날짜별 일기 + 사진 + 사진 설명)
# ============================================================
@bp.get("/story")
def story():
    """
    여행기 — 기간 안에서 사진이나 일기가 있는 날을 날짜 오름차순으로
    - days: [{"base_dt", "diary": {title, html, updated_at} | null,
              "photos": [지도와 같은 사진 JSON + "note": {title, html} | null]}]
    - 마크다운은 md.render 로 변환·살균해서 보낸다.
    """
    start, end = request.args.get("start", ""), request.args.get("end", "")
    try:
        days = story_logic.build_story(g.user["user_id"], start, end, _status_arg())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    out = []
    for d in days:
        daily = d["daily"]
        photos = []
        for p in d["photos"]:
            note = d["notes"].get(p["pic_id"])
            j = _photo_json(p, note is not None)
            j["note"] = {"title": note["title"] or "", "html": md.render(note["note"])} if note else None
            photos.append(j)
        out.append({
            "base_dt": d["base_dt"],
            "stats": _stats_json(calendar_logic.day_stats(d["photos"])),
            "diary": {
                "title": daily["title"] or "",
                "html": md.render(daily["note"]),
                "updated_at": daily["updated_at"].strftime("%Y-%m-%d %H:%M"),
            } if daily else None,
            "photos": photos,
        })
    return jsonify(days=out)


def _stats_json(st: dict) -> dict:
    """하루 통계 → JSON (시각은 HH:MM, 거리는 km 소수 1자리)"""
    return {
        "count": st["count"],
        "first": st["first"].strftime("%H:%M") if st["first"] else None,
        "last": st["last"].strftime("%H:%M") if st["last"] else None,
        "km": round(st["km"], 1),
    }


# ============================================================
# 달력 · 검색
# ============================================================
@bp.get("/calendar")
def calendar_month():
    """
    한 달 요약 — days: {base_dt: {count, first, last, km, has_diary, diary_title}} (사진이나 일기가 있는 날만)
    - totals: 그달 사진 수·사진 찍은 날 수·일기 수·이동 거리 합
    """
    try:
        r = calendar_logic.month_summary(g.user["user_id"], request.args.get("month", ""), _status_arg())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    days = {
        dt: {**_stats_json(d), "has_diary": d["has_diary"], "diary_title": d["diary_title"]}
        for dt, d in r["days"].items()
    }
    t = r["totals"]
    return jsonify(start=r["start"], end=r["end"], days=days,
                   totals={**t, "km": round(t["km"], 1)})


SEARCH_LIMIT = 100


@bp.get("/search")
def search():
    """
    일기·사진 설명 검색 (제목/본문, 대소문자 무시, 각각 최근 것부터 최대 SEARCH_LIMIT 건)
    - diaries: [{base_dt, title, snippet}], notes: [{pic_id, base_dt, photo_at, title, snippet, mini_url}]
    - snippet 은 검색어 주변 평문 (화면에서 검색어를 강조한다)
    """
    user_id = g.user["user_id"]
    q = request.args.get("q", "")
    try:
        dailies = daily_logic.search_daily(user_id, q, SEARCH_LIMIT)
        notes = note_logic.search_notes(user_id, q, SEARCH_LIMIT)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    keyword = " ".join(q.split())
    return jsonify(
        q=keyword,
        limit=SEARCH_LIMIT,
        diaries=[
            {"base_dt": d["base_dt"], "title": d["title"] or "", "snippet": md.snippet(d["note"], keyword)}
            for d in dailies
        ],
        notes=[
            {
                "pic_id": n["pic_id"], "base_dt": n["base_dt"],
                "photo_at": n["photo_at"].strftime("%Y-%m-%d %H:%M"),
                "title": n["title"] or "", "snippet": md.snippet(n["note"], keyword),
                "mini_url": url_for("photo.mini", pic_id=n["pic_id"]),
            }
            for n in notes
        ],
    )
