"""
메일 발송 유틸 (SMTP)

- 설정은 config 의 SMTP_* / MAIL_FROM (값은 .env 에만).
- 587 이면 STARTTLS, 465 면 SSL 로 접속한다. OCI 는 25 번 포트를 막으므로 쓰지 않는다.
- SMTP_HOST 가 비어 있으면 실제로 보내지 않고 로그에 남긴다(개발용). 운영에서는 반드시 설정한다.
- 실패하면 MailError 를 던진다. 호출한 쪽이 사용자에게 알맞은 메시지를 보여 준다.
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from flask import current_app


class MailError(Exception):
    """메일을 보내지 못함 (접속·인증·수신 거부 등)"""


def send_mail(to: str, subject: str, body: str) -> None:
    """평문 메일 한 통 보내기"""
    cfg = current_app.config
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["MAIL_FROM"] or cfg["SMTP_USER"]
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="tracepic.local")
    msg.set_content(body)

    if not cfg["SMTP_HOST"]:
        # 개발용: 메일 대신 로그 (인증 코드가 로그에 남으므로 운영에서는 쓰지 않는다)
        current_app.logger.warning("[메일 미발송: SMTP_HOST 없음] to=%s subject=%s\n%s", to, subject, body)
        return

    port = cfg["SMTP_PORT"]
    context = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(cfg["SMTP_HOST"], port, timeout=20, context=context)
        else:
            server = smtplib.SMTP(cfg["SMTP_HOST"], port, timeout=20)
        with server:
            if port != 465:
                server.starttls(context=context)
            if cfg["SMTP_USER"]:
                server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            refused = server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        # 비밀번호·키는 로그에 남기지 않는다 (예외 메시지에는 서버 응답만 있음)
        current_app.logger.error("메일 발송 실패: to=%s error=%s", to, e)
        raise MailError("메일을 보내지 못했습니다. 잠시 후 다시 시도하세요.") from e
    if refused:
        raise MailError("받는 메일 주소가 거부되었습니다.")
