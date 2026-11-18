"""
일기 화면 라우트 (/diary)

- 화면만 그리고, 데이터는 화면의 JS 가 /api/diary 로 주고받는다.
- 기록은 tracepic_daily (하루 1건, 마크다운)에 저장된다.
"""
from flask import Blueprint, render_template

bp = Blueprint("diary", __name__)


@bp.get("/")
def index():
    """일기 화면 — 기록 카드가 원형으로 늘어선 3D 링"""
    return render_template("diary.html")
