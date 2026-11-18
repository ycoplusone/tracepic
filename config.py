"""
TracePic 설정 모듈
- .env 파일의 환경 변수를 읽어 Flask 설정 클래스로 제공한다.
- 환경(development / production)에 따라 설정 클래스를 분리한다.
"""
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

# 프로젝트 루트 경로 및 .env 로딩 (이미 OS 환경 변수가 있으면 그 값을 우선)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _build_db_config() -> dict:
    """
    PyMySQL connect() 에 그대로 넘길 접속 정보 dict 생성
    1순위: DATABASE_URL  (예: mysql+pymysql://user:pass@host:3306/dbname?charset=utf8mb4)
    2순위: DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME 개별 변수
    """
    url = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
    if url:
        parts = urlsplit(url)
        return {
            "host": parts.hostname or "127.0.0.1",
            "port": parts.port or 3306,
            "user": unquote(parts.username or ""),
            "password": unquote(parts.password or ""),  # URL 인코딩된 특수문자 복원
            "database": parts.path.lstrip("/"),
        }
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "tracepic"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "tracepic"),
    }


def _resolve_dir(env_key: str, default_name: str) -> Path:
    """
    디렉토리 경로 결정
    - 환경 변수가 없으면 프로젝트 상위 폴더의 형제 디렉토리 사용 (예: ../tracepic_storage)
    - 상대 경로는 실행 위치(CWD)가 아닌 프로젝트 루트 기준으로 해석
    """
    raw = os.getenv(env_key, "").strip()
    path = Path(raw).expanduser() if raw else BASE_DIR.parent / default_name
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


class BaseConfig:
    """모든 환경 공통 설정"""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret")

    # ── DB (PyMySQL 직접 사용, ORM 미사용) ──
    DB_CONFIG = _build_db_config()
    # 커넥션 풀 (db.py): 요청마다 원격 MySQL 에 새로 접속하지 않고 재사용한다 — gunicorn 워커(프로세스)마다 따로 가진다
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))            # 보관할 유휴 커넥션 수 (넘치면 닫음)
    DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))   # 이 시간(초)보다 오래된 커넥션은 새로 연결 (서버 wait_timeout 28800 보다 짧게)
    DB_POOL_PING_IDLE = int(os.getenv("DB_POOL_PING_IDLE", "60")) # 이 시간(초) 이상 쉬었던 커넥션은 꺼내기 전에 ping 으로 살아 있는지 확인
    # 로그인 확인 결과를 워커 메모리에 잠깐 보관하는 시간(초). 0 이면 매 요청 DB 확인 (routes/auth.py)
    AUTH_CACHE_SECONDS = int(os.getenv("AUTH_CACHE_SECONDS", "60"))

    # ── 암호화 ──
    MASTER_SALT = os.getenv("MASTER_SALT", "")

    # ── 파일 저장소 / 업로드 ──
    # 저장소·로그는 프로젝트 외부(형제 폴더)에 둔다 → 배포/재설치 시 데이터 보존, Git 오염 방지
    STORAGE_DIR = _resolve_dir("STORAGE_DIR", "tracepic_storage")
    LOG_DIR = _resolve_dir("LOG_DIR", "tracepic_logs")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "30")) * 1024 * 1024
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "heic", "webp"}

    # ── 이미지 리사이징 ──
    IMAGE_MAX_SIDE = int(os.getenv("IMAGE_MAX_SIDE", "2048"))
    IMAGE_JPEG_QUALITY = int(os.getenv("IMAGE_JPEG_QUALITY", "85"))

    # ── 로그인 / 세션 ──
    # 기기 토큰 유효기간 (user_devices.expires_at, 기존 데이터와 동일하게 180일)
    DEVICE_TOKEN_DAYS = int(os.getenv("DEVICE_TOKEN_DAYS", "180"))
    PERMANENT_SESSION_LIFETIME = timedelta(days=DEVICE_TOKEN_DAYS)  # 세션 쿠키도 같은 기간 유지
    LOGIN_MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "5"))        # 아이디당 허용 실패 횟수
    LOGIN_LOCK_MINUTES = int(os.getenv("LOGIN_LOCK_MINUTES", "10"))  # 초과 시 잠금 시간
    SESSION_COOKIE_NAME = "tracepic_session"

    # ── 세션 쿠키 보안 ──
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True  # HTTPS 전용 쿠키 (Nginx + TLS 전제)


# FLASK_ENV 값 → 설정 클래스 매핑
config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
