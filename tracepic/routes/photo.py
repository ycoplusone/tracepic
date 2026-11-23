"""
사진 라우트 (/photos)

- GET  /photos/upload             업로드 화면
- POST /photos/upload             사진 1장 업로드 → JSON (화면의 JS 가 파일마다 한 번씩 호출)
                                  동영상(mp4·mov 등)이면 3~7초 구간을 움직이는 WebP 로 바꿔 사진처럼 저장 (영상은 보관 안 함)
- GET  /photos/<pic_id>/image     복호화한 웹용 JPEG
- GET  /photos/<pic_id>/thumb     복호화한 썸네일 JPEG (긴 변 400px)
- GET  /photos/<pic_id>/mini      복호화한 마커용 JPEG (128px 정사각형)
  (동영상 클립이면 세 가지 모두 움직이는 WebP — Content-Type 은 내용을 보고 정한다)
이미지는 반드시 이 라우트에서 복호화한 뒤에만 응답한다 (static/ 에 두지 않음).

캐시: 저장된 파일은 바뀌지 않으므로 ETag + 1년 immutable 캐시를 붙인다.
- 브라우저는 다시 요청하지 않고 자기 캐시를 쓴다. 다시 묻더라도(If-None-Match) 소유 확인만 하고 304 로 끝낸다(복호화 안 함).
- private: 공유 프록시에는 남기지 않는다. 같은 브라우저에서 다른 계정으로 로그인해도 그 계정 화면에는
  자기 사진 주소만 나오므로 남의 캐시를 볼 일은 없다.
"""
import os
import shutil
from datetime import datetime, timedelta

from flask import Blueprint, Response, abort, current_app, g, jsonify, render_template, request, url_for

from ..logics import photo_file_logic, photo_logic
from ..utils import video
from ..utils.image import HEIF_SUPPORTED, ImageError

bp = Blueprint("photo", __name__)

# 화면의 공개 범위 선택지 (값 → 표시 이름)
STATUS_CHOICES = [
    (photo_logic.STATUS_PRIVATE, "나만 보기"),
    (photo_logic.STATUS_PARTIAL, "부분 공유"),
    (photo_logic.STATUS_PUBLIC, "전체 공유"),
]


@bp.get("/upload")
def upload_page():
    """업로드 화면"""
    cfg = current_app.config
    return render_template(
        "upload.html",
        status_choices=STATUS_CHOICES,
        max_mb=cfg["MAX_PHOTO_BYTES"] // (1024 * 1024),
        max_video_mb=cfg["MAX_VIDEO_BYTES"] // (1024 * 1024),
        heif_supported=HEIF_SUPPORTED,
        video_supported=video.find_ffmpeg(cfg["FFMPEG_PATH"] or None) is not None,
        video_exts=sorted(video.VIDEO_EXTENSIONS),
    )


@bp.post("/upload")
def upload():
    """사진 1장 업로드 — 성공하면 200 + 사진 정보, 실패하면 400 + error 메시지"""
    return handle_upload(request.files.get("photo"))


def handle_upload(file):
    """
    업로드 1건 처리 (웹 /photos/upload 와 앱 /api/app/upload 가 같이 쓴다)
    - 호출 전에 g.user 가 정해져 있어야 한다 (웹: 세션, 앱: device_token).
    - 폼 값: status, client_time(파일 시각), tz_offset(동영상 UTC 시각 변환용),
      latitude/longitude(파일에 GPS 가 없을 때만 쓰는 보조 좌표 — 앱이 따로 읽어 보낸 값)
    """
    if file is None or not file.filename:
        return jsonify(ok=False, error="파일이 없습니다."), 400

    cfg = current_app.config
    is_video = video.is_video_name(file.filename)
    limit = cfg["MAX_VIDEO_BYTES"] if is_video else cfg["MAX_PHOTO_BYTES"]
    if (request.content_length or 0) > limit + 1024 * 1024:        # 폼 필드 여유 1MB
        kind = "동영상" if is_video else "사진"
        return jsonify(ok=False, error=f"{kind} 파일이 너무 큽니다 (최대 {limit // 1048576}MB)."), 413

    client_time = _parse_client_time(request.form.get("client_time"))
    status = request.form.get("status") or photo_logic.STATUS_PRIVATE
    gps_hint = _parse_gps(request.form.get("latitude"), request.form.get("longitude"))
    try:
        if is_video:
            result = _save_video(file, client_time, status, gps_hint)
        else:
            result = photo_file_logic.save_upload(g.user["user_id"], file.read(), file.filename,
                                                  client_time=client_time, status=status, gps_hint=gps_hint)
    except (ImageError, video.VideoError) as e:
        return jsonify(ok=False, error=str(e)), 400
    except ValueError as e:
        return jsonify(ok=False, error=f"입력값 오류: {e}"), 400

    current_app.logger.info("%s 업로드: user_id=%s pic_id=%s", "동영상" if is_video else "사진",
                            g.user["user_id"], result.pic_id)
    return jsonify(
        ok=True,
        kind="clip" if result.animated else "photo",   # 동영상·움직이는 WebP 는 클립
        pic_id=result.pic_id,
        base_dt=result.base_dt,
        photo_at=result.photo_at.strftime("%Y-%m-%d %H:%M:%S"),
        time_source=result.time_source,
        latitude=result.latitude,
        longitude=result.longitude,
        thumb_url=url_for("photo.thumb", pic_id=result.pic_id),
        mini_url=url_for("photo.mini", pic_id=result.pic_id),
        image_url=url_for("photo.image", pic_id=result.pic_id),
    )


