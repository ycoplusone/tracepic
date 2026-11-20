"""
사진 파일 업로드 / 읽기 로직 (암호화 파일 + tracepic_photos 메타데이터)

업로드 흐름 (save_upload)
  1. 이미지 열기·포맷 확인 (utils/image)
  2. EXIF 에서 촬영 시각·GPS 추출 (utils/exif). 촬영 시각이 없으면 브라우저가 보낸 파일 수정 시각 → 업로드 시각 순으로 대신 쓴다.
  3. 웹용 JPEG(긴 변 IMAGE_MAX_SIDE) + 썸네일(긴 변 400px) + 마커용(128px 정사각형) 만들기 — EXIF 는 파일에 남기지 않는다
  4. 사용자별 키(MASTER_SALT + user_id)로 암호화해 STORAGE_DIR/{사용자폴더}/{base_dt}/{타임스탬프}.enc 로 저장 (utils/crypto)
     타임스탬프(time_ns)는 파일 이름이 겹치지 않게 하는 용도이며 키에는 쓰이지 않는다.
  5. tracepic_photos 에 메타데이터 INSERT (photo_logic.create_photo). 실패하면 방금 쓴 파일을 지운다.

- DB 의 file_path 에는 STORAGE_DIR 기준 상대 경로를 저장한다 (서버를 옮겨도 STORAGE_DIR 만 바꾸면 된다).
- 썸네일은 '.thumb.enc', 마커용은 '.mini.enc' 를 붙인 파일이다 (DB 컬럼 없이 이름 규칙으로 찾는다).
  마커용 파일이 없는 예전 사진은 처음 요청될 때 썸네일로 만들어 저장한다 (read_image).
- 저장된 파일은 바뀌지 않는다 → 응답에 ETag 와 긴 캐시 기간을 붙일 수 있다 (image_ref 의 etag).
- 원본 파일은 보관하지 않는다 (IMAGE_MAX_SIDE 로 줄인 JPEG 만 저장).

동영상 (save_video_upload, 2026-11-20)
- 동영상은 보관하지 않고 3~7초 구간만 움직이는 WebP 3개(image 720p / thumb 400 / mini 128)로 만들어
  사진과 똑같은 자리(.enc / .thumb.enc / .mini.enc)에 저장한다 → DB 구조·화면은 사진과 같다(<img> 로 재생됨).
- 사진인지 클립인지는 복호화한 내용(WebP 여부)으로 구분한다 (utils/video.is_webp).
- ffmpeg 가 파일을 앞뒤로 오가며 읽어야 해서 업로드 영상을 STORAGE_DIR/.tmp(0700)에 잠깐 쓰고, 변환이 끝나면 바로 지운다.
"""
import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from flask import current_app

from ..utils import crypto, exif, image, video
from . import photo_logic

_ENC_SUFFIX = ".enc"
# 크기별 파일 이름 끝 — image: 웹용(크게 보기), thumb: 썸네일, mini: 마커용 정사각형
_SUFFIXES = {"image": _ENC_SUFFIX, "thumb": ".thumb.enc", "mini": ".mini.enc"}
KINDS = tuple(_SUFFIXES)
_SAFE_DIR = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}")


@dataclass
class UploadResult:
    """업로드 결과 (라우트가 JSON 으로 바꿔 응답한다)"""
    pic_id: int
    base_dt: str
    photo_at: datetime
    time_source: str          # 'exif' | 'meta'(동영상) | 'file' | 'upload' — 촬영 시각을 어디서 얻었는지
    latitude: float | None
    longitude: float | None


