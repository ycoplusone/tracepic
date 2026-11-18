"""
인증 라우트 + 전역 접근 가드

- 모든 요청은 먼저 require_login() 을 거친다 (공개 엔드포인트 제외).
  세션의 user_id/device_token 이 user_devices 에서 확인되면 통과, 아니면 로그인 페이지로 이동.
- 로그인 성공 시 원래 가려던 페이지(next)로 돌려보낸다.
"""
from flask import (Blueprint, current_app, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)

from ..logics import auth_logic
from ..utils.login_throttle import login_throttle
from ..utils.ttl_cache import TTLCache

bp = Blueprint("auth", __name__)

# 로그인 없이 접근 가능한 엔드포인트
PUBLIC_ENDPOINTS = {"auth.login", "main.health", "static"}

# 로그인 확인 결과 캐시: (user_id, device_token) → 사용자 정보
# 지도 화면은 썸네일 수십 장을 한꺼번에 요청한다. 요청마다 user_devices 를 조회하지 않도록 AUTH_CACHE_SECONDS 동안 기억한다.
# - 이 브라우저의 로그아웃은 즉시 반영된다(캐시 삭제). 다른 기기·다른 워커에서 토큰을 지운 경우엔 최대 그 시간만큼 늦게 반영된다.
_auth_cache = TTLCache(max_size=2048)


def _verify(user_id: str, token: str) -> dict | None:
    """세션의 (아이디, 토큰) 확인 — 캐시에 있으면 DB 를 조회하지 않는다 (실패 결과는 캐시하지 않음)"""
    ttl = current_app.config.get("AUTH_CACHE_SECONDS", 0)
    key = (user_id, token)
    if ttl > 0:
        user = _auth_cache.get(key)
        if user is not None:
            return user
    user = auth_logic.verify_device(user_id, token)
    if user is not None and ttl > 0:
        _auth_cache.set(key, user, ttl)
    return user


@bp.before_app_request
def require_login():
    """전역 로그인 가드: 세션 키 → user_devices 검증"""
    g.user = None
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None  # endpoint None = 존재하지 않는 URL → 404 처리에 맡김

    user_id = session.get("user_id")
    token = session.get("device_token")
    user = _verify(user_id, token) if user_id and token else None

    if user is None:
        session.clear()  # 만료·위조·삭제된 세션 정리
        if request.path.startswith("/api/"):
            return jsonify(error="로그인이 필요합니다."), 401
        # 원래 가려던 경로를 next 로 넘김 (쿼리 없으면 끝의 '?' 제거)
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    g.user = user
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    """로그인 화면 / 처리"""
    next_url = _safe_next(request.values.get("next"))

    # 이미 로그인된 브라우저면 바로 이동
    if request.method == "GET" and session.get("user_id") and session.get("device_token"):
        if auth_logic.verify_device(session["user_id"], session["device_token"]):
            return redirect(next_url)

    if request.method == "GET":
        return render_template("login.html", next=next_url)

    user_id = request.form.get("user_id", "").strip()
    password = request.form.get("password", "")
    cfg = current_app.config

    # ── 실패 횟수 제한 확인 (IP 기준 + 아이디 기준) ──
    keys = [f"ip:{request.remote_addr}", f"user:{user_id.lower()}"]
    limits = [cfg["LOGIN_MAX_FAILS"] * 3, cfg["LOGIN_MAX_FAILS"]]  # IP 는 여러 아이디 시도를 고려해 여유
    window = cfg["LOGIN_LOCK_MINUTES"] * 60
    remain = max(login_throttle.locked_seconds(k, n, window) for k, n in zip(keys, limits))
    if remain:
        flash(f"로그인 시도가 너무 많습니다. {remain // 60 + 1}분 후 다시 시도하세요.", "error")
        return render_template("login.html", next=next_url, user_id=user_id), 429

    user = auth_logic.authenticate(user_id, password) if user_id and password else None
    if user is None:
        for k in keys:
            login_throttle.record_fail(k)
        current_app.logger.info("로그인 실패: user_id=%s ip=%s", user_id, request.remote_addr)
        # 아이디 존재 여부를 알 수 없도록 동일한 메시지 사용
        flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
        return render_template("login.html", next=next_url, user_id=user_id), 401

    # ── 성공: 토큰 발급 → 세션 저장 ──
    for k in keys:
        login_throttle.reset(k)
    token = auth_logic.issue_device_token(
        user["user_id"], request.headers.get("User-Agent"), cfg["DEVICE_TOKEN_DAYS"]
    )
    session.clear()             # 세션 고정(fixation) 공격 방지: 기존 세션 폐기 후 새로 구성
    session.permanent = True    # 브라우저를 닫아도 유지 (PERMANENT_SESSION_LIFETIME)
    session["user_id"] = user["user_id"]  # DB 의 정식 아이디 저장 (대소문자 통일)
    session["device_token"] = token
    current_app.logger.info("로그인 성공: user_id=%s ip=%s", user["user_id"], request.remote_addr)
    return redirect(next_url)


@bp.post("/logout")
def logout():
    """로그아웃: 이 브라우저의 토큰만 폐기"""
    user_id, token = session.get("user_id"), session.get("device_token")
    if user_id and token:
        _auth_cache.delete((user_id, token))   # 이 워커의 캐시에서 바로 지운다
        auth_logic.revoke_device(user_id, token)
    session.clear()
    return redirect(url_for("auth.login"))


def _safe_next(target: str | None) -> str:
    """
    오픈 리다이렉트 방지: 같은 사이트 내부 경로('/...')만 허용
    '//evil.com' 이나 '/\\evil.com' 처럼 외부로 해석될 수 있는 값은 거부
    """
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("main.index")
