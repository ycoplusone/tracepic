"""
CSRF(사이트 간 요청 위조) 방지 — 세션 토큰 방식

- 세션마다 난수 토큰을 하나 만들어 두고, 화면의 폼(hidden 필드)과 fetch 요청(X-CSRF-Token 헤더)에 넣는다.
- POST/PUT/PATCH/DELETE 요청은 토큰이 세션 값과 같아야 통과한다.
- 다른 사이트는 이 토큰을 읽을 수 없으므로, 로그인한 사용자의 브라우저를 이용한 위조 요청이 막힌다.
"""
import hmac
import secrets

from flask import Flask, jsonify, request, session

_SESSION_KEY = "csrf_token"
FORM_FIELD = "csrf_token"
HEADER_NAME = "X-CSRF-Token"
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_token() -> str:
    """현재 세션의 CSRF 토큰 (없으면 새로 만든다) — 템플릿에서 csrf_token() 으로 호출"""
    token = session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_SESSION_KEY] = token
    return token


def _is_valid() -> bool:
    """요청에 담긴 토큰이 세션 토큰과 같은지 (타이밍 공격 방지를 위해 compare_digest 사용)"""
    expected = session.get(_SESSION_KEY)
    sent = request.headers.get(HEADER_NAME) or request.form.get(FORM_FIELD)
    return bool(expected and sent) and hmac.compare_digest(expected, sent)


def init_app(app: Flask) -> None:
    """모든 쓰기 요청에 CSRF 검사를 걸고, 템플릿에 csrf_token() 함수를 등록한다"""
    app.jinja_env.globals["csrf_token"] = get_token

    @app.before_request
    def _check_csrf():
        if request.method not in _UNSAFE_METHODS or request.endpoint == "static":
            return None
        # 앱 API(/api/app/*)는 쿠키가 아니라 요청에 직접 넣은 device_token 으로만 인증한다
        # (routes/auth.require_login). 브라우저가 자동으로 붙이는 자격 증명이 없으니 위조 요청이 성립하지 않는다.
        if request.blueprint == "app_api":
            return None
        if _is_valid():
            return None
        message = "보안 토큰이 만료되었습니다. 페이지를 새로고침한 뒤 다시 시도하세요."
        # fetch 요청(JSON 응답을 기대)이면 JSON 으로, 일반 폼이면 텍스트로 응답
        if request.headers.get(HEADER_NAME) is not None or request.accept_mimetypes.best == "application/json":
            return jsonify(ok=False, error=message), 400
        return message, 400