# ============================================================
# 경로 헬퍼
# ============================================================
def _user_dir_name(user_id: str) -> str:
    """사용자 폴더 이름 — 파일 시스템에 안전한 아이디면 그대로, 아니면 해시값 (경로 조작 방지)"""
    if _SAFE_DIR.fullmatch(user_id):
        return user_id
    return "u_" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def _abs_path(rel_path: str) -> Path:
    """DB 의 상대 경로 → 절대 경로 (STORAGE_DIR 밖을 가리키면 ValueError)"""
    root = current_app.config["STORAGE_DIR"]
    path = (root / rel_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("저장소 밖의 경로입니다.")
    return path


def _variant_rel_path(rel_path: str, kind: str) -> str:
    """DB 경로 'a/b/123.enc' → 크기별 경로 (thumb: 'a/b/123.thumb.enc', mini: 'a/b/123.mini.enc')"""
    return rel_path[: -len(_ENC_SUFFIX)] + _SUFFIXES[kind]


def _write_private(path: Path, data: bytes) -> None:
    """권한 0600 으로 임시 파일에 쓴 뒤 이름을 바꿔, 중간에 실패해도 반쯤 쓴 파일이 남지 않게 한다"""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _make_dirs(path: Path) -> None:
    """상위 폴더를 권한 0700 으로 만든다"""
    root = current_app.config["STORAGE_DIR"]
    for parent in reversed(path.relative_to(root).parents):
        d = root / parent
        if not d.exists():
            d.mkdir(mode=0o700)


# ============================================================
# 업로드
# ============================================================
def save_upload(user_id: str, data: bytes, original_file_name: str | None,
                client_time: datetime | None = None,
                status: str = photo_logic.STATUS_PRIVATE,
                gps_hint: tuple[float, float] | None = None) -> UploadResult:
    """
    업로드된 이미지 1장을 암호화 저장하고 DB 에 등록
    - gps_hint: 파일에 GPS 가 없을 때만 쓰는 보조 좌표 (앱이 원본에서 따로 읽어 보낸 값)
    - 이미지 문제는 image.ImageError, 잘못된 입력은 ValueError 로 알린다 (메시지는 사용자에게 보여 줘도 됨).
    """
    cfg = current_app.config
    img = image.open_image(data, max_side=cfg["IMAGE_MAX_SIDE"])   # JPEG 는 필요한 크기만큼만 디코딩

    # ── 촬영 시각 / 좌표 ──
    photo_at, source = exif.extract_photo_at(img), "exif"
    if photo_at is None and client_time is not None:
        photo_at, source = client_time, "file"
    if photo_at is None:
        photo_at, source = datetime.now().replace(microsecond=0), "upload"
    gps = exif.extract_gps(img) or gps_hint
    lat, lng = gps if gps else (None, None)

    # ── 웹용 JPEG + 썸네일 + 마커용 (회전·색 정리는 한 번만) ──
    rgb = image.normalize(img)
    jpegs = {
        "image": image.to_jpeg(rgb, cfg["IMAGE_MAX_SIDE"], cfg["IMAGE_JPEG_QUALITY"]),
        "thumb": image.to_jpeg(rgb, image.THUMB_SIDE, 80),
        "mini": image.to_square_jpeg(rgb, image.MINI_SIDE, 75),
    }
    return _store(user_id, jpegs, photo_at, source, lat, lng, original_file_name, status)


def save_video_upload(user_id: str, src_path: Path, original_file_name: str | None,
                      client_time: datetime | None = None, tz_minutes: int | None = None,
                      status: str = photo_logic.STATUS_PRIVATE,
                      gps_hint: tuple[float, float] | None = None) -> UploadResult:
    """
    동영상 → 3~7초 구간 움직이는 WebP 3개를 암호화 저장하고 DB 에 등록 (동영상 자체는 저장하지 않음)
    - src_path 는 호출한 쪽이 STORAGE_DIR/.tmp 에 잠깐 쓴 업로드 파일이다. 지우는 것도 호출한 쪽이 한다.
    - 촬영 시각: 영상 메타데이터 → 브라우저가 보낸 파일 수정 시각 → 업로드 시각. 위치: 영상 메타데이터(없으면 NULL).
    - 동영상 문제는 video.VideoError 로 알린다 (메시지는 사용자에게 보여 줘도 됨).
    """
    ffmpeg = video.find_ffmpeg(current_app.config["FFMPEG_PATH"] or None)
    if ffmpeg is None:
        raise video.VideoError("서버에 ffmpeg 가 없어 동영상을 올릴 수 없습니다.")
    duration, tags = video.probe(ffmpeg, src_path)

    photo_at, source = video.parse_time(tags, tz_minutes), "meta"
    if photo_at is None and client_time is not None:
        photo_at, source = client_time, "file"
    if photo_at is None:
        photo_at, source = datetime.now().replace(microsecond=0), "upload"
    gps = video.parse_location(tags) or gps_hint      # 메타데이터에 없을 때만 앱이 보낸 좌표
    lat, lng = gps if gps else (None, None)

    start, length = video.clip_window(duration)
    frames = video.extract_frames(ffmpeg, src_path, start, length)
    webps = {kind: video.to_webp(frames, kind) for kind in KINDS}
    return _store(user_id, webps, photo_at, source, lat, lng, original_file_name, status)


def temp_upload_path() -> Path:
    """업로드 동영상을 잠깐 둘 경로 — STORAGE_DIR/.tmp (0700, 웹으로 열리지 않음). 쓰고 나면 호출한 쪽이 지운다"""
    root = current_app.config["STORAGE_DIR"]
    tmp_dir = root / ".tmp"
    tmp_dir.mkdir(mode=0o700, exist_ok=True)
    return tmp_dir / f"{time.time_ns()}_{os.getpid()}.upload"


def _store(user_id: str, files: dict, photo_at: datetime, source: str,
           lat: float | None, lng: float | None, original_file_name: str | None, status: str) -> UploadResult:
    """크기별 바이트(image/thumb/mini)를 암호화 저장 → tracepic_photos INSERT (실패하면 쓴 파일을 지움)"""
    cfg = current_app.config
    base_dt = photo_at.strftime("%Y%m%d")
    folder = Path(_user_dir_name(user_id)) / base_dt
    file_ts = str(time.time_ns())
    while (cfg["STORAGE_DIR"] / folder / (file_ts + _ENC_SUFFIX)).exists():  # 극히 드문 이름 충돌 대비
        file_ts = str(time.time_ns())
    rel_path = (folder / (file_ts + _ENC_SUFFIX)).as_posix()
    paths = {kind: _abs_path(_variant_rel_path(rel_path, kind)) for kind in KINDS}

    _make_dirs(paths["image"])
    salt = cfg["MASTER_SALT"]
    try:
        for kind in KINDS:
            _write_private(paths[kind], crypto.encrypt_bytes(files[kind], salt, user_id))
        pic_id = photo_logic.create_photo(
            user_id, rel_path, photo_at, lat, lng,
            original_file_name=_clean_file_name(original_file_name), status=status,
        )
    except Exception:
        # DB 등록에 실패하면 주인 없는 파일이 남지 않도록 지운다
        for p in paths.values():
            p.unlink(missing_ok=True)
        raise

    return UploadResult(pic_id, base_dt, photo_at, source, lat, lng)


def _clean_file_name(name: str | None) -> str | None:
    """원본 파일명은 표시용으로만 저장 — 경로 부분과 제어 문자를 지운다"""
    if not name:
        return None
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:255] or None


