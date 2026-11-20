"""
관리자 화면 (/admin) — user_info.role = 'admin' 인 사용자만

- 가입 신청 목록: 승인 대기(P)를 먼저 보여 주고 승인 / 거절한다.
- 관리자가 아니면 404 로 응답한다(화면이 있다는 것도 알리지 않음). 상단 메뉴의 '관리'도 관리자에게만 보인다.
- 역할(role)은 로그인 확인 캐시(AUTH_CACHE_SECONDS) 때문에 바꾼 뒤 최대 그 시간만큼 늦게 반영된다.
"""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, url_for

from ..logics import account_logic
from ..utils.mail import MailError, send_mail

bp = Blueprint("admin", __name__)


@bp.before_request
def require_admin():
    """전역 로그인 가드(auth.require_login) 다음에 실행 — 관리자만 통과"""
    if not g.get("user") or g.user.get("role") != "admin":
        abort(404)


@bp.get("/")
def index():
    """가입 신청 목록"""
    return render_template(
        "admin.html",
        signups=account_logic.list_signups(),
        labels=account_logic.SIGNUP_STATUS_LABELS,
    )


@bp.post("/signups/<int:signup_id>/approve")
def approve(signup_id: int):
    """승인 → user_info 에 계정 추가, 신청자에게 메일"""
    try:
        email = account_logic.approve_signup(signup_id, g.user["user_id"])
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.index"))
    if email is None:
        flash("이미 처리되었거나 없는 신청입니다.", "error")
        return redirect(url_for("admin.index"))
    current_app.logger.info("가입 승인: email=%s by=%s", email, g.user["user_id"])
    base = current_app.config["PUBLIC_BASE_URL"]
    _mail(email, "[TracePic] 가입이 승인되었습니다",
          f"TracePic 가입이 승인되었습니다.\n아이디: {email}\n가입할 때 정한 비밀번호로 로그인하세요."
          + (f"\n{base}{url_for('auth.login')}" if base else ""))
    flash(f"{email} 가입을 승인했습니다.", "info")
    return redirect(url_for("admin.index"))


@bp.post("/signups/<int:signup_id>/reject")
def reject(signup_id: int):
    """거절 → 신청자에게 메일"""
    email = account_logic.reject_signup(signup_id, g.user["user_id"])
    if email is None:
        flash("이미 처리되었거나 없는 신청입니다.", "error")
        return redirect(url_for("admin.index"))
    current_app.logger.info("가입 거절: email=%s by=%s", email, g.user["user_id"])
    _mail(email, "[TracePic] 가입 신청 결과", "TracePic 가입 신청이 승인되지 않았습니다.")
    flash(f"{email} 가입 신청을 거절했습니다.", "info")
    return redirect(url_for("admin.index"))


def _mail(to: str, subject: str, body: str) -> None:
    """결과 알림 메일 — 실패해도 처리 결과는 그대로, 화면에만 알린다"""
    try:
        send_mail(to, subject, body)
    except MailError:
        flash("처리는 끝났지만 알림 메일을 보내지 못했습니다.", "error")
