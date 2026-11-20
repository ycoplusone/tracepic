"""
계정 라우트 (로그인 없이 쓰는 공개 화면): 메일 가입 신청 · 비밀번호 찾기

가입:   /signup (메일·비밀번호) → 인증 메일 → /signup/verify (6자리 코드) → 관리자 승인 대기
재설정: /password/forgot (메일) → 인증 메일 → /password/reset (코드 + 새 비밀번호)

- 진행 중인 메일 주소는 서명된 세션에만 둔다(signup_email / reset_email).
- 비밀번호 찾기는 계정이 있든 없든 같은 안내를 보여 준다(가입 여부를 떠볼 수 없게).
- 같은 IP 에서 인증 메일은 1시간에 MAIL_PER_IP_HOUR 통까지 (메일 폭탄 방지, 워커 메모리 기준).
"""
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from ..logics import account_logic
from ..logics.account_logic import CodeError
from ..utils.login_throttle import LoginThrottle, login_throttle
from ..utils.mail import MailError, send_mail
from ..utils.password import check_new_password

bp = Blueprint("account", __name__)

MAIL_PER_IP_HOUR = 10
_mail_throttle = LoginThrottle()   # IP 별 인증 메일 발송 횟수 (로그인 실패 제한과 같은 방식)


def _ip_mail_blocked() -> bool:
    """이 IP 가 1시간 발송 한도를 넘었는지 (넘었으면 안내 메시지까지 띄움)"""
    if _mail_throttle.locked_seconds(f"ip:{request.remote_addr}", MAIL_PER_IP_HOUR, 3600):
        flash("인증 메일 요청이 너무 많습니다. 잠시 후 다시 시도하세요.", "error")
        return True
    return False


def _send_code(purpose: str, email: str, subject: str, intro: str, quiet: bool = False) -> bool:
    """코드 발급 + 메일 발송 → 성공 여부

    실패 메시지는 flash 로 보여 준다. quiet=True(비밀번호 찾기)면 보여 주지 않고 로그만 남긴다
    — "방금 보냈습니다" 같은 안내가 계정이 있을 때만 나오면 가입 여부가 드러나기 때문.
    """
    try:
        code = account_logic.issue_code(purpose, email)
    except CodeError as e:
        if quiet:
            current_app.logger.info("재설정 코드 발급 거절: email=%s reason=%s", email, e)
        else:
            flash(str(e), "error")
        return False
    _mail_throttle.record_fail(f"ip:{request.remote_addr}")
    minutes = current_app.config["EMAIL_CODE_MINUTES"]
    body = (f"{intro}\n\n인증 코드: {code}\n\n"
            f"{minutes}분 안에 입력해 주세요. 직접 요청하지 않았다면 이 메일은 무시하셔도 됩니다.\n\n— TracePic")
    try:
        send_mail(email, subject, body)
    except MailError as e:
        if not quiet:
            flash(str(e), "error")
        return False
    return True


def _notify(to_list: list[str], subject: str, body: str) -> None:
    """알림 메일 (실패해도 본 작업은 그대로 — 로그만 남김)"""
    for to in to_list:
        try:
            send_mail(to, subject, body)
        except MailError:
            pass


# ============================================================
# 가입 신청
# ============================================================
@bp.route("/signup", methods=["GET", "POST"])
def signup():
    """1단계: 메일·비밀번호 입력 → 인증 메일 발송"""
    min_len = current_app.config["PASSWORD_MIN_LENGTH"]
    if request.method == "GET":
        return render_template("signup.html", min_len=min_len)

    raw_email = request.form.get("email", "")
    try:
        email = account_logic.normalize_email(raw_email)
        check_new_password(request.form.get("password", ""), request.form.get("password2", ""), min_len)
        if _ip_mail_blocked():
            return render_template("signup.html", min_len=min_len, email=raw_email), 429
        account_logic.start_signup(email, request.form["password"])
    except ValueError as e:
        flash(str(e), "error")
        return render_template("signup.html", min_len=min_len, email=raw_email), 400

    session["signup_email"] = email
    if _send_code(account_logic.PURPOSE_SIGNUP, email, "[TracePic] 가입 인증 코드",
                  "TracePic 가입 신청을 확인하는 인증 코드입니다."):
        flash(f"{email} 로 인증 코드를 보냈습니다.", "info")
    current_app.logger.info("가입 신청: email=%s ip=%s", email, request.remote_addr)
    return redirect(url_for("account.signup_verify"))