# ============================================================
# 읽기 / 파일 삭제
# ============================================================
@dataclass
class ImageRef:
    """본인 사진 파일 1개를 가리키는 정보 (소유 확인을 마친 상태)"""
    kind: str        # image | thumb | mini
    rel_path: str    # DB 의 file_path (웹용 기준 경로)
    owner: str       # 키 유도에 쓰는 user_id (DB 값)
    etag: str        # 파일 내용이 바뀌지 않으므로 경로·종류로 만든 고정값


def image_ref(user_id: str, pic_id: int, kind: str = "image") -> ImageRef | None:
    """
    본인 사진이면 파일 정보, 아니면 None — 파일은 읽지 않는다
    - 브라우저 캐시 확인(If-None-Match)에 맞으면 복호화 없이 304 로 끝낼 수 있게 읽기와 나눴다.
    - 휴지통(D) 사진도 볼 수 있다 (복구 여부를 판단할 수 있게).
    """
    if kind not in _SUFFIXES:
        raise ValueError(f"알 수 없는 이미지 종류: {kind}")
    row = photo_logic.get_photo(user_id, pic_id, include_deleted=True)
    if not row:
        return None
    digest = hashlib.sha256(f"{row['file_path']}|{kind}".encode("utf-8")).hexdigest()[:20]
    return ImageRef(kind, row["file_path"], row["user_id"], f"{kind}-{digest}")


