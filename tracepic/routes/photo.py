"""
사진 라우트 (/photos)

- GET  /photos/upload             업로드 화면
- POST /photos/upload             사진 1장 업로드 → JSON (화면의 JS 가 파일마다 한 번씩 호출)
- GET  /photos/<pic_id>/image     복호화한 웹용 JPEG
- GET  /photos/<pic_id>/thumb     복호화한 썸네일 JPEG (긴 변 400px)
- GET  /photos/<pic_id>/mini      복호화한 마커용 JPEG (128px 정사각형)
이미지는 반드시 이 라우트에서 복호화한 뒤에만 응답한다 (static/ 에 두지 않음).

캐시: 저장된 파일은 바뀌지 않으므로 ETag + 1년 immutable 캐시를 붙인다.
- 브라우저는 다시 요청하지 않고 자기 캐시를 쓴다. 다시 묻더라도(If-None-Match) 소유 확인만 하고 304 로 끝낸다(복호화 안 함).
- private: 공유 프록시에는 남기지 않는다. 같은 브라우저에서 다른 계정으로 로그인해도 그 계정 화면에는
  자기 사진 주소만 나오므로 남의 캐시를 볼 일은 없다.
"""
from datetime import datetime, timedelta

from flask import Blueprint, Response, abort, current_app, g, jsonify, render_template, request, url_for

from ..logics import photo_file_logic, photo_logic
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
        max_mb=cfg["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        heif_supported=HEIF_SUPPORTED,
    )


@bp.post("/upload")
def upload():
    """사진 1장 업로드 — 성공하면 200 + 사진 정보, 실패하면 400 + error 메시지"""
    file = request.files.get("photo")
    if file is None or not file.filename:
        return jsonify(ok=False, error="파일이 없습니다."), 400

    try:
        result = photo_file_logic.save_upload(
            g.user["user_id"],
            file.read(),
            file.filename,
            client_time=_parse_client_time(request.form.get("client_time")),
            status=request.form.get("status") or photo_logic.STATUS_PRIVATE,
        )
    except ImageError as e:
        return jsonify(ok=False, error=str(e)), 400
    except ValueError as e:
        return jsonify(ok=False, error=f"입력값 오류: {e}"), 400

    current_app.logger.info("사진 업로드: user_id=%s pic_id=%s", g.user["user_id"], result.pic_id)
    return jsonify(
        ok=True,
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
        resp = Response(data, mimetype="image/jpeg")
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