@bp.route("/signup/verify", methods=["GET", "POST"])
def signup_verify():
    """2단계: 메일로 받은 코드 입력 → 관리자 승인 대기"""
    email = session.get("signup_email")
    if not email:
        return redirect(url_for("account.signup"))
    if request.method == "GET":
        return render_template("signup_verify.html", email=email)

    try:
        account_logic.verify_signup(email, request.form.get("code", "").strip())
    except CodeError as e:
        flash(str(e), "error")
        return render_template("signup_verify.html", email=email), 400

    session.pop("signup_email", None)
    current_app.logger.info("가입 메일 인증 완료(승인 대기): email=%s", email)
    base = current_app.config["PUBLIC_BASE_URL"]
    _notify(account_logic.admin_emails(), "[TracePic] 새 가입 신청",
            f"새 가입 신청이 있습니다: {email}\n\n관리자 화면에서 승인하거나 거절해 주세요."
            + (f"\n{base}{url_for('admin.index')}" if base else ""))
    return render_template("signup_done.html", email=email)


@bp.post("/signup/resend")
def signup_resend():
    """가입 인증 코드 다시 받기"""
    email = session.get("signup_email")
    if not email:
        return redirect(url_for("account.signup"))
    if account_logic.has_waiting_signup(email) and not _ip_mail_blocked():
        if _send_code(account_logic.PURPOSE_SIGNUP, email, "[TracePic] 가입 인증 코드",
                      "TracePic 가입 신청을 확인하는 인증 코드입니다."):
            flash("인증 코드를 다시 보냈습니다.", "info")
    return redirect(url_for("account.signup_verify"))


# ============================================================
# 비밀번호 찾기 (재설정) — 관리자 승인 없이 메일 인증만
# ============================================================
def _send_reset_code(email: str) -> None:
    """재설정 코드 발송 — 결과와 상관없이 화면 안내는 같다(quiet)"""
    _send_code(account_logic.PURPOSE_RESET, email, "[TracePic] 비밀번호 재설정 코드",
               "TracePic 비밀번호 재설정을 위한 인증 코드입니다.", quiet=True)


_RESET_SENT = "가입된 메일이라면 인증 코드를 보냈습니다. 메일함(스팸함 포함)을 확인해 주세요."


@bp.route("/password/forgot", methods=["GET", "POST"])
def password_forgot():
    """1단계: 메일 입력 → (계정이 있으면) 인증 메일. 안내는 항상 같다"""
    if request.method == "GET":
        return render_template("password_forgot.html")
    raw_email = request.form.get("email", "")
    try:
        email = account_logic.normalize_email(raw_email)
    except ValueError as e:
        flash(str(e), "error")
        return render_template("password_forgot.html", email=raw_email), 400
    if _ip_mail_blocked():
        return render_template("password_forgot.html", email=raw_email), 429

    session["reset_email"] = email
    if account_logic.find_account_by_email(email):
        _send_reset_code(email)
    current_app.logger.info("비밀번호 찾기 요청: email=%s ip=%s", email, request.remote_addr)
    flash(_RESET_SENT, "info")
    return redirect(url_for("account.password_reset"))


@bp.route("/password/reset", methods=["GET", "POST"])
def password_reset():
    """2단계: 코드 + 새 비밀번호 → user_info.password 변경"""
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("account.password_forgot"))
    min_len = current_app.config["PASSWORD_MIN_LENGTH"]
    if request.method == "GET":
        return render_template("password_reset.html", email=email, min_len=min_len)

    try:
        check_new_password(request.form.get("password", ""), request.form.get("password2", ""), min_len)
        user_id = account_logic.reset_password(email, request.form.get("code", "").strip(), request.form["password"])
    except ValueError as e:      # CodeError 포함
        flash(str(e), "error")
        return render_template("password_reset.html", email=email, min_len=min_len), 400

    session.pop("reset_email", None)
    login_throttle.reset(f"user:{user_id.lower()}")   # 비밀번호를 새로 정했으니 로그인 잠금도 푼다
    current_app.logger.info("비밀번호 재설정: user_id=%s ip=%s", user_id, request.remote_addr)
    _notify([email], "[TracePic] 비밀번호가 변경되었습니다",
            "TracePic 비밀번호가 방금 변경되었습니다.\n직접 바꾸지 않았다면 바로 관리자에게 알려 주세요.")
    flash("비밀번호를 바꿨습니다. 새 비밀번호로 로그인하세요.", "info")
    return redirect(url_for("auth.login"))


@bp.post("/password/resend")
def password_resend():
    """재설정 코드 다시 받기 (안내는 항상 같다)"""
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("account.password_forgot"))
    if not _ip_mail_blocked():
        if account_logic.find_account_by_email(email):
            _send_reset_code(email)
        flash(_RESET_SENT, "info")
    return redirect(url_for("account.password_reset"))
