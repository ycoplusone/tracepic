"""
날짜 관련 순수 함수 (DB 와 무관)

- base_dt : 촬영일을 'YYYYMMDD' 8자리 문자열로 저장한다 (tracepic_photos, tracepic_daily 공통).
- photo_at_from_filename : EXIF 에 촬영 시각이 없을 때 파일 이름에서 날짜·시각을 찾는다.
"""
import re
from datetime import date, datetime, timedelta


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


# 파일 이름 속 날짜(·시각) — 휴대폰·메신저·카메라가 흔히 쓰는 모양
#   IMG_20250503_142210.jpg, PXL_20250503_142210123.jpg(밀리초), KakaoTalk_20250503_142210123.jpg,
#   Screenshot_20250503-142210.png, DJI_20250503142210_0001.JPG, photo_2025-05-03_14-22-10.jpg,
#   Screenshot 2025-05-03 at 14.22.10.png, IMG-20250503-WA0001.jpg(날짜만)
# - 앞뒤가 숫자에 붙어 있으면 날짜로 보지 않는다 (긴 일련번호 속 숫자를 잘못 읽지 않게)
# - 시각 뒤 밀리초(최대 3자리)는 허용하고 버린다
_FILENAME_DT = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"
    r"(?:[ _T.-]?(?:at[ _])?([01]\d|2[0-3])[-_.:h]?([0-5]\d)[-_.:m]?([0-5]\d)\d{0,3})?(?!\d)",
    re.IGNORECASE,
)


def photo_at_from_filename(name: str | None, now: datetime | None = None) -> datetime | None:
    """
    파일 이름에서 촬영 시각 찾기 — 없거나 말이 안 되는 날짜(1990년 전, 내일 이후)면 None
    - 시각이 없고 날짜만 있으면 그날 00:00:00
    - 폴더 경로가 붙어 와도 마지막 이름만 본다
    """
    if not name:
        return None
    base = re.split(r"[\\/]", name)[-1]
    limit = (now or datetime.now()) + timedelta(days=1)
    for m in _FILENAME_DT.finditer(base):
        y, mo, d, h, mi, sec = m.groups()
        try:
            value = datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(sec or 0))
        except ValueError:          # 2월 30일 같은 날짜
            continue
        if datetime(1990, 1, 1) <= value <= limit:
            return value
    return None
