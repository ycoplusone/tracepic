"""
TracePic 애플리케이션 패키지
- Application Factory 패턴: create_app() 호출 시점에 설정·확장·블루프린트를 조립한다.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify

from config import config_by_name
from . import db
from .utils import csrf


def create_app(env_name: str | None = None) -> Flask:
    """Flask 앱 인스턴스를 생성해 반환한다."""
    env_name = env_name or os.getenv("FLASK_ENV", "development")
    config_cls = config_by_name.get(env_name, config_by_name["development"])

    app = Flask(__name__)
    app.config.from_object(config_cls)

    _validate_config(app, env_name)
    _init_db(app)
    _init_storage(app)
    csrf.init_app(app)  # 모든 쓰기 요청(POST 등)에 CSRF 토큰 검사
    _register_blueprints(app)
    _register_error_handlers(app)
    _init_logging(app)

    return app


# ──────────────────────────────────────────────
# 내부 초기화 함수
# ──────────────────────────────────────────────
def _validate_config(app: Flask, env_name: str) -> None:
    """필수 비밀값 검증. 운영 환경에서 기본값으로 기동되는 사고를 막는다(Fail-fast)."""
    salt = app.config["MASTER_SALT"]
    if env_name == "production":
        if app.config["SECRET_KEY"] in ("", "dev-only-secret", "change-me"):
            raise RuntimeError("운영 환경에서는 SECRET_KEY 를 반드시 설정해야 합니다.")
        if len(salt) < 32 or salt == "change-me":
            raise RuntimeError("운영 환경에서는 32자 이상의 MASTER_SALT 가 필요합니다.")
    elif not salt or salt == "change-me":
        app.logger.warning("MASTER_SALT 가 설정되지 않았습니다. 개발용으로만 사용하세요.")


def _init_db(app: Flask) -> None:
    """DB 커넥션 정리 훅 등록 (PyMySQL 직접 사용, ORM 미사용)"""
    db.init_app(app)


def _init_storage(app: Flask) -> None:
    """암호화 이미지 저장 디렉토리 생성 (소유자만 접근 가능하도록 0700)"""
    storage_dir = app.config["STORAGE_DIR"]
    storage_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(storage_dir, 0o700)


def _register_blueprints(app: Flask) -> None:
    """라우트(블루프린트) 등록 — 기능별 모듈이 추가되면 여기에 등록한다."""
    from .routes.auth import bp as auth_bp  # 전역 로그인 가드(before_app_request) 포함
    from .routes.main import bp as main_bp
    from .routes.photo import bp as photo_bp
    from .routes.api import bp as api_bp
    from .routes.diary import bp as diary_bp
    from .routes.backup import bp as backup_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(photo_bp, url_prefix="/photos")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(diary_bp, url_prefix="/diary")
    app.register_blueprint(backup_bp, url_prefix="/backup")
    # 다음 단계에서 추가 예정:
    # from .routes.note import bp as note_bp;   app.register_blueprint(note_bp,  url_prefix="/notes")


def _register_error_handlers(app: Flask) -> None:
    """공통 에러 응답"""

    @app.errorhandler(413)
    def too_large(_e):
        limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return jsonify(error=f"업로드 용량 초과 (최대 {limit_mb}MB)"), 413

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify(error="요청한 리소스를 찾을 수 없습니다."), 404


def _init_logging(app: Flask) -> None:
    """운영 환경에서는 회전 파일 로그(LOG_DIR/tracepic.log, 기본 ../tracepic_logs) 사용"""
    if app.debug:
        return
    log_dir = app.config["LOG_DIR"]
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "tracepic.log", maxBytes=5 * 1024 * 1024, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


__all__ = ["create_app"]