def read_image(ref: ImageRef) -> bytes | None:
    """파일을 읽어 복호화한 JPEG 바이트 (파일이 없거나 복호화에 실패하면 None)"""
    salt = current_app.config["MASTER_SALT"]
    rel = _variant_rel_path(ref.rel_path, ref.kind)
    token = _read_file(rel)
    if token is None and ref.kind == "mini":
        return _make_mini_from_thumb(ref)          # 마커용 파일이 생기기 전에 올린 사진
    if token is None:
        current_app.logger.warning("사진 파일 없음: path=%s", rel)
        return None
    try:
        # 키 유도에는 DB 에 저장된 user_id 를 쓴다 (MASTER_SALT + user_id)
        return crypto.decrypt_bytes(token, salt, ref.owner)
    except crypto.InvalidToken:
        current_app.logger.error("복호화 실패(MASTER_SALT 변경 또는 파일 손상): path=%s", rel)
        return None


def _read_file(rel: str) -> bytes | None:
    try:
        return _abs_path(rel).read_bytes()
    except (OSError, ValueError):
        return None


def _make_mini_from_thumb(ref: ImageRef) -> bytes | None:
    """썸네일로 마커용 파일을 만들어 저장하고 그 JPEG 를 돌려준다 (실패하면 썸네일을 그대로 돌려준다)"""
    thumb = read_image(ImageRef("thumb", ref.rel_path, ref.owner, ""))
    if thumb is None:
        return None
    try:
        mini = image.to_square_jpeg(image.normalize(image.open_image(thumb)), image.MINI_SIDE, 75)
        _write_private(_abs_path(_variant_rel_path(ref.rel_path, "mini")),
                       crypto.encrypt_bytes(mini, current_app.config["MASTER_SALT"], ref.owner))
        return mini
    except Exception:  # noqa: BLE001 — 마커용 파일은 없어도 썸네일로 대신할 수 있다
        current_app.logger.exception("마커용 썸네일 생성 실패: path=%s", ref.rel_path)
        return thumb


def read_row_image(row: dict, kind: str = "image") -> bytes | None:
    """
    이미 소유 확인을 거쳐 조회한 사진 행(photo_logic 조회 결과)으로 바로 복호화 — 여러 장을 읽을 때 사진마다 다시 조회하지 않게
    - 호출하는 쪽이 user_id 조건으로 조회한 행만 넘겨야 한다 (백업 내보내기).
    """
    return read_image(ImageRef(kind, row["file_path"], row["user_id"], ""))


def load_image(user_id: str, pic_id: int, thumb: bool = False) -> bytes | None:
    """본인 사진의 JPEG 바이트 (복호화) — 사진이 없거나, 남의 사진이거나, 파일이 없으면 None"""
    ref = image_ref(user_id, pic_id, "thumb" if thumb else "image")
    return read_image(ref) if ref else None


def remove_files(rel_path: str) -> None:
    """완전삭제(purge_photo)된 사진의 암호화 파일(웹용·썸네일·마커용) 삭제"""
    for kind in KINDS:
        p = _variant_rel_path(rel_path, kind)
        try:
            _abs_path(p).unlink(missing_ok=True)
        except ValueError:
            current_app.logger.warning("저장소 밖 경로 삭제 시도 차단: %s", p)
