"""
기본 라우트
- 메인 페이지(지도), 여행기(/story), 달력(/calendar)과 헬스체크(서버/DB 상태 확인) 엔드포인트
"""
from flask import Blueprint, jsonify, render_template

from ..logics import photo_logic, system_logic

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    """메인 페이지 = 사진 지도 (데이터는 화면의 JS 가 /api 로 불러온다)"""
    return render_template(
        "map.html",
        status_labels=photo_logic.STATUS_LABELS,          # 상태 조건 체크박스·상태 변경 선택지
        default_statuses=photo_logic.VISIBLE_STATUSES,    # 처음엔 휴지통을 뺀 A/B/C 만 조회
    )


@bp.get("/story")
def story():
    """여행기: 기간 안의 날짜별 일기 + 동선 지도 + 사진·설명 (데이터는 JS 가 /api/story 로 불러온다)"""
    return render_template(
        "story.html",
        status_labels=photo_logic.STATUS_LABELS,
        default_statuses=photo_logic.VISIBLE_STATUSES,
    )


@bp.get("/calendar")
def calendar_page():
    """달력: 날짜별 사진 수·일기·첫/마지막 촬영 시각·이동 거리 (데이터는 JS 가 /api/calendar 로 불러온다)"""
    return render_template(
        "calendar.html",
        status_labels=photo_logic.STATUS_LABELS,
        default_statuses=photo_logic.VISIBLE_STATUSES,
    )


@bp.get("/health")
def health():
    """헬스체크: DB 연결까지 확인 (로그인 불필요 — 모니터링용)"""
    ok, detail = system_logic.check_db()
    if ok:
        return jsonify(status="ok", db="ok")
    return jsonify(status="degraded", db=detail), 503
