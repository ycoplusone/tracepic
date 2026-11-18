"""
일별 요약 기록(tracepic_daily) 로직

- 하루(base_dt)·사용자(user_id)당 사용 중(use_yn='Y')인 요약은 1건으로 운영한다.
  DB 에 유니크 제약은 없으므로 save_daily() 가 "있으면 수정, 없으면 추가"로 1건을 유지한다.
  (예전 데이터에 같은 날짜가 여러 건 있으면 가장 최근 daily_id 를 쓴다.)
  화면에서는 create_daily()(새로 쓰기) / update_daily()(고치기·날짜 옮기기)를 쓴다.
  두 함수는 대상 날짜에 이미 기록이 있으면 덮어쓰지 않고 DailyConflictError 를 던진다.
- 삭제는 use_yn = 'N' 으로 표시만 한다 (행은 남김).
- updated_at 에 ON UPDATE 가 없으므로 수정할 때 NOW() 를 직접 넣는다.
- 저장되는 note 는 마크다운 원문이다. HTML 변환과 nh3 살균은 화면에 그릴 때 한다.
"""
from ..db import execute, fetch_all, fetch_one, transaction
from ..utils.dates import validate_base_dt
from ..utils.search import clean_keyword, like_contains
from .note_logic import USE_N, USE_Y

_NOTE_MAX_BYTES = 65535  # note 컬럼이 TEXT(최대 65,535바이트)


class DailyConflictError(ValueError):
    """대상 날짜에 이미 기록이 있음 (하루 1건 규칙) — 라우트에서 409 로 응답한다"""


def _check_daily(title: str | None, note: str) -> tuple[str | None, str]:
    """제목·본문 정리: 제목은 앞뒤 공백 제거 후 255자 이내(빈 값이면 NULL), 본문은 비어 있으면 ValueError"""
    title = (title or "").strip() or None
    if title and len(title) > 255:
        raise ValueError("제목은 255자까지 입력할 수 있습니다.")
    if not note or not note.strip():
        raise ValueError("기록 내용이 비어 있습니다.")
    if len(note.encode("utf-8")) > _NOTE_MAX_BYTES:
        raise ValueError("기록이 너무 깁니다. (한글 기준 약 2만 자까지)")
    return title, note


# ============================================================
# 조회
# ============================================================
def get_daily(user_id: str, base_dt: str) -> dict | None:
    """그날의 요약 1건 (없으면 None) — 인덱스 (base_dt, user_id) 사용"""
    return fetch_one(
        """
        SELECT daily_id, base_dt, user_id, title, note, created_at, updated_at
          FROM tracepic_daily
         WHERE base_dt = %s AND user_id = %s AND use_yn = %s
         ORDER BY daily_id DESC
         LIMIT 1
        """,
        (validate_base_dt(base_dt), user_id, USE_Y),
    )


def list_daily(user_id: str, start_dt: str, end_dt: str) -> list[dict]:
    """기간(양끝 포함) 요약 목록 (날짜순)"""
    start_dt, end_dt = validate_base_dt(start_dt), validate_base_dt(end_dt)
    if start_dt > end_dt:
        raise ValueError("시작일이 종료일보다 늦습니다.")
    return fetch_all(
        """
        SELECT daily_id, base_dt, user_id, title, note, created_at, updated_at
          FROM tracepic_daily
         WHERE base_dt BETWEEN %s AND %s AND user_id = %s AND use_yn = %s
         ORDER BY base_dt, daily_id
        """,
        (start_dt, end_dt, user_id, USE_Y),
    )


def list_daily_years(user_id: str) -> list[dict]:
    """기록이 있는 연도와 연도별 기록 수 (최근 연도부터) — 일기 화면의 연도 선택용"""
    return fetch_all(
        """
        SELECT LEFT(base_dt, 4) AS year, COUNT(*) AS count
          FROM tracepic_daily
         WHERE user_id = %s AND use_yn = %s
         GROUP BY LEFT(base_dt, 4)
         ORDER BY year DESC
        """,
        (user_id, USE_Y),
    )


