"""
EXIF 에서 촬영 시각과 GPS 좌표 꺼내기 (DB 와 무관)

- 촬영 시각: DateTimeOriginal → DateTimeDigitized → DateTime 순서로 찾는다.
  카메라에 기록된 '현지 시각' 그대로 쓴다 (시간대 변환 없음 → 여행지 시각으로 날짜가 나뉜다).
- GPS: 도·분·초(DMS) 값을 십진수 위도·경도로 바꾼다. 남위(S)·서경(W)은 음수.
- EXIF 가 없거나 깨져 있으면 None 을 돌려주고, 예외를 밖으로 던지지 않는다.
"""
from datetime import datetime

from PIL import ExifTags, Image

# EXIF 태그 번호
_TAG_DATETIME = 306                # IFD0: DateTime (파일 수정 시각인 경우가 많아 마지막 후보)
_TAG_DATETIME_ORIGINAL = 36867     # Exif IFD: 촬영 시각
_TAG_DATETIME_DIGITIZED = 36868    # Exif IFD: 디지털화 시각
_GPS_LAT_REF, _GPS_LAT, _GPS_LNG_REF, _GPS_LNG = 1, 2, 3, 4


def _parse_exif_datetime(value) -> datetime | None:
    """'YYYY:MM:DD HH:MM:SS' 문자열 → datetime (형식이 다르거나 0000:00:00 이면 None)"""
    if not value:
        return None
    text = value.decode(errors="ignore") if isinstance(value, bytes) else str(value)
    text = text.strip().rstrip("\x00")[:19]
    try:
        return datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _dms_to_decimal(dms, ref) -> float | None:
    """(도, 분, 초) + 방향(N/S/E/W) → 십진수 좌표"""
    try:
        deg, minute, sec = (float(v) for v in dms)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    value = deg + minute / 60 + sec / 3600
    ref = ref.decode(errors="ignore") if isinstance(ref, bytes) else str(ref or "")
    return -value if ref.strip().upper() in ("S", "W") else value


def extract_photo_at(img: Image.Image) -> datetime | None:
    """이미지 EXIF 의 촬영 시각 (없으면 None)"""
    try:
        exif = img.getexif()
        sub = exif.get_ifd(ExifTags.IFD.Exif)
        for value in (sub.get(_TAG_DATETIME_ORIGINAL), sub.get(_TAG_DATETIME_DIGITIZED),
                      exif.get(_TAG_DATETIME)):
            parsed = _parse_exif_datetime(value)
            if parsed:
                return parsed
    except Exception:  # noqa: BLE001 — 깨진 EXIF 는 '정보 없음'으로 처리
        pass
    return None


def extract_gps(img: Image.Image) -> tuple[float, float] | None:
    """이미지 EXIF 의 GPS (위도, 경도). 없거나 범위를 벗어나면 None"""
    try:
        gps = img.getexif().get_ifd(ExifTags.IFD.GPSInfo)
        if not gps or _GPS_LAT not in gps or _GPS_LNG not in gps:
            return None
        lat = _dms_to_decimal(gps[_GPS_LAT], gps.get(_GPS_LAT_REF, "N"))
        lng = _dms_to_decimal(gps[_GPS_LNG], gps.get(_GPS_LNG_REF, "E"))
    except Exception:  # noqa: BLE001
        return None
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if lat == 0 and lng == 0:  # 일부 기기는 GPS 를 못 잡으면 0,0 을 기록한다
        return None
    return lat, lng


# ============================================================
# 백업 내보내기용: 저장 파일(EXIF 없음)에 촬영 시각·GPS 를 다시 넣기
# ============================================================
def _dms(value: float) -> tuple[float, float, float]:
    """십진 도(33.459) → (도, 분, 초)"""
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    s = round(((value - d) * 60 - m) * 60, 4)
    return (float(d), float(m), s)


def with_exif(jpeg: bytes, photo_at, latitude=None, longitude=None) -> bytes:
    """
    JPEG 바이트에 촬영 시각(DateTimeOriginal)·GPS 를 담은 EXIF(APP1) 조각을 끼워 넣는다
    - 다시 인코딩하지 않으므로 화질이 그대로다 (SOI 바로 뒤에 APP1 을 붙임).
    - 백업 파일을 다른 사진 앱이나 TracePic 에 다시 올렸을 때 시각·위치가 살아 있게 하는 용도다.
      (저장소의 암호화 파일에는 여전히 EXIF 를 넣지 않는다)
    """
    if not jpeg.startswith(b"\xff\xd8"):
        return jpeg
    ex = Image.Exif()
    stamp = photo_at.strftime("%Y:%m:%d %H:%M:%S")
    ex[0x0132] = stamp                              # DateTime
    ex.get_ifd(0x8769)[36867] = stamp               # DateTimeOriginal
    if latitude is not None and longitude is not None:
        lat, lng = float(latitude), float(longitude)
        gps = ex.get_ifd(0x8825)
        gps[1], gps[2] = ("N" if lat >= 0 else "S"), _dms(lat)
        gps[3], gps[4] = ("E" if lng >= 0 else "W"), _dms(lng)
    payload = ex.tobytes()                          # b"Exif\0\0" + TIFF 데이터
    if len(payload) + 2 > 0xFFFF:
        return jpeg
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    return jpeg[:2] + segment + jpeg[2:]
