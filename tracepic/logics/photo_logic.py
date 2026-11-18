"""
사진(tracepic_photos) 로직

- 이 모듈은 사진 '메타데이터'만 다룬다. 이미지 파일 암호화·저장·삭제는 utils(crypto, image)와 라우트가 맡는다.
- 모든 조회·수정에 user_id 조건을 함께 걸어 본인 사진만 다룬다 (남의 pic_id 면 None / False).
- 삭제는 행을 지우지 않고 status 만 바꾼다 (D: 휴지통 → 복구 가능, Z: 완전삭제 → 복구 불가).
- status 비교는 테이블 콜레이션(utf8mb4_unicode_ci)이 대소문자를 구분하지 않으므로 'a'/'A' 어느 쪽이 저장돼 있어도 동작한다.
  새로 쓰는 값은 DB 기본값('A')에 맞춰 대문자로 저장한다. (대소문자 통일은 미결정 — CLAUDE.md 참고)
"""
from datetime import datetime
from decimal import Decimal

from ..db import execute, fetch_all, fetch_one
from ..utils.dates import to_base_dt, validate_base_dt

# ── status 코드 ──
STATUS_PUBLIC = "A"    # 완전공유
STATUS_PARTIAL = "B"   # 부분공유
STATUS_PRIVATE = "C"   # 나만 보기
STATUS_DELETED = "D"   # 삭제 (휴지통, 복구 가능)
STATUS_PURGED = "Z"    # 완전삭제 (복구 불가, 파일도 지울 대상)

# 사용자가 직접 고를 수 있는 공개 범위 = 화면에 보이는 사진
VISIBLE_STATUSES = (STATUS_PUBLIC, STATUS_PARTIAL, STATUS_PRIVATE)
# 화면에 보여 줄 상태 이름 (표시 순서: 나만 → 부분 → 전체 → 휴지통)
STATUS_LABELS = {
    STATUS_PRIVATE: "나만 보기",
    STATUS_PARTIAL: "부분 공유",
    STATUS_PUBLIC: "전체 공유",
    STATUS_DELETED: "휴지통",
}
# 본인 조회 시 휴지통까지 포함할 때 (지도의 상태 조건에서 고를 수 있는 값이기도 하다)
VISIBLE_OR_DELETED = VISIBLE_STATUSES + (STATUS_DELETED,)


# ============================================================
# 검증 헬퍼
# ============================================================
def _check_coord(latitude, longitude) -> tuple[Decimal | None, Decimal | None]:
    """
    위도·경도 검증 → (위도, 경도)
    - 둘 다 None 이면 GPS 정보 없음으로 보고 NULL 로 저장한다 (지도에서 제외).
    - 하나만 있거나 범위를 벗어나면 ValueError
    """
    if latitude is None and longitude is None:
        return None, None
    if latitude is None or longitude is None:
        raise ValueError("위도와 경도는 함께 입력해야 합니다.")
    lat, lng = Decimal(str(latitude)), Decimal(str(longitude))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError(f"좌표 범위를 벗어났습니다: ({lat}, {lng})")
    # DB 컬럼(소수점 7자리)에 맞춰 반올림
    step = Decimal("0.0000001")
    return lat.quantize(step), lng.quantize(step)


def _check_status(status: str) -> str:
    """사용자가 지정할 수 있는 status(A/B/C)인지 확인 → 대문자로 반환"""
    status = (status or "").upper()
    if status not in VISIBLE_STATUSES:
        raise ValueError(f"허용되지 않는 status 입니다: {status!r}")
    return status


