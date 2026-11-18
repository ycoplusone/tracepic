"""
사진별 기록(tracepic_notes) 로직

- tracepic_notes 에는 user_id 가 없다 → 항상 tracepic_photos 와 pic_id 로 JOIN 해서 소유자를 확인한다.
- 기록이 달린 사진이 휴지통(D)·완전삭제(Z) 상태면 기록도 보이지 않는다.
- 삭제는 use_yn = 'N' 으로 표시만 한다 (행은 남김).
- updated_at 에 ON UPDATE 가 없으므로 수정할 때 NOW() 를 직접 넣는다.
- 저장되는 note 는 마크다운 원문이다. HTML 변환과 nh3 살균은 화면에 그릴 때 한다.
"""
from ..db import execute, fetch_all, fetch_one
from ..utils.dates import validate_base_dt
from ..utils.search import clean_keyword, like_contains
from .photo_logic import VISIBLE_STATUSES

USE_Y = "Y"   # 사용
USE_N = "N"   # 미사용(삭제)


def _owns_photo(user_id: str, pic_id: int) -> bool:
    """이 사진이 본인 소유이고 보이는 상태(A/B/C)인지"""
    return fetch_one(
        "SELECT 1 AS ok FROM tracepic_photos WHERE pic_id = %s AND user_id = %s AND status IN %s",
        (pic_id, user_id, VISIBLE_STATUSES),
    ) is not None


def _check_note(title: str | None, note: str) -> tuple[str | None, str]:
    """제목·본문 정리: 제목은 앞뒤 공백 제거 후 255자 이내(빈 값이면 NULL), 본문은 비어 있으면 ValueError"""
    title = (title or "").strip() or None
    if title and len(title) > 255:
        raise ValueError("제목은 255자까지 입력할 수 있습니다.")
    if not note or not note.strip():
        raise ValueError("기록 내용이 비어 있습니다.")
    return title, note


# ============================================================
# 생성
# ============================================================
def create_note(user_id: str, pic_id: int, note: str, title: str | None = None) -> int | None:
    """본인 사진에 기록 추가 → 새 note_id (사진이 없거나 남의 사진이면 None)"""
    title, note = _check_note(title, note)
    if not _owns_photo(user_id, pic_id):
        return None
    return execute(
        "INSERT INTO tracepic_notes (pic_id, title, note, use_yn) VALUES (%s, %s, %s, %s)",
        (pic_id, title, note, USE_Y),
    )


# ============================================================
# 조회
# ============================================================
def get_note(user_id: str, note_id: int) -> dict | None:
    """기록 1건 (본인 사진의 사용 중인 기록만)"""
    return fetch_one(
        """
        SELECT n.note_id, n.pic_id, n.title, n.note, n.created_at, n.updated_at
          FROM tracepic_notes  n
          JOIN tracepic_photos p ON p.pic_id = n.pic_id
         WHERE n.note_id = %s AND n.use_yn = %s
           AND p.user_id = %s AND p.status IN %s
        """,
        (note_id, USE_Y, user_id, VISIBLE_STATUSES),
    )


def list_notes_by_photo(user_id: str, pic_id: int) -> list[dict]:
    """사진 1장에 달린 기록 목록 (작성순)"""
    return fetch_all(
        """
        SELECT n.note_id, n.pic_id, n.title, n.note, n.created_at, n.updated_at
          FROM tracepic_notes  n
          JOIN tracepic_photos p ON p.pic_id = n.pic_id
         WHERE n.pic_id = %s AND n.use_yn = %s
           AND p.user_id = %s AND p.status IN %s
         ORDER BY n.created_at, n.note_id
        """,
        (pic_id, USE_Y, user_id, VISIBLE_STATUSES),
    )


def list_notes_by_date(user_id: str, base_dt: str) -> list[dict]:
    """하루치 사진들의 기록 목록 (사진 촬영 시각순 → 작성순) — 일별 화면용"""
    return fetch_all(
        """
        SELECT n.note_id, n.pic_id, n.title, n.note, n.created_at, n.updated_at,
               p.photo_at
          FROM tracepic_photos p
          JOIN tracepic_notes  n ON n.pic_id = p.pic_id
         WHERE p.base_dt = %s AND p.user_id = %s AND p.status IN %s
           AND n.use_yn = %s
         ORDER BY p.photo_at, p.pic_id, n.created_at, n.note_id
        """,
        (validate_base_dt(base_dt), user_id, VISIBLE_STATUSES, USE_Y),
    )


def photo_ids_with_notes(user_id: str, pic_ids) -> set[int]:
    """주어진 사진들 중 사용 중인 기록(설명)이 있는 pic_id 집합 — 지도에서 '설명 있음' 표시용 (쿼리 1번)"""
    pic_ids = tuple(pic_ids)
    if not pic_ids:
        return set()   # IN () 은 SQL 문법 오류라 빈 목록은 조회하지 않는다
    rows = fetch_all(
        """
        SELECT DISTINCT n.pic_id
          FROM tracepic_notes  n
          JOIN tracepic_photos p ON p.pic_id = n.pic_id
         WHERE n.pic_id IN %s AND n.use_yn = %s
           AND p.user_id = %s AND p.status IN %s
        """,
        (pic_ids, USE_Y, user_id, VISIBLE_STATUSES),
    )
    return {r["pic_id"] for r in rows}


