"""
백업 내보내기 라우트 (/backup)

- GET /backup/download?start=YYYYMMDD&end=YYYYMMDD[&status=A,B,C][&exif=0]
  → 기간·상태 조건의 사진(복호화 JPEG)·일기·사진 설명을 zip 으로 내려받는다 (export_logic).
- 읽기 전용 GET 이라 CSRF 검사 대상이 아니며, 로그인 가드가 본인만 받게 한다(조회는 모두 user_id 조건).
- zip 은 만들면서 바로 보낸다(스트리밍) — 복호화한 사진을 디스크에 남기지 않는다.
"""
from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context

from ..logics import export_logic, photo_logic

bp = Blueprint("backup", __name__)


@bp.get("/download")
def download():
    """백업 zip 내려받기 (잘못된 조건이면 400 JSON)"""
    user_id = g.user["user_id"]
    raw = request.args.get("status")
    try:
        statuses = photo_logic.check_status_filter(raw.split(",")) if raw else photo_logic.VISIBLE_STATUSES
        data = export_logic.prepare(user_id, request.args.get("start", ""), request.args.get("end", ""), statuses)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    with_exif = request.args.get("exif", "1") != "0"
    current_app.logger.info("백업 내보내기: user_id=%s 기간=%s~%s 사진=%d장",
                            user_id, data["start"], data["end"], len(data["photos"]))
    name = export_logic.file_name(data)
    return Response(
        stream_with_context(export_logic.stream_zip(data, with_exif)),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",      # 복호화된 사진이 담긴 파일 — 캐시에 남기지 않는다
            "X-Content-Type-Options": "nosniff",
        },
    )