def check_status_filter(statuses) -> tuple[str, ...]:
    """
    조회 조건으로 받은 상태 목록 검증 → 대문자 튜플 (SQL 의 IN %s 에 그대로 바인딩)
    - A/B/C/D 만 고를 수 있다. 완전삭제(Z)는 조회 대상이 아니다. 비어 있으면 ValueError
    """
    result = tuple(dict.fromkeys((s or "").strip().upper() for s in statuses if (s or "").strip()))
    if not result:
        raise ValueError("상태를 하나 이상 골라야 합니다.")
    bad = [s for s in result if s not in VISIBLE_OR_DELETED]
    if bad:
        raise ValueError(f"허용되지 않는 상태 조건입니다: {', '.join(bad)}")
    return result


def has_location(photo: dict) -> bool:
    """지도에 찍을 수 있는 좌표가 있는지 (NULL 이나 0,0 은 GPS 없음으로 본다)"""
    lat, lng = photo.get("latitude"), photo.get("longitude")
    return lat is not None and lng is not None and not (lat == 0 and lng == 0)


# ============================================================
# 생성
# ============================================================
def create_photo(user_id: str, file_path: str, photo_at: datetime,
                 latitude=None, longitude=None,
                 original_file_name: str | None = None,
                 status: str = STATUS_PRIVATE) -> int:
    """
    사진 메타데이터 저장 → 새 pic_id 반환
    - base_dt 는 촬영 시각(photo_at)에서 만든다.
    - 공개 범위 기본값은 '나만(C)' — 업로드 직후 실수로 공개되지 않게 한다.
    """
    lat, lng = _check_coord(latitude, longitude)
    return execute(
        """
        INSERT INTO tracepic_photos
               (user_id, base_dt, original_file_name, file_path,
                photo_at, latitude, longitude, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, to_base_dt(photo_at), (original_file_name or "")[:255] or None,
         file_path, photo_at, lat, lng, _check_status(status)),
    )


# ============================================================
# 조회
# ============================================================
def get_photo(user_id: str, pic_id: int, include_deleted: bool = False) -> dict | None:
    """
    본인 사진 1건 조회 (없거나 남의 사진이면 None)
    - 기본은 A/B/C 만. include_deleted=True 면 휴지통(D)도 포함한다. 완전삭제(Z)는 항상 제외.
    """
    statuses = VISIBLE_OR_DELETED if include_deleted else VISIBLE_STATUSES
    return fetch_one(
        """
        SELECT pic_id, user_id, base_dt, original_file_name, file_path,
               photo_at, latitude, longitude, status, created_at
          FROM tracepic_photos
         WHERE pic_id = %s AND user_id = %s AND status IN %s
        """,
        (pic_id, user_id, statuses),
    )


def list_photos_by_date(user_id: str, base_dt: str) -> list[dict]:
    """하루치 사진 목록 (촬영 시각순) — 인덱스 (base_dt, user_id) 사용"""
    return fetch_all(
        """
        SELECT pic_id, user_id, base_dt, original_file_name, file_path,
               photo_at, latitude, longitude, status, created_at
          FROM tracepic_photos
         WHERE base_dt = %s AND user_id = %s AND status IN %s
         ORDER BY photo_at, pic_id
        """,
        (validate_base_dt(base_dt), user_id, VISIBLE_STATUSES),
    )


def list_photos_by_range(user_id: str, start_dt: str, end_dt: str,
                         only_located: bool = False,
                         statuses=VISIBLE_STATUSES) -> list[dict]:
    """
    기간(start_dt ~ end_dt, 양끝 포함) 사진 목록 (촬영 시각순)
    - only_located=True 면 좌표가 있는 사진만 돌려준다 (지도 표시용).
    - statuses: 상태 조건 (기본 A/B/C, 휴지통 D 도 고를 수 있음)
    """
    statuses = check_status_filter(statuses)
    start_dt, end_dt = validate_base_dt(start_dt), validate_base_dt(end_dt)
    if start_dt > end_dt:
        raise ValueError("시작일이 종료일보다 늦습니다.")
    rows = fetch_all(
        """
        SELECT pic_id, user_id, base_dt, original_file_name, file_path,
               photo_at, latitude, longitude, status, created_at
          FROM tracepic_photos
         WHERE base_dt BETWEEN %s AND %s AND user_id = %s AND status IN %s
         ORDER BY photo_at, pic_id
        """,
        (start_dt, end_dt, user_id, statuses),
    )
    if only_located:
        # 조건에 따라 SQL 을 조립하지 않도록 좌표 필터는 파이썬에서 적용한다
        rows = [r for r in rows if has_location(r)]
    return rows


def list_map_photos(user_id: str, start_dt: str, end_dt: str,
                    statuses=VISIBLE_STATUSES) -> dict:
    """
    지도 화면용: 기간·상태 조건에 맞는 사진 전체(촬영 시각순)와 위치 없는 사진 수
    → {"photos": [...촬영 시각순, 위치 없는 사진 포함...], "unlocated_count": n}
    - 위치 없는 사진도 돌려주는 이유: 지도에는 못 찍어도 촬영 순서 목록에는 보여 주기 위해서다.
    """
    rows = list_photos_by_range(user_id, start_dt, end_dt, statuses=statuses)
    return {"photos": rows, "unlocated_count": sum(1 for r in rows if not has_location(r))}


def list_photo_dates(user_id: str, statuses=VISIBLE_STATUSES,
                     start_dt: str | None = None, end_dt: str | None = None) -> list[dict]:
    """
    사진이 있는 날짜 목록과 날짜별 장수 (최근 날짜부터) — 상태 조건(statuses)에 맞는 사진만 센다
    - start_dt·end_dt 를 주면 그 기간(양끝 포함)만, 안 주면 전체 기간
    """
    statuses = check_status_filter(statuses)
    if (start_dt is None) != (end_dt is None):
        raise ValueError("시작일과 종료일은 함께 입력해야 합니다.")
    if start_dt is None:
        # SQL 을 조건에 따라 조립하지 않도록, 전체 기간은 모든 YYYYMMDD 를 덮는 범위로 대신한다
        start_dt, end_dt = "00000000", "99999999"
    else:
        start_dt, end_dt = validate_base_dt(start_dt), validate_base_dt(end_dt)
        if start_dt > end_dt:
            raise ValueError("시작일이 종료일보다 늦습니다.")
    return fetch_all(
        """
        SELECT base_dt, COUNT(*) AS photo_count
          FROM tracepic_photos
         WHERE base_dt BETWEEN %s AND %s AND user_id = %s AND status IN %s
         GROUP BY base_dt
         ORDER BY base_dt DESC
        """,
        (start_dt, end_dt, user_id, statuses),
    )


def list_deleted_photos(user_id: str) -> list[dict]:
    """휴지통(D) 사진 목록 (최근 업로드부터)"""
    return fetch_all(
        """
        SELECT pic_id, user_id, base_dt, original_file_name, file_path,
               photo_at, latitude, longitude, status, created_at
          FROM tracepic_photos
         WHERE user_id = %s AND status = %s
         ORDER BY created_at DESC, pic_id DESC
        """,
        (user_id, STATUS_DELETED),
    )


# ============================================================
# 수정 (모두 성공하면 True, 대상이 없거나 남의 사진이면 False)
# ============================================================
def update_location(user_id: str, pic_id: int, latitude, longitude) -> bool:
    """좌표 수정 (EXIF 에 GPS 가 없을 때 지도에서 직접 찍는 용도). None, None 이면 좌표 삭제"""
    lat, lng = _check_coord(latitude, longitude)
    return execute(
        """
        UPDATE tracepic_photos SET latitude = %s, longitude = %s
         WHERE pic_id = %s AND user_id = %s AND status IN %s
        """,
        (lat, lng, pic_id, user_id, VISIBLE_STATUSES),
    ) > 0


def update_photo_at(user_id: str, pic_id: int, photo_at: datetime) -> bool:
    """촬영 시각 수정 — 날짜가 바뀔 수 있으므로 base_dt 도 함께 바꾼다"""
    return execute(
        """
        UPDATE tracepic_photos SET photo_at = %s, base_dt = %s
         WHERE pic_id = %s AND user_id = %s AND status IN %s
        """,
        (photo_at, to_base_dt(photo_at), pic_id, user_id, VISIBLE_STATUSES),
    ) > 0


def update_status(user_id: str, pic_id: int, status: str) -> bool:
    """공개 범위(A/B/C) 변경"""
    return execute(
        """
        UPDATE tracepic_photos SET status = %s
         WHERE pic_id = %s AND user_id = %s AND status IN %s
        """,
        (_check_status(status), pic_id, user_id, VISIBLE_STATUSES),
    ) > 0


def change_status(user_id: str, pic_id: int, status: str) -> bool:
    """
    사진 화면의 상태 변경 — A/B/C(공개 범위)와 D(휴지통) 사이를 자유롭게 오간다
    - 휴지통(D) 사진을 A/B/C 로 바꾸면 복구, A/B/C 를 D 로 바꾸면 휴지통 이동이다.
    - 완전삭제(Z)는 여기서 할 수 없다 (purge_photo 로만, 파일 삭제가 함께 필요하므로).
    """
    status = (status or "").upper()
    if status not in VISIBLE_OR_DELETED:
        raise ValueError(f"허용되지 않는 status 입니다: {status!r}")
    row = fetch_one(
        "SELECT status FROM tracepic_photos WHERE pic_id = %s AND user_id = %s AND status IN %s",
        (pic_id, user_id, VISIBLE_OR_DELETED),
    )
    if not row:
        return False
    if row["status"].upper() == status:
        return True  # 이미 그 상태 (MySQL 은 값이 같으면 변경 행 수를 0 으로 돌려주므로 따로 처리)
    return execute(
        """
        UPDATE tracepic_photos SET status = %s
         WHERE pic_id = %s AND user_id = %s AND status IN %s
        """,
        (status, pic_id, user_id, VISIBLE_OR_DELETED),
    ) > 0


# ============================================================
# 삭제 / 복구
# ============================================================
def delete_photo(user_id: str, pic_id: int) -> bool:
    """휴지통으로 이동 (status → D)"""
    return execute(
        """
        UPDATE tracepic_photos SET status = %s
         WHERE pic_id = %s AND user_id = %s AND status IN %s
        """,
        (STATUS_DELETED, pic_id, user_id, VISIBLE_STATUSES),
    ) > 0


def restore_photo(user_id: str, pic_id: int, status: str = STATUS_PRIVATE) -> bool:
    """휴지통(D)에서 복구 — 공개 범위는 기본 '나만(C)'"""
    return execute(
        """
        UPDATE tracepic_photos SET status = %s
         WHERE pic_id = %s AND user_id = %s AND status = %s
        """,
        (_check_status(status), pic_id, user_id, STATUS_DELETED),
    ) > 0


def purge_photo(user_id: str, pic_id: int) -> str | None:
    """
    완전삭제 (휴지통(D)에 있는 사진만 가능, status → Z)
    - 성공하면 지워야 할 암호화 파일 경로(file_path)를 돌려준다. 실제 파일 삭제는 호출한 쪽이 한다.
    - 행은 남겨 두므로 연결된 기록(notes)이 고아가 되지 않는다.
    """
    row = fetch_one(
        "SELECT file_path FROM tracepic_photos WHERE pic_id = %s AND user_id = %s AND status = %s",
        (pic_id, user_id, STATUS_DELETED),
    )
    if not row:
        return None
    changed = execute(
        """
        UPDATE tracepic_photos SET status = %s
         WHERE pic_id = %s AND user_id = %s AND status = %s
        """,
        (STATUS_PURGED, pic_id, user_id, STATUS_DELETED),
    )
    return row["file_path"] if changed else None