def get_photo_note(user_id: str, pic_id: int) -> dict | None:
    """
    사진 '설명' — 사진 크게 보기 화면은 사진 1장에 설명 1건으로 쓴다 (가장 먼저 쓴 기록)
    - 테이블은 여러 건을 허용하므로, 나머지 기록이 있어도 지우지 않고 그대로 둔다.
    """
    notes = list_notes_by_photo(user_id, pic_id)
    return notes[0] if notes else None


def save_photo_note(user_id: str, pic_id: int, note: str, title: str | None = None) -> int | None:
    """
    사진 설명 저장 — 있으면 고치고 없으면 새로 쓴다 → note_id (사진이 없거나 남의 사진이면 None)
    """
    current = get_photo_note(user_id, pic_id)
    if current is None:
        return create_note(user_id, pic_id, note, title)
    update_note(user_id, current["note_id"], note, title)
    return current["note_id"]


# ============================================================
# 수정 / 삭제 (성공하면 True, 대상이 없거나 남의 기록이면 False)
# ============================================================
def update_note(user_id: str, note_id: int, note: str, title: str | None = None) -> bool:
    """기록 제목·본문 수정 (updated_at 갱신)"""
    title, note = _check_note(title, note)
    return execute(
        """
        UPDATE tracepic_notes  n
          JOIN tracepic_photos p ON p.pic_id = n.pic_id
           SET n.title = %s, n.note = %s, n.updated_at = NOW()
         WHERE n.note_id = %s AND n.use_yn = %s
           AND p.user_id = %s AND p.status IN %s
        """,
        (title, note, note_id, USE_Y, user_id, VISIBLE_STATUSES),
    ) > 0


def delete_note(user_id: str, note_id: int) -> bool:
    """기록 삭제 (use_yn → N, updated_at 갱신)"""
    return execute(
        """
        UPDATE tracepic_notes  n
          JOIN tracepic_photos p ON p.pic_id = n.pic_id
           SET n.use_yn = %s, n.updated_at = NOW()
         WHERE n.note_id = %s AND n.use_yn = %s
           AND p.user_id = %s AND p.status IN %s
        """,
        (USE_N, note_id, USE_Y, user_id, VISIBLE_STATUSES),
    ) > 0


def notes_for_photos(user_id: str, pic_ids) -> list[dict]:
    """여러 사진의 사용 중인 기록 전체 (사진별 작성순) — 쿼리 1번 (여행기·백업용)"""
    pic_ids = tuple(pic_ids)
    if not pic_ids:
        return []   # IN () 은 SQL 문법 오류라 빈 목록은 조회하지 않는다
    return fetch_all(
        """
        SELECT n.note_id, n.pic_id, n.title, n.note, n.created_at, n.updated_at
          FROM tracepic_notes  n
          JOIN tracepic_photos p ON p.pic_id = n.pic_id
         WHERE n.pic_id IN %s AND n.use_yn = %s
           AND p.user_id = %s AND p.status IN %s
         ORDER BY n.pic_id, n.created_at, n.note_id
        """,
        (pic_ids, USE_Y, user_id, VISIBLE_STATUSES),
    )


def first_notes_by_photo(user_id: str, pic_ids) -> dict[int, dict]:
    """
    여러 사진의 '설명'(사진마다 가장 먼저 쓴 사용 중인 기록)을 한 번에 → {pic_id: 기록}
    - get_photo_note 와 같은 기준(작성순 첫 건)이며, 사진마다 쿼리하지 않도록 한 번에 읽는다 (여행기 화면용).
    """
    first: dict[int, dict] = {}
    for r in notes_for_photos(user_id, pic_ids):
        first.setdefault(r["pic_id"], r)   # 사진별 첫 건만 남긴다
    return first


def search_notes(user_id: str, keyword: str, limit: int = 100) -> list[dict]:
    """
    사진 설명 검색 — 제목·본문에 검색어가 들어간 기록 (최근 촬영부터, 최대 limit 건)
    - 사진이 보이는 상태(A/B/C)인 기록만. 사진 1장에 기록이 여러 건이면 맞는 기록마다 나온다.
    """
    keyword = clean_keyword(keyword)
    pattern = like_contains(keyword)
    return fetch_all(
        """
        SELECT n.note_id, n.pic_id, n.title, n.note, p.base_dt, p.photo_at
          FROM tracepic_notes  n
          JOIN tracepic_photos p ON p.pic_id = n.pic_id
         WHERE p.user_id = %s AND p.status IN %s AND n.use_yn = %s
           AND (n.title LIKE %s OR n.note LIKE %s)
         ORDER BY p.photo_at DESC, n.note_id DESC
         LIMIT %s
        """,
        (user_id, VISIBLE_STATUSES, USE_Y, pattern, pattern, int(limit)),
    )