# ============================================================
# 저장 (생성 + 수정)
# ============================================================
def save_daily(user_id: str, base_dt: str, note: str, title: str | None = None) -> int:
    """
    그날의 요약 저장 → daily_id 반환
    - 이미 있으면 내용을 고치고(updated_at 갱신), 없으면 새로 만든다.
    - 같은 날짜를 동시에 두 번 저장해도 1건만 생기도록 트랜잭션 안에서 행 잠금(FOR UPDATE) 후 처리한다.
    """
    base_dt = validate_base_dt(base_dt)
    title, note = _check_daily(title, note)
    with transaction() as cur:
        cur.execute(
            """
            SELECT daily_id FROM tracepic_daily
             WHERE base_dt = %s AND user_id = %s AND use_yn = %s
             ORDER BY daily_id DESC
             LIMIT 1
               FOR UPDATE
            """,
            (base_dt, user_id, USE_Y),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE tracepic_daily SET title = %s, note = %s, updated_at = NOW() WHERE daily_id = %s",
                (title, note, row["daily_id"]),
            )
            return row["daily_id"]
        cur.execute(
            "INSERT INTO tracepic_daily (base_dt, user_id, title, note, use_yn) VALUES (%s, %s, %s, %s, %s)",
            (base_dt, user_id, title, note, USE_Y),
        )
        return cur.lastrowid


def _lock_active_id(cur, user_id: str, base_dt: str) -> int | None:
    """트랜잭션 안에서 그날 사용 중인 기록의 daily_id 를 잠그고(FOR UPDATE) 반환 (없으면 None)"""
    cur.execute(
        """
        SELECT daily_id FROM tracepic_daily
         WHERE base_dt = %s AND user_id = %s AND use_yn = %s
         ORDER BY daily_id DESC
         LIMIT 1
           FOR UPDATE
        """,
        (base_dt, user_id, USE_Y),
    )
    row = cur.fetchone()
    return row["daily_id"] if row else None


def create_daily(user_id: str, base_dt: str, note: str, title: str | None = None) -> int:
    """
    새 기록 작성 → daily_id
    - 그날 기록이 이미 있으면 덮어쓰지 않고 DailyConflictError
    """
    base_dt = validate_base_dt(base_dt)
    title, note = _check_daily(title, note)
    with transaction() as cur:
        if _lock_active_id(cur, user_id, base_dt) is not None:
            raise DailyConflictError("이날은 이미 기록이 있습니다.")
        cur.execute(
            "INSERT INTO tracepic_daily (base_dt, user_id, title, note, use_yn) VALUES (%s, %s, %s, %s, %s)",
            (base_dt, user_id, title, note, USE_Y),
        )
        return cur.lastrowid


def update_daily(user_id: str, base_dt: str, note: str, title: str | None = None,
                 new_base_dt: str | None = None) -> int | None:
    """
    기록 고치기 → daily_id (그날 기록이 없으면 None)
    - new_base_dt 를 주면 기록을 그 날짜로 옮긴다. 옮길 날짜에 이미 기록이 있으면 DailyConflictError.
    - 일기의 날짜만 바뀌고, 그날 올린 사진(tracepic_photos)은 그대로다.
    """
    base_dt = validate_base_dt(base_dt)
    new_base_dt = validate_base_dt(new_base_dt) if new_base_dt else base_dt
    title, note = _check_daily(title, note)
    with transaction() as cur:
        daily_id = _lock_active_id(cur, user_id, base_dt)
        if daily_id is None:
            return None
        if new_base_dt != base_dt and _lock_active_id(cur, user_id, new_base_dt) is not None:
            raise DailyConflictError("옮길 날짜에 이미 기록이 있습니다.")
        cur.execute(
            """
            UPDATE tracepic_daily
               SET base_dt = %s, title = %s, note = %s, updated_at = NOW()
             WHERE daily_id = %s
            """,
            (new_base_dt, title, note, daily_id),
        )
        return daily_id


# ============================================================
# 삭제
# ============================================================
def delete_daily(user_id: str, base_dt: str) -> bool:
    """그날의 요약 삭제 (use_yn → N, updated_at 갱신). 성공하면 True"""
    return execute(
        """
        UPDATE tracepic_daily SET use_yn = %s, updated_at = NOW()
         WHERE base_dt = %s AND user_id = %s AND use_yn = %s
        """,
        (USE_N, validate_base_dt(base_dt), user_id, USE_Y),
    ) > 0


def search_daily(user_id: str, keyword: str, limit: int = 100) -> list[dict]:
    """
    일기 검색 — 제목·본문에 검색어가 들어간 기록 (최근 날짜부터, 최대 limit 건)
    - 검색어는 utils/search 로 정리·이스케이프해 LIKE 패턴으로 바인딩한다 (대소문자는 콜레이션이 무시).
    """
    keyword = clean_keyword(keyword)
    pattern = like_contains(keyword)
    return fetch_all(
        """
        SELECT daily_id, base_dt, title, note, updated_at
          FROM tracepic_daily
         WHERE user_id = %s AND use_yn = %s
           AND (title LIKE %s OR note LIKE %s)
         ORDER BY base_dt DESC, daily_id DESC
         LIMIT %s
        """,
        (user_id, USE_Y, pattern, pattern, int(limit)),
    )
