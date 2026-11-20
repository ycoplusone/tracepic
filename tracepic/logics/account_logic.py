"""
계정 로직: 메일 가입 신청 · 관리자 승인 · 비밀번호 재설정 (2026-11-20)

테이블
- tracepic_signup      : 가입 신청. V(메일 인증 대기) → P(승인 대기) → A(승인) / R(거절)
- tracepic_email_codes : 메일 인증 코드. purpose S(가입) / R(비밀번호 재설정). 코드는 HMAC 값만 저장
- user_info (공유)     : 승인하는 순간에만 INSERT(user_id = email), 재설정 때만 password UPDATE

규칙
- 승인 전 신청자는 user_info 에 없으므로 다른 서비스에도, TracePic 로그인에도 보이지 않는다.
- 비밀번호는 신청 때부터 bcrypt 해시로만 보관한다.
- 메일 주소는 소문자로 맞추고, user_info.user_id(varchar 50)에 들어가도록 50자 이하만 받는다.
"""
import hashlib
import hmac
import re
import secrets

from flask import current_app

from ..db import fetch_all, fetch_one, transaction
from ..utils.password import hash_password, verify_password

PURPOSE_SIGNUP = "S"
PURPOSE_RESET = "R"
EMAIL_MAX = 50      # user_info.user_id 길이 (메일을 아이디로 그대로 쓰므로)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SIGNUP_STATUS_LABELS = {"V": "메일 인증 대기", "P": "승인 대기", "A": "승인", "R": "거절"}


class CodeError(ValueError):
    """인증 코드 발급·확인 실패 (메시지를 화면에 그대로 보여 준다)"""


