"""
앱(휴대폰 업로드 앱) 전용 API — /api/app/*

웹 화면은 세션 쿠키 + CSRF 토큰을 쓰지만, 앱은 쿠키 없이 기기 토큰(device_token)으로 인증한다.
- POST /api/app/login    아이디·비밀번호 → device_token 발급 (user_devices 에 INSERT, 웹 로그인과 같은 규칙)
- GET  /api/app/me       토큰이 아직 유효한지 확인
- POST /api/app/upload   사진·동영상 1건 업로드 (웹 /photos/upload 와 같은 처리: 3종 생성·암호화·DB 등록)
- POST /api/app/logout   이 기기 토큰 삭제

인증 값 전달 (login 제외):
- 권장: 헤더 `X-User-Id: <user_id>` + `Authorization: Bearer <device_token>`
- 또는 폼 필드 `user_id`, `device_token` (multipart 업로드에 함께 넣기)
  헤더 방식은 큰 파일 본문을 읽기 전에 인증을 끝낼 수 있어 더 낫다.

보안
- 이 블루프린트의 요청은 **세션 쿠키를 전혀 쓰지 않는다** (routes/auth.require_login 이 토큰으로만 g.user 를 정함).
  쿠키로 인증되지 않으므로 다른 사이트가 사용자 브라우저를 이용해 위조할 수 없다 → CSRF 검사 제외(utils/csrf.py).
- 비밀번호·토큰이 오가므로 실제 사용은 HTTPS 에서만 해야 한다 (http 면 같은 와이파이에서 엿볼 수 있음).
"""
from flask import Blueprint, current_app, g, jsonify, request

from ..logics import account_logic, auth_logic
from ..utils.login_throttle import login_throttle
from . import auth as auth_routes
from .photo import handle_upload

bp = Blueprint("app_api", __name__)

# 앱이 user_devices.user_agent 에 남길 이름 (기기 이름은 앱이 보냄, 길이 제한)
APP_AGENT_PREFIX = "TracePic App"
DEVICE_NAME_MAX = 100


def app_credentials() -> tuple[str | None, str | None]:
    """요청에서 (user_id, device_token) 꺼내기 — 헤더 우선, 없으면 폼 필드"""
    user_id = request.headers.get("X-User-Id")
    token = None
    auth = request.headers.get("Authorization", "")
    if auth[:7].lower() == "bearer ":
        token = auth[7:].strip()
    if not user_id or not token:
        user_id = user_id or request.form.get("user_id")
        token = token or request.form.get("device_token")
    return (user_id or "").strip() or None, (token or "").strip() or None


@bp.post("/login")
def login():
    """
    앱 로그인 — JSON {"user_id","password","device_name"} (폼으로 보내도 됨)
    성공: 200 {"ok":true,"user_id","device_token","expires_days"}
    실패: 400 값 없음 / 401 틀림·승인 대기 / 429 시도 너무 많음
    """
    data = request.get_json(silent=True) or request.form
    user_id = str(data.get("user_id") or "").strip()
    password = str(data.get("password") or "")
    device_name = str(data.get("device_name") or "").strip()[:DEVICE_NAME_MAX]
    if not user_id or not password:
        return jsonify(ok=False, error="아이디와 비밀번호를 보내 주세요."), 400

    # ── 실패 횟수 제한 (웹 로그인과 같은 기준·같은 집계) ──
    cfg = current_app.config
    keys = [f"ip:{request.remote_addr}", f"user:{user_id.lower()}"]
    limits = [cfg["LOGIN_MAX_FAILS"] * 3, cfg["LOGIN_MAX_FAILS"]]
    window = cfg["LOGIN_LOCK_MINUTES"] * 60
    remain = max(login_throttle.locked_seconds(k, n, window) for k, n in zip(keys, limits))
    if remain:
        return jsonify(ok=False, error=f"로그인 시도가 너무 많습니다. {remain // 60 + 1}분 후 다시 시도하세요."), 429

    user = auth_logic.authenticate(user_id, password)
    if user is None:
        for k in keys:
            login_throttle.record_fail(k)
        current_app.logger.info("앱 로그인 실패: user_id=%s ip=%s", user_id, request.remote_addr)
        waiting = account_logic.pending_status(user_id, password)   # 비밀번호까지 맞는 가입 신청만 안내
        if waiting == "P":
            msg = "가입 신청이 관리자 승인을 기다리고 있습니다."
        elif waiting == "V":
            msg = "가입 메일 인증이 끝나지 않았습니다."
        else:
            msg = "아이디 또는 비밀번호가 올바르지 않습니다."
        return jsonify(ok=False, error=msg), 401

    for k in keys:
        login_throttle.reset(k)
    agent = f"{APP_AGENT_PREFIX} ({device_name})" if device_name else APP_AGENT_PREFIX
    days = cfg["DEVICE_TOKEN_DAYS"]
    token = auth_logic.issue_device_token(user["user_id"], agent, days)
    current_app.logger.info("앱 로그인 성공: user_id=%s ip=%s", user["user_id"], request.remote_addr)
    # user_id 는 DB 의 정식 표기(대소문자)로 돌려준다 — 이후 요청에 이 값을 그대로 쓴다
    return jsonify(ok=True, user_id=user["user_id"], device_token=token, expires_days=days)


@bp.get("/me")
def me():
    """토큰 확인 — require_login 을 통과했다면 유효한 토큰이다"""
    return jsonify(ok=True, user_id=g.user["user_id"], email=g.user.get("email"))


@bp.post("/upload")
def upload():
    """
    사진·동영상 1건 업로드 — multipart/form-data
    - 파일 필드: photo (또는 file)
    - 선택: status(A/B/C, 기본 C), client_time('YYYY-MM-DDTHH:MM:SS' 현지 시각, 파일에 촬영 시각이 없을 때),
            tz_offset(UTC 기준 동쪽 +분, 동영상 UTC 시각 변환), latitude/longitude(파일에 GPS 가 없을 때만 사용)
    응답은 웹 업로드와 같다: {"ok","kind","pic_id","base_dt","photo_at","time_source","latitude","longitude",...}
    """
    return handle_upload(request.files.get("photo") or request.files.get("file"))


@bp.post("/logout")
def logout():
    """이 기기 토큰 삭제 (다른 기기·웹 로그인은 그대로)"""
    user_id, token = app_credentials()
    auth_routes.forget_cached(user_id, token)
    auth_logic.revoke_device(user_id, token)
    return jsonify(ok=True)