def _save_video(file, client_time, status, gps_hint=None):
    """업로드 동영상을 STORAGE_DIR/.tmp 에 잠깐 쓰고(0600) WebP 클립으로 바꾼 뒤 바로 지운다"""
    tmp = photo_file_logic.temp_upload_path()
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(file.stream, f, 1024 * 1024)       # 메모리에 다 올리지 않고 1MB 씩
        return photo_file_logic.save_video_upload(
            g.user["user_id"], tmp, file.filename, client_time=client_time,
            tz_minutes=_parse_tz(request.form.get("tz_offset")), status=status, gps_hint=gps_hint,
        )
    finally:
        tmp.unlink(missing_ok=True)


def _parse_gps(lat: str | None, lng: str | None) -> tuple[float, float] | None:
    """보조 좌표(십진수 도). 둘 다 있고 범위 안이며 0,0(GPS 없음 표시)이 아닐 때만 쓴다"""
    try:
        la, lo = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= la <= 90 and -180 <= lo <= 180) or (la == 0 and lo == 0) or la != la or lo != lo:
        return None
    return round(la, 7), round(lo, 7)


def _parse_tz(value: str | None) -> int | None:
    """브라우저 시간대(UTC 기준 동쪽 +분, 예: 한국 540). 형식이 틀리거나 범위 밖이면 None"""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return minutes if -14 * 60 <= minutes <= 14 * 60 else None


@bp.get("/<int:pic_id>/image")
def image(pic_id: int):
    """웹용 이미지 (본인 사진만)"""
    return _serve(pic_id, "image")


@bp.get("/<int:pic_id>/thumb")
def thumb(pic_id: int):
    """썸네일 (본인 사진만)"""
    return _serve(pic_id, "thumb")


@bp.get("/<int:pic_id>/mini")
def mini(pic_id: int):
    """마커용 정사각형 썸네일 (본인 사진만)"""
    return _serve(pic_id, "mini")


_CACHE_CONTROL = "private, max-age=31536000, immutable"


def _serve(pic_id: int, kind: str) -> Response:
    """소유 확인 → (브라우저 캐시가 같으면 304) → 복호화한 JPEG 응답"""
    ref = photo_file_logic.image_ref(g.user["user_id"], pic_id, kind)
    if ref is None:
        abort(404)
    if ref.etag in request.if_none_match:
        resp = Response(status=304)          # 파일을 읽지도, 복호화하지도 않는다
    else:
        data = photo_file_logic.read_image(ref)
        if data is None:
            abort(404)
        resp = Response(data, mimetype="image/webp" if video.is_webp(data) else "image/jpeg")
    resp.set_etag(ref.etag)
    resp.headers["Cache-Control"] = _CACHE_CONTROL
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _parse_client_time(value: str | None) -> datetime | None:
    """
    브라우저가 보낸 파일 수정 시각('YYYY-MM-DDTHH:MM:SS', 사용자 기기의 현지 시각)
    - EXIF 에 촬영 시각이 없을 때만 쓰인다. 형식이 틀리거나 말이 안 되는 값이면 무시(None)한다.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value[:19])
    except ValueError:
        return None
    if not (datetime(1990, 1, 1) <= parsed <= datetime.now() + timedelta(days=1)):
        return None
    return parsed.replace(tzinfo=None, microsecond=0)