# ============================================================
# 공통: 메일 주소 · 인증 코드
# ============================================================
def normalize_email(raw: str | None) -> str:
    """메일 주소 정리(앞뒤 공백 제거·소문자) + 형식/길이 확인 → ValueError"""
    email = (raw or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("메일 주소 형식이 올바르지 않습니다.")
    if len(email) > EMAIL_MAX:
        raise ValueError(f"메일 주소는 {EMAIL_MAX}자 이하여야 합니다 (아이디로 사용).")
    return email


def _code_hash(purpose: str, email: str, code: str) -> str:
    """인증 코드 → HMAC-SHA256 (SECRET_KEY). 용도·메일을 함께 묶어 다른 곳에 재사용할 수 없게 한다"""
    key = current_app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(key, f"{purpose}:{email}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def issue_code(purpose: str, email: str) -> str:
    """새 6자리 코드 발급 → 코드 문자열 (호출한 쪽이 메일로 보낸다)

    - 같은 메일·용도로 EMAIL_CODE_RESEND_SECONDS 안에 다시 받거나, 1시간에 EMAIL_CODE_HOURLY_MAX 를 넘으면 CodeError
    - 새 코드를 만들면 이전에 받은 코드는 바로 만료시킨다 (마지막 코드만 유효)
    """
    cfg = current_app.config
    row = fetch_one(
        """
        SELECT COUNT(*) AS n,
               SUM(created_at > NOW() - INTERVAL %s SECOND) AS recent
          FROM tracepic_email_codes
         WHERE email = %s AND purpose = %s AND created_at > NOW() - INTERVAL 1 HOUR
        """,
        (cfg["EMAIL_CODE_RESEND_SECONDS"], email, purpose),
    )
    if row and row["recent"]:
        raise CodeError(f"인증 메일을 방금 보냈습니다. {cfg['EMAIL_CODE_RESEND_SECONDS']}초 뒤에 다시 받을 수 있습니다.")
    if row and row["n"] >= cfg["EMAIL_CODE_HOURLY_MAX"]:
        raise CodeError("인증 메일을 너무 많이 요청했습니다. 1시간 뒤에 다시 시도하세요.")

    code = f"{secrets.randbelow(10**6):06d}"
    with transaction() as cur:
        cur.execute(
            "UPDATE tracepic_email_codes SET expires_at = NOW() "
            "WHERE email = %s AND purpose = %s AND used_at IS NULL AND expires_at > NOW()",
            (email, purpose),
        )
        cur.execute(
            "INSERT INTO tracepic_email_codes (purpose, email, code_hash, expires_at) "
            "VALUES (%s, %s, %s, NOW() + INTERVAL %s MINUTE)",
            (purpose, email, _code_hash(purpose, email, code), cfg["EMAIL_CODE_MINUTES"]),
        )
    return code


def _check_code(cur, purpose: str, email: str, code: str) -> str | None:
    """트랜잭션 안에서 코드 확인 → 실패 메시지(str) 또는 None(성공, 사용 처리까지 끝냄)

    틀린 횟수는 실패해도 저장돼야 하므로 예외를 던지지 않고 메시지를 돌려준다(호출한 쪽이 커밋 후 처리).
    """
    max_tries = current_app.config["EMAIL_CODE_MAX_TRIES"]
    cur.execute(
        """
        SELECT code_id, code_hash, attempts, expires_at > NOW() AS alive
          FROM tracepic_email_codes
         WHERE email = %s AND purpose = %s AND used_at IS NULL
         ORDER BY code_id DESC LIMIT 1
           FOR UPDATE
        """,
        (email, purpose),
    )
    row = cur.fetchone()
    if not row or not row["alive"] or row["attempts"] >= max_tries:
        return "인증 코드가 없거나 만료되었습니다. 코드를 다시 받아 주세요."
    if not re.fullmatch(r"\d{6}", code or "") or not hmac.compare_digest(
        row["code_hash"], _code_hash(purpose, email, code)
    ):
        cur.execute("UPDATE tracepic_email_codes SET attempts = attempts + 1 WHERE code_id = %s", (row["code_id"],))
        left = max_tries - row["attempts"] - 1
        if left <= 0:
            return "인증 코드를 너무 많이 틀렸습니다. 코드를 다시 받아 주세요."
        return f"인증 코드가 맞지 않습니다. (남은 횟수 {left}번)"
    cur.execute("UPDATE tracepic_email_codes SET used_at = NOW() WHERE code_id = %s", (row["code_id"],))
    return None


def account_exists(email: str) -> bool:
    """user_info 에 이 메일이 아이디나 메일로 이미 있는지"""
    return fetch_one(
        "SELECT 1 AS x FROM user_info WHERE user_id = %s OR email = %s LIMIT 1", (email, email)
    ) is not None


# ============================================================
# 가입 신청
# ============================================================
def start_signup(email: str, password: str) -> None:
    """가입 신청 저장(V) — 이미 계정이 있거나 승인 대기 중이면 ValueError. 인증 대기(V) 신청이 있으면 비밀번호만 새로"""
    if account_exists(email):
        raise ValueError("이미 가입된 메일입니다. 로그인하거나 비밀번호 찾기를 이용하세요.")
    hashed = hash_password(password)
    with transaction() as cur:
        cur.execute(
            "SELECT signup_id, status FROM tracepic_signup WHERE email = %s AND status IN ('V','P') "
            "ORDER BY signup_id DESC LIMIT 1 FOR UPDATE",
            (email,),
        )
        row = cur.fetchone()
        if row and row["status"] == "P":
            raise ValueError("이미 가입 신청이 접수되어 관리자 승인을 기다리고 있습니다.")
        if row:
            cur.execute(
                "UPDATE tracepic_signup SET password = %s, updated_at = NOW() WHERE signup_id = %s",
                (hashed, row["signup_id"]),
            )
        else:
            cur.execute("INSERT INTO tracepic_signup (email, password) VALUES (%s, %s)", (email, hashed))


def verify_signup(email: str, code: str) -> None:
    """가입 메일 인증 → 승인 대기(P). 실패하면 CodeError"""
    with transaction() as cur:
        error = _check_code(cur, PURPOSE_SIGNUP, email, code)
        if error is None:
            cur.execute(
                "UPDATE tracepic_signup SET status = 'P', verified_at = NOW(), updated_at = NOW() "
                "WHERE email = %s AND status = 'V'",
                (email,),
            )
            if cur.rowcount == 0:
                error = "가입 신청을 찾을 수 없습니다. 처음부터 다시 신청해 주세요."
    if error:
        raise CodeError(error)


def has_waiting_signup(email: str) -> bool:
    """메일 인증을 기다리는(V) 신청이 있는지 — 코드 재발송 전에 확인"""
    return fetch_one(
        "SELECT 1 AS x FROM tracepic_signup WHERE email = %s AND status = 'V' LIMIT 1", (email,)
    ) is not None


def pending_status(user_id: str, password: str) -> str | None:
    """로그인 실패 안내용: 비밀번호가 맞는 진행 중 신청이 있으면 그 상태(V/P), 아니면 None

    비밀번호까지 맞아야 알려 주므로, 남의 메일로 가입 신청 여부를 떠볼 수 없다.
    """
    try:
        email = normalize_email(user_id)
    except ValueError:
        return None
    row = fetch_one(
        "SELECT password, status FROM tracepic_signup WHERE email = %s AND status IN ('V','P') "
        "ORDER BY signup_id DESC LIMIT 1",
        (email,),
    )
    if row and verify_password(password, row["password"]):
        return row["status"]
    return None


# ============================================================
# 관리자: 승인 / 거절
# ============================================================
def list_signups(limit: int = 100) -> list[dict]:
    """관리자 화면용 신청 목록 — 승인 대기(P)를 먼저, 나머지는 최근 순 (비밀번호 해시는 꺼내지 않음)"""
    return fetch_all(
        """
        SELECT signup_id, email, status, verified_at, decided_at, decided_by, created_at
          FROM tracepic_signup
         ORDER BY status = 'P' DESC, signup_id DESC
         LIMIT %s
        """,
        (limit,),
    )


def approve_signup(signup_id: int, admin_user_id: str) -> str | None:
    """승인: user_info 에 계정 추가(user_id = email, role user) → 메일 주소. 대상이 없으면 None, 이미 계정이 있으면 ValueError"""
    with transaction() as cur:
        cur.execute(
            "SELECT email, password FROM tracepic_signup WHERE signup_id = %s AND status = 'P' FOR UPDATE",
            (signup_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            "SELECT 1 AS x FROM user_info WHERE user_id = %s OR email = %s LIMIT 1", (row["email"], row["email"])
        )
        if cur.fetchone():
            raise ValueError("같은 아이디나 메일의 계정이 이미 있어 승인할 수 없습니다. 거절해 주세요.")
        cur.execute(
            "INSERT INTO user_info (user_id, password, email, role) VALUES (%s, %s, %s, 'user')",
            (row["email"], row["password"], row["email"]),
        )
        cur.execute(
            "UPDATE tracepic_signup SET status = 'A', decided_at = NOW(), decided_by = %s, updated_at = NOW() "
            "WHERE signup_id = %s",
            (admin_user_id, signup_id),
        )
    return row["email"]


def reject_signup(signup_id: int, admin_user_id: str) -> str | None:
    """거절 → 메일 주소. 승인 대기(P)가 아니면 None"""
    with transaction() as cur:
        cur.execute(
            "SELECT email FROM tracepic_signup WHERE signup_id = %s AND status = 'P' FOR UPDATE", (signup_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            "UPDATE tracepic_signup SET status = 'R', decided_at = NOW(), decided_by = %s, updated_at = NOW() "
            "WHERE signup_id = %s",
            (admin_user_id, signup_id),
        )
    return row["email"]


def admin_emails() -> list[str]:
    """새 신청 알림을 받을 관리자 메일 목록"""
    rows = fetch_all("SELECT email FROM user_info WHERE role = 'admin' AND email <> ''", ())
    return [r["email"] for r in rows]


# ============================================================
# 비밀번호 재설정
# ============================================================
def find_account_by_email(email: str) -> dict | None:
    """메일로 계정 찾기 → {user_id} 또는 None"""
    return fetch_one("SELECT user_id FROM user_info WHERE email = %s", (email,))


def reset_password(email: str, code: str, new_password: str) -> str:
    """코드 확인 후 user_info.password 를 bcrypt 로 바꿈 → user_id. 실패하면 CodeError"""
    hashed = hash_password(new_password)
    user_id = None
    with transaction() as cur:
        error = _check_code(cur, PURPOSE_RESET, email, code)
        if error is None:
            cur.execute("SELECT id, user_id FROM user_info WHERE email = %s FOR UPDATE", (email,))
            user = cur.fetchone()
            if user is None:
                error = "계정을 찾을 수 없습니다."
            else:
                cur.execute("UPDATE user_info SET password = %s WHERE id = %s", (hashed, user["id"]))
                user_id = user["user_id"]
    if error:
        raise CodeError(error)
    return user_id
