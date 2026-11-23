"""
업로드 이미지 열기 / 웹용 리사이징 (DB 와 무관)

- 확장자가 아니라 실제 파일 내용(Pillow 가 판별한 포맷)으로 허용 여부를 정한다.
- HEIC(아이폰 사진)는 pillow-heif 패키지가 설치되어 있을 때만 지원한다.
- 저장용 이미지는 EXIF 회전을 반영한 뒤 JPEG 로 다시 인코딩한다. WebP 로 올린 사진은 WebP 로 다시 인코딩한다(2026-11-23).
  이때 EXIF(GPS 포함)는 파일에 남기지 않는다 — 좌표는 DB 에만 둔다.
- 속도: JPEG 는 열 때 draft() 로 '필요한 크기 이상인 가장 작은 배율'(1/2, 1/4, 1/8)로 디코딩한다.
  2000만 화소 사진을 2048px 로 줄일 때 전체 해상도로 풀지 않아 시간·메모리가 크게 준다.
- 세 가지 크기(웹용·썸네일·마커용)는 normalize() 로 한 번 정리한 이미지에서 각각 만든다.
"""
import io
import math

from PIL import Image, ImageOps

# HEIC 지원: pillow-heif 가 있으면 Pillow 에 HEIF 열기 기능을 등록한다
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False

# Pillow 가 판별한 포맷 중 허용할 것
_ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "HEIF"}  # MPO: 일부 카메라의 JPEG 변형

THUMB_SIDE = 400  # 썸네일 긴 변(px) — 지도 팝업(200×150, 고해상도 화면 2배)·일기 사진 목록
MINI_SIDE = 128   # 마커용 정사각형 썸네일 한 변(px) — 지도 마커(48px)·촬영 순서 필름(60px)의 2배 여유


class ImageError(ValueError):
    """사용자에게 그대로 보여 줘도 되는 이미지 오류"""


def open_image(data: bytes, max_side: int | None = None) -> Image.Image:
    """
    바이트 → Pillow 이미지 (허용되지 않는 포맷·깨진 파일·초대형 이미지는 ImageError)
    - max_side 를 주면 JPEG 는 긴 변이 max_side 이상인 범위에서 가장 작게 디코딩한다(draft).
      EXIF(촬영 시각·GPS)는 디코딩 크기와 관계없이 그대로 읽을 수 있다.
    """
    try:
        img = Image.open(io.BytesIO(data))
        if max_side and img.format in ("JPEG", "MPO"):
            w, h = img.size
            scale = max_side / max(w, h)
            if scale < 1:
                # draft 는 요청한 크기 '이상'을 보장하는 가장 큰 축소 배율을 고른다
                img.draft(None, (math.ceil(w * scale), math.ceil(h * scale)))
        img.load()  # 여기서 실제로 디코딩해 깨진 파일을 걸러낸다
    except Image.DecompressionBombError as e:
        raise ImageError("이미지 해상도가 너무 큽니다.") from e
    except Exception as e:  # noqa: BLE001 — 원인과 상관없이 '읽을 수 없는 파일'로 안내
        hint = "" if HEIF_SUPPORTED else " (HEIC 는 현재 서버에서 지원하지 않습니다)"
        raise ImageError("이미지 파일을 읽을 수 없습니다." + hint) from e
    if img.format not in _ALLOWED_FORMATS:
        raise ImageError(f"지원하지 않는 이미지 형식입니다: {img.format}")
    return img


def normalize(img: Image.Image) -> Image.Image:
    """
    저장 전 정리: EXIF 회전을 픽셀에 반영하고 RGB 로 바꾼다 (투명 배경은 흰색으로 합성)
    - 결과에는 EXIF 가 없다 → 이 이미지로 만든 JPEG 에도 GPS 등이 남지 않는다.
    """
    img = ImageOps.exif_transpose(img)  # 세로 사진이 눕지 않도록 회전 정보를 픽셀에 반영
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _encode(img: Image.Image, quality: int, fmt: str = "JPEG") -> bytes:
    """저장 형식으로 인코딩 — JPEG(기본) 또는 WEBP(WebP 로 올린 사진은 WebP 그대로 둔다)"""
    buf = io.BytesIO()
    if fmt == "WEBP":
        img.save(buf, format="WEBP", quality=quality, method=4)
    else:
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def to_jpeg(img: Image.Image, max_side: int, quality: int, fmt: str = "JPEG") -> bytes:
    """normalize() 한 이미지 → 긴 변을 max_side 이하로 축소(확대는 안 함) → JPEG(또는 fmt) 바이트"""
    img = img.copy()   # thumbnail() 은 원본을 바꾸므로 복사해서 줄인다 (같은 이미지로 여러 크기를 만들기 위해)
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return _encode(img, quality, fmt)


def to_square_jpeg(img: Image.Image, side: int, quality: int, fmt: str = "JPEG") -> bytes:
    """normalize() 한 이미지 → 가운데를 정사각형으로 잘라 side×side → JPEG(또는 fmt) 바이트 (마커용)"""
    return _encode(ImageOps.fit(img, (side, side), Image.Resampling.LANCZOS), quality, fmt)
