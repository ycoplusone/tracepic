# CLAUDE.md — TracePic 개발 가이드

이 파일은 TracePic 프로젝트의 **개발 규칙과 핵심 결정사항**을 담습니다.
중요한 결정이나 구조 변경이 생기면 그때마다 이 파일을 갱신합니다.
(프로젝트 소개와 디렉토리별 역할은 `README.md`에 있습니다.)

## 프로젝트 요약
- 개인용 여행 아카이빙 플랫폼입니다. 사진 EXIF(GPS·촬영시간)를 Leaflet 지도에 표시하고, 마크다운 기록과 암호화된 이미지를 보관합니다.
- 스택: Python 3.14 / Flask 3.1 / PyMySQL(ORM 미사용) / MySQL(utf8mb4) / Pillow / cryptography
- 배포: Oracle Cloud Linux, Nginx → gunicorn(`app:app`, 127.0.0.1:5555) — 개발 서버도 5555 (5000은 다른 개발 서비스가 사용 중, 2026-11-17 변경)

## 개발 원칙 (반드시 지킬 것)
1. **계층 분리**: `routes`(요청/응답) → `logics`(비즈니스 로직 + SQL) → `db.py`(PyMySQL 헬퍼). DB와 무관한 순수 기능은 `utils/`, 화면은 `templates/`·`static/`에 둡니다.
   - 라우트에 로직이나 SQL을 직접 쓰지 않습니다.
   - logics 파일 이름은 기능별 `*_logic.py`로 짓습니다(예: `photo_logic.py`, `note_logic.py`, `daily_logic.py`).
2. **비밀값은 `.env`로만 관리**: DB 접속 정보, `SECRET_KEY`, `MASTER_SALT`를 코드에 하드코딩하지 않습니다. 새 환경 변수가 생기면 `.env.example`과 `config.py`를 함께 갱신합니다.
3. **한국어 주석**: 모든 코드에 핵심을 설명하는 한국어 주석을 답니다.
4. **ORM을 쓰지 않습니다** (사용자 결정 — 직관성 우선). SQLAlchemy나 Flask-SQLAlchemy를 다시 들이지 않습니다.
   - DB 접근은 `tracepic/db.py`의 `fetch_one`, `fetch_all`, `execute`(단건 실행 후 즉시 커밋, INSERT면 새 id 반환), `transaction()`(여러 SQL 묶기)만 씁니다.
   - 값은 **반드시 `%s` 파라미터 바인딩**으로 넘깁니다. f-string이나 `+`로 SQL을 조립하지 않습니다(SQL 인젝션 방지).
   - 커넥션은 `db.py`의 풀에서 요청마다 하나 빌려 `flask.g`에 두고, 요청이 끝나면 롤백한 뒤 풀에 돌려줍니다(닫지 않음). 쓰기는 반드시 commit을 거쳐야 합니다.
   - 풀은 프로세스(gunicorn 워커)마다 따로 만들고, 오래된 커넥션(`DB_POOL_RECYCLE`)은 새로 연결하며, 오래 쉰 커넥션(`DB_POOL_PING_IDLE`)은 ping으로 확인합니다.
5. 새 블루프린트는 `tracepic/__init__.py`의 `_register_blueprints()`에 등록합니다.
6. 패키지 이름은 `tracepic/`을 씁니다. `app/`으로 바꾸면 루트의 `app.py`와 이름이 겹쳐 import가 꼬입니다.

## 실행 / 검증
```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py                       # 개발 서버
.venv/bin/python -c "from app import app; print(app.test_client().get('/health').json)"
```
- DB가 없으면 `/health`는 503을 반환합니다. 이 경우는 정상입니다.

## 인증(로그인) 설계
- **공유 테이블**: `user_info`, `user_devices`는 다른 서비스와 같이 씁니다.
  - `user_info`는 **읽기만** 합니다. 컬럼을 바꾸지 않습니다.
    - 예외 (모두 2026-11-20 사용자 결정, 다른 서비스도 bcrypt 검증 지원 확인):
      - 평문 비밀번호 → bcrypt 일괄 변환(`scripts/hash_passwords.py` → `auth_logic.hash_plain_passwords`). 이미 해시인 행은 건너뜁니다.
      - 관리자가 가입을 **승인할 때만** INSERT(`account_logic.approve_signup`, user_id = email, role `user`).
      - 비밀번호 재설정 때만 해당 행의 `password` UPDATE(`account_logic.reset_password`).
      - 그 밖의 컬럼(role 등)은 TracePic이 바꾸지 않습니다. 관리자 지정은 DB에서 직접 합니다.
  - `user_devices`에는 TracePic이 발급한 토큰만 INSERT(로그인)하고 DELETE(로그아웃)합니다. 다른 행은 건드리지 않습니다.
  - `user_devices` 중 8건은 `user_info`에 없는 아이디입니다(다른 서비스 데이터로 추정). 그래서 검증할 때 `user_info`와 JOIN합니다.
- **비밀번호**: `utils/password.py`가 저장값 형식을 보고 bcrypt, werkzeug, 평문(`compare_digest`) 중 맞는 방식으로 검증합니다.
  - 2026-11-20 개발 DB의 5명 모두 **bcrypt(`$2b$12$`, 60자)로 변환**했습니다. 평문 분기는 다른 서비스가 새로 평문으로 넣은 행에 대한 호환용으로만 남깁니다.
  - 운영 DB가 따로 있으면 서버에서도 `.venv/bin/python scripts/hash_passwords.py --dry-run`으로 건수를 확인한 뒤 실행합니다(되돌릴 수 없음).
  - 새 비밀번호를 만들 때는 `hash_password()`(bcrypt, 72바이트 제한)를 씁니다.
  - ⚠️ `password` 컬럼은 일부 문자열이라도 SELECT 결과로 출력하지 않습니다. 형식을 확인할 때는 `LENGTH`, `LIKE '$2%'` 같은 집계만 씁니다.
- **흐름**: `routes/auth.py`의 `require_login`(`before_app_request`)이 모든 요청을 검사합니다. 세션에는 `user_id`와 `device_token`만 저장합니다(서명된 쿠키 `tracepic_session`, 180일).
  - 공개 엔드포인트는 `PUBLIC_ENDPOINTS`에 등록합니다(현재 `auth.login`, `main.health`, `static`). 새 공개 페이지는 반드시 여기에 추가합니다.
  - 로그인한 사용자 정보는 `g.user`로 꺼내 씁니다(`id`, `user_id`, `email`, `role`). 사진 같은 데이터의 소유자 확인은 `g.user["user_id"]`로 합니다.
  - `/api/*`는 로그인하지 않았을 때 401 JSON을 돌려줍니다.
- **TODO**
  - ~~CSRF 토큰 도입~~ → 4회차에 완료했습니다. `utils/csrf.py`가 모든 POST/PUT/PATCH/DELETE를 검사합니다.
    - 새 폼에는 `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`를 넣습니다. fetch나 XHR 요청은 `<meta name="csrf-token">` 값을 `X-CSRF-Token` 헤더로 보냅니다.
  - 배포할 때 **ProxyFix**를 적용합니다. 그래야 로그인 실패 제한이 실제 클라이언트 IP로 동작합니다.
  - 로그인 실패 제한은 메모리 기반이라 gunicorn 워커마다 따로 집계됩니다.

## 앱 API — 휴대폰 업로드 앱 (`/api/app/*`, 2026-11-20)
- 배경: 안드로이드는 휴대폰 안의 사진을 브라우저에 넘길 때 GPS를 지웁니다(크롬에 '미디어 위치 접근' 권한 없음). 그래서 권한을 받는 전용 앱이 원본을 보내는 경로를 만듭니다.
- `routes/app_api.py`(블루프린트 `app_api`):
  - `POST /login`: JSON/폼 `user_id`, `password`, `device_name` → `{ok, user_id, device_token, expires_days}`. 웹 로그인과 같은 bcrypt 검증, 실패 횟수 제한, 승인 대기 안내를 씁니다. 토큰은 `user_devices`에 INSERT(user_agent `TracePic App (기기 이름)`).
  - `GET /me`(토큰 확인), `POST /upload`(웹 업로드와 같은 `photo.handle_upload`), `POST /logout`(이 토큰만 DELETE).
- 인증: 헤더 `X-User-Id` + `Authorization: Bearer <device_token>`(권장), 또는 폼 필드 `user_id`, `device_token`. `require_login`이 이 블루프린트는 **토큰으로만** 확인하고 세션은 읽지도 쓰지도 않습니다. 쿠키로 인증되지 않으므로 CSRF 검사에서 뺍니다(`utils/csrf.py`). 세션 쿠키만 있는 요청은 401입니다.
- 업로드 보조 값: `latitude`/`longitude`는 파일에 GPS가 없을 때만 씁니다(0,0·범위 밖은 무시). 앱이 줄여 보내거나 EXIF가 빠질 때를 위한 값입니다.
- ⚠️ 비밀번호와 토큰이 오가므로 **실사용은 HTTPS에서만** 합니다. 중복 업로드 방지(원본 해시)는 아직 없습니다(DDL 필요 — 사용자 확인 후).

## 동영상 → 움직이는 WebP 클립 (2026-11-20)
- **동영상 자체는 보관하지 않습니다.** 업로드한 영상의 **3~7초 구간(4초)**만 잘라 움직이는 WebP 3개(image 짧은 변 720px / thumb 긴 변 400px / mini 128px 정사각형, 10fps, 소리 없음)를 만들어 사진과 같은 자리(`.enc`/`.thumb.enc`/`.mini.enc`)에 암호화 저장합니다. DB 구조·지도·필름·크게 보기는 사진과 같습니다(`<img>`로 재생).
  - 7초보다 짧으면 끝 4초, 4초보다 짧으면 전부를 씁니다(`video.clip_window`).
  - 사진인지 클립인지는 복호화한 내용이 WebP인지로 구분합니다(`video.is_webp`). 이미지 응답의 Content-Type, 백업 zip 확장자(`.webp`, EXIF 안 넣음)가 이걸로 갈립니다.
- 변환은 ffmpeg로 합니다(`utils/video.py`). `-ss 3 -t 4`를 입력 앞에 둬서 7초 지점까지만 디코딩하고 멈춥니다. 프레임은 PNG로 파이프에 받아 메모리에서 Pillow로 WebP를 만듭니다(프레임을 디스크에 쓰지 않음).
  - ffmpeg 찾는 순서: `.env` `FFMPEG_PATH` → PATH의 `ffmpeg`(서버: `sudo apt install ffmpeg`) → 설치돼 있으면 `imageio-ffmpeg`. 없으면 업로드 화면에서 동영상 안내를 숨기고, 올리면 400입니다.
  - ffmpeg가 파일을 앞뒤로 읽어야 해서 업로드 영상을 `STORAGE_DIR/.tmp`(0700, 파일 0600)에 잠깐 쓰고, 성공·실패와 관계없이 바로 지웁니다. 다만 Flask가 큰 업로드를 시스템 임시 폴더에 먼저 받아 두는 것은 막지 않습니다(0600).
- 촬영 시각: 영상 메타데이터 → 브라우저가 보낸 파일 수정 시각 → 업로드 시각. `com.apple.quicktime.creationdate`(시간대 포함)는 그 현지 시각 그대로, `creation_time`(UTC, 안드로이드·DJI)은 업로드한 브라우저의 시간대(`tz_offset`, 동쪽 +분)로 바꿉니다. 시간대를 모르면 UTC 값을 쓰지 않습니다.
- 위치: `com.apple.quicktime.location.ISO6709` / `location` / `location-eng`(ISO 6709). DJI Osmo는 대개 GPS가 없어 위치 없음으로 들어옵니다(크게 보기에서 직접 찍기).
- 크기 한도: 사진 `MAX_UPLOAD_MB`(30), 동영상 `MAX_VIDEO_MB`(500). `MAX_CONTENT_LENGTH`는 둘 중 큰 값 + 1MB입니다. **Nginx `client_max_body_size`도 500M 이상**이어야 하고, 변환에 수십 초가 걸릴 수 있으니 `proxy_read_timeout`·gunicorn `--timeout`을 넉넉히(300초) 둡니다.
- HDR·10bit·D-Log 영상은 색 변환(톤매핑)을 하지 않아 색이 흐리게 나올 수 있습니다.

## 메일 가입 · 관리자 승인 · 비밀번호 찾기 (2026-11-20)
- 메일 발송: `utils/mail.send_mail`(SMTP, 현재 Brevo). 설정은 `.env`의 `SMTP_HOST/PORT/USER/PASSWORD`, `MAIL_FROM`, 선택 `PUBLIC_BASE_URL`(메일 속 링크).
  - `SMTP_HOST`가 비면 보내지 않고 로그에 남깁니다(개발용 — 코드가 로그에 남으므로 운영에서는 반드시 설정).
  - Brevo는 등록한 IP에서만 보낼 수 있습니다. 서버 공인 IP를 Brevo Authorised IPs에 추가해야 합니다. SMTP 로그인은 계정 메일이 아니라 `…@smtp-brevo.com`입니다.
- 가입(`routes/account.py`, 공개): `/signup`(메일·비밀번호) → 인증 코드 메일 → `/signup/verify` → 승인 대기(P) → 관리자 승인 → user_info INSERT.
  - 신청은 `tracepic_signup`(V 메일 인증 대기 / P 승인 대기 / A 승인 / R 거절)에 bcrypt 해시로 보관합니다. 승인 전에는 user_info에 없으므로 다른 서비스와 로그인에 보이지 않습니다.
  - 메일 주소는 소문자로 맞추고 50자 이하(`user_info.user_id` varchar 50)만 받습니다. 아이디 = 메일 주소입니다.
  - 승인 전 로그인: 비밀번호까지 맞을 때만 '승인 대기' 안내를 보여 줍니다(아니면 공통 실패 메시지).
- 비밀번호 찾기(공개): `/password/forgot`(메일) → 코드 메일 → `/password/reset`(코드 + 새 비밀번호). **관리자 승인 없이 메일 인증만**으로 바뀝니다.
  - 계정이 있든 없든, 재발송 간격에 걸리든 화면 안내는 같습니다(가입 여부를 떠볼 수 없게). 바뀌면 그 메일로 알림을 보냅니다.
  - user_devices에서 TracePic 토큰만 골라낼 수 없어, 재설정 뒤에도 이미 로그인한 기기는 그대로입니다.
- 인증 코드(`tracepic_email_codes`): 6자리, `HMAC-SHA256(SECRET_KEY, 용도:메일:코드)`만 저장, 10분 유효, 5번 틀리면 무효, 새 코드를 받으면 이전 코드는 만료.
  - 같은 메일·용도: 60초 재발송 간격, 1시간 5통. 같은 IP: 1시간 10통(`account.MAIL_PER_IP_HOUR`, 워커 메모리 기준).
  - 값은 `config.py`의 `EMAIL_CODE_*`, 새 비밀번호 최소 길이는 `PASSWORD_MIN_LENGTH`(기본 8, 기존 4자리 비밀번호는 그대로 로그인됨).
- 관리자 화면 `/admin`(`routes/admin.py`): `g.user.role == 'admin'`만 들어가고 나머지는 404입니다. 상단 메뉴 '관리'도 관리자에게만 보입니다. 새 신청이 인증되면 관리자 메일(role admin, email 있음)로 알림이 갑니다.
  - role은 로그인 확인 캐시 때문에 바꾼 뒤 최대 `AUTH_CACHE_SECONDS`만큼 늦게 반영됩니다.

## 디렉토리 배치 (프로젝트 외부)
- 이미지 저장소: `../tracepic_storage` (`STORAGE_DIR`, 권한 0700)
- 로그: `../tracepic_logs` (`LOG_DIR`, 운영 환경에서만 파일 로그)
- 환경 변수가 없으면 프로젝트 상위 폴더의 형제 디렉토리를 씁니다. 상대 경로는 프로젝트 루트 기준으로 해석합니다(`config.py` `_resolve_dir`).
- 프로젝트 안에 `storage/`나 `logs/` 폴더를 다시 만들지 않습니다.

## 보안·암호화 결정사항
- 이미지 키 유도 방식은 `HKDF-SHA256(key material = MASTER_SALT, info = user_id)`로 **사용자마다 키 하나**를 만들고, 그 키로 Fernet 암호화합니다(2026-11-17 사용자 결정: 파일 타임스탬프는 키에서 뺌).
  - 같은 사용자의 파일은 키가 같지만, Fernet이 파일마다 무작위 IV와 HMAC을 써서 암호문은 매번 다릅니다.
  - 촬영 시간과 GPS는 저장 파일에 다시 넣지 않습니다(DB에만 기록, 2026-11-17 사용자 결정).
  - ⚠️ `user_id`가 바뀌면(계정 이름 변경 등) 그 사용자의 기존 파일을 복호화할 수 없습니다. 아이디를 바꿀 때는 파일을 다시 암호화해야 합니다.
- user_id는 DB에 평문으로 남습니다. 따라서 **실질적인 비밀은 `MASTER_SALT` 하나**입니다. 32자 이상 난수를 쓰고, 서버 밖에 반드시 백업합니다(잃으면 복구할 수 없습니다).
- 운영 환경(`FLASK_ENV=production`)에서는 `SECRET_KEY`가 기본값이거나 `MASTER_SALT`가 32자 미만이면 기동하지 않습니다.
- 암호화 파일은 `STORAGE_DIR`(권한 0700, 프로젝트 외부)에 저장하고, 반드시 라우트를 거쳐 복호화한 뒤에만 응답합니다. `static/`에 이미지를 두지 않습니다.
- 이미지 응답 캐시: 파일은 바뀌지 않으므로 `Cache-Control: private, max-age=31536000, immutable`과 ETag를 붙입니다. `If-None-Match`가 맞으면 **소유 확인만 하고** 304를 돌려줍니다(복호화 없음). 소유 확인을 304보다 먼저 하므로 남의 사진은 ETag를 알아도 404입니다.
- 로그인 확인 캐시: `routes/auth.py`가 (user_id, device_token) 확인 결과를 워커 메모리에 `AUTH_CACHE_SECONDS`(기본 60초)만큼 기억합니다. 실패 결과는 캐시하지 않고, 이 브라우저의 로그아웃은 즉시 지웁니다. 다른 기기나 다른 워커에서 토큰을 지운 경우에는 최대 그 시간만큼 늦게 반영됩니다.
- 파일 저장 규칙 (`logics/photo_file_logic.py`):
  - 경로: `STORAGE_DIR/{사용자폴더}/{base_dt}/{time_ns}.enc`(웹용), `{time_ns}.thumb.enc`(썸네일 400px), `{time_ns}.mini.enc`(마커용 128px 정사각형)입니다. DB의 `file_path`에는 웹용의 STORAGE_DIR 기준 상대 경로를 저장합니다.
  - 마커용 파일이 없는 예전 사진은 처음 `/photos/<id>/mini`를 요청할 때 썸네일로 만들어 저장합니다. 완전삭제할 때는 세 파일을 모두 지웁니다(`remove_files`).
  - 파일 이름의 `time_ns`는 이름이 겹치지 않게 하는 용도이며 키와는 관계없습니다. 키 유도에는 DB의 `user_id`를 씁니다.
  - 사용자 폴더는 아이디가 `[A-Za-z0-9_.-]`일 때만 그대로 쓰고, 아니면 sha256 앞 16자리를 씁니다(경로 조작 방지).
  - 원본은 보관하지 않습니다. 웹용 JPEG(긴 변 `IMAGE_MAX_SIDE`), 썸네일, 마커용만 저장하고, 파일에서는 EXIF(GPS 포함)를 지웁니다. 좌표는 DB에만 있습니다.
  - JPEG는 `open_image(max_side=...)`가 draft로 필요한 크기만큼만 디코딩합니다. 세 크기는 `normalize()`(회전·RGB 정리)를 한 번 거친 이미지로 만듭니다.
  - 촬영 시각은 EXIF → 브라우저가 보낸 파일 수정 시각 → 업로드 시각 순서로 정합니다. EXIF 시각은 시간대를 바꾸지 않고 현지 시각 그대로 씁니다.
  - 파일은 0600, 폴더는 0700 권한으로 만듭니다. `MASTER_SALT`가 비어 있으면 암호화를 거부합니다.
- 외부 스크립트(Leaflet 등)는 **버전을 고정하고 SRI(`integrity`)를 붙여서** 불러옵니다. 버전을 올릴 때는 해시도 다시 계산합니다.
- 지도 타일은 OpenStreetMap 공용 서버를 씁니다(개인 사용 규모 기준). 사용량이 늘면 타일 제공자를 바꿔야 합니다.
- 마크다운 입력칸(일기 본문, 사진 설명)은 **OverType 2.7.0**(jsDelivr, SRI) 편집기를 씁니다(2026-11-20 사용자 결정). `static/js/mdedit.js`의 `TPMd.attach(textarea)`가 textarea 자리에 끼우고 textarea처럼 쓰는 객체(`value`/`hidden`/`focus`/`addEventListener`)를 돌려줍니다. 스크립트를 못 불러오면 원래 textarea를 그대로 씁니다.
  - 저장은 그대로 마크다운 글자이고, 미리보기 탭과 화면 표시는 계속 서버 렌더(아래)를 씁니다. OverType의 보기 전환 버튼은 뺐습니다.
  - 두 겹(입력·서식 표시)의 글자 위치를 맞추려고 고정폭 글꼴만 씁니다. 일기 창은 `solar`(밝게), 사진 설명은 `auto`(화면 테마)입니다.
- 마크다운을 HTML로 변환한 결과는 항상 `nh3`로 살균(sanitize)한 뒤 렌더링합니다. 변환과 살균은 `utils/md.render()` 하나로만 합니다(미리보기도 같은 함수를 씁니다).
  - `<img>`는 `/photos/...` 내부 경로만 허용합니다. 외부 이미지는 열람 기록이 밖으로 새므로 막습니다.

## DB 환경 (개발)
- 서버: 원격 MySQL 8.0.46 (Ubuntu), DB 이름 `devDB`. **다른 서비스 테이블(nicon_*, received_* 등)과 함께 쓰는 공용 DB입니다.**
  - `tracepic_*` 테이블만 다룹니다. DB 전체에 영향을 주는 명령은 쓰지 않습니다. 테스트 데이터는 트랜잭션 안에서 롤백으로 정리합니다.
  - 테이블은 이미 만들어져 있습니다(DDL 원본: `sql/schema.sql`). logics의 SQL은 기존 DDL 컬럼에 맞춰 작성하고, DDL을 바꿀 때는 사용자 확인을 받고, `sql/schema.sql`도 같이 갱신합니다.
- 접속 설정: `.env`의 `DATABASE_URL`이 1순위이고, 없으면 `DB_*` 개별 변수로 조립합니다(`config.py` `_build_db_uri`).
- 서버 `wait_timeout`은 28800초이고, 앱 쪽 커넥션 재연결 주기(`DB_POOL_RECYCLE`)는 3600초입니다.
- 연결 확인: `/health` → `{"db":"ok"}` (2026-11-13 확인)

## DB 스키마 메모
- `tracepic_photos`: pic_id(PK), user_id, base_dt(YYYYMMDD), original_file_name, file_path, photo_at, latitude(10,7), longitude(11,7), status, created_at
- `tracepic_photos` 인덱스: `tracepic_photos_inx01 (base_dt, user_id)`, `tracepic_photos_inx02 (user_id, base_dt)`(2026-11-17 사용자 확인 후 추가 — 사용자별 기간 조회용)
- `tracepic_notes`: note_id(PK), pic_id, title, note(md), use_yn, created_at, updated_at — 사진별 기록. pic_id → tracepic_photos 외래키(`tracepic_notes_tracepic_photos_FK`)와 그 인덱스가 있습니다(사진 행을 지우지 않는 현재 규칙과 맞음).
- `tracepic_daily`: daily_id(PK), base_dt, user_id, title, note(md), use_yn, created_at, updated_at — **일별 요약 기록** (최초 명세에는 없었고 DB에서 확인)
- 공통: `updated_at`에 `ON UPDATE CURRENT_TIMESTAMP`가 없습니다 → 수정할 때 앱에서 직접 값을 넣어야 합니다.
- status 코드: a 완전공유 / b 부분공유 / c 나만 / d 삭제 / z 완전삭제
- **미결정 사항** (사용자 확인 필요)
  - status 기본값은 대문자 `'A'`인데 주석은 소문자입니다. 대문자 통일을 권장했고 아직 확정되지 않았습니다.
    현재 코드는 **대문자로 저장**하고, 비교는 콜레이션(`utf8mb4_unicode_ci`)이 대소문자를 구분하지 않아 양쪽 모두 동작합니다.
  - `tracepic_notes`에 user_id가 없습니다. 현재는 pic_id 조인으로 소유권을 확인합니다.
  - `tracepic_daily`의 인덱스 이름이 `tracepic_photos_inx01`로 되어 있습니다(복사 흔적으로 보이며, 동작에는 문제없음).
  - `base_dt` 주석 오타 "촤열" → "촬영"
- `tracepic_signup` / `tracepic_email_codes` (2026-11-20 사용자 확인 후 추가): 가입 신청 / 메일 인증 코드. 컬럼은 `sql/schema.sql` 참고

## CRUD 로직 규칙 (photo / note / daily)
- 모든 함수는 첫 인자로 `user_id`를 받고 SQL에 소유자 조건을 겁니다. 대상이 없거나 남의 데이터면 `None` / `False`를 돌려주고, 입력값이 잘못되면 `ValueError`를 던집니다.
- 행을 DELETE하지 않습니다. 사진은 `status`(D 휴지통 → Z 완전삭제), 기록은 `use_yn='N'`으로 표시합니다.
  - `purge_photo()`는 지울 암호화 파일 경로만 돌려줍니다. 실제 파일 삭제는 호출한 쪽(라우트)이 합니다.
- 사진의 공개 범위 기본값은 `C`(나만)입니다. 휴지통(D)이나 완전삭제(Z) 상태인 사진의 기록은 보이지 않습니다.
- 좌표가 없으면 NULL로 저장합니다. 지도 조회에서는 NULL과 0,0을 GPS 없음으로 보고 뺍니다(`has_location`).
- `tracepic_daily`는 날짜·사용자당 사용 중인 행 1건으로 운영합니다. `save_daily()`가 `FOR UPDATE`로 잠근 뒤 수정하거나 추가합니다.
- `updated_at`은 수정할 때 `NOW()`를 직접 넣습니다.
- SQL은 조건에 따라 문자열을 조립하지 않고 완성된 리터럴로 씁니다. `IN %s`에는 튜플을 바인딩합니다.
- base_dt 검증과 변환은 `utils/dates.py`(`validate_base_dt`, `to_base_dt`)를 씁니다.

## 지도 화면 규칙 (`/`)
- 조회 조건: 기간(기본 **이번 달 1일 ~ 오늘**, 브라우저 현지 날짜) + 상태(`?status=A,B,C`, 기본은 A/B/C). 상태 조건 검증은 `photo_logic.check_status_filter`가 하고, Z(완전삭제)는 고를 수 없습니다.
- 날짜 목록은 조회 기간 안에서 사진이 있는 날을 **일자별(오름차순)**로 보여 줍니다(`/api/photo-dates?start=&end=`). 날짜를 누르면 그날만 지도에 표시하고, 조회 기간은 그대로 둡니다. '기간 전체'나 같은 날을 다시 누르면 기간 전체로 돌아갑니다. '전체' 버튼은 사진이 있는 첫날~마지막 날로 기간을 넓힙니다.
- 주소: `?start=&end=&day=&status=` (day는 고른 날, 없으면 기간 전체)
- `/api/map-photos`는 위치 없는 사진도 촬영 시각순으로 함께 돌려줍니다(lat/lng = null). 지도에는 위치 있는 사진만 찍고, '촬영 순서 필름'에는 모두 보여 줍니다. 순번은 조회 결과 안에서 1부터 매깁니다.
- 필름 키보드: Tab 정지점은 선택된 사진 하나뿐이고(roving tabindex, `syncTabStop`), 필름 안에서는 ← → / Home / End로 옮기며 Enter로 크게 봅니다. 방향키 이동은 위치 없는 사진이어도 크게 보기를 열지 않습니다(클릭만 바로 엽니다). 포커스가 아무 데도 없을 때(body)도 ← →가 필름을 넘기고, 입력칸·Leaflet 지도에 포커스가 있으면 그쪽에 맡깁니다.
- 위치 찍기·수정: 크게 보기의 작은 지도(`#pv-loc-map`, 처음 열 때 생성)에서 누르거나 핀을 끌어 정하고 `PATCH /api/photos/<id>` `{"latitude","longitude"}`(둘 다 null = 지우기) → `photo_logic.update_location`으로 저장합니다. 상태와 위치는 한 요청에 같이 보내지 않습니다. 휴지통(D) 사진은 바꿀 수 없습니다. 저장 뒤에는 다시 조회하지 않고 `draw(photos, true)`로 그립니다.
- 상태 변경은 `PATCH /api/photos/<id>` → `photo_logic.change_status`(A/B/C/D 사이 자유 이동, D→A/B/C가 복구)를 씁니다. 완전삭제(Z)는 파일 삭제가 함께 필요하므로 이 경로로는 할 수 없습니다.
- 사진 설명은 화면에서 **사진당 1건**(`tracepic_notes`에서 가장 먼저 쓴 사용 중인 기록)으로 다룹니다. 테이블은 여러 건을 허용하므로 나머지 기록은 지우지 않고 그대로 둡니다.
- 휴지통(D) 사진은 크게 보기는 되지만 설명은 숨기고 쓸 수도 없습니다. 복구하면 다시 보입니다.
- 상태 표시 색: A 초록 / B 주황 / C 흰색 / D 회색(흑백). CSS 변수 `--st-A`~`--st-D`로 바꿀 수 있습니다.
- 크게 보기의 사진은 사진 칸 안에 비율을 유지해 꽉 맞춥니다(`object-fit: contain`, 잘림 없음). 마커·필름 썸네일만 정사각형으로 잘라(`cover`) 보여 줍니다. Leaflet 기본 CSS가 마커 이미지 크기를 `auto`로 덮어쓰므로, 마커 크기 규칙은 `.leaflet-container .leaflet-marker-pane .photo-marker img`로 지정합니다.
- 설명이 있는 사진은 상태 테두리 바깥에 보라색 테두리(`--note`)를 한 겹 더 두릅니다. `/api/map-photos`의 `has_note`는 `note_logic.photo_ids_with_notes`로 한 번에 조회합니다(사진마다 쿼리하지 않음).

## 일기 화면 규칙 (`/diary`)
- 데이터는 `tracepic_daily`(하루 1건)를 씁니다. 저장은 `PUT /api/diary/<base_dt>`이고 body의 `mode`로 동작을 나눕니다.
  - `create`(`daily_logic.create_daily`): 그날 기록이 이미 있으면 덮어쓰지 않고 409를 돌려줍니다.
  - `update`(`daily_logic.update_daily`): `date`를 함께 보내면 기록을 그 날짜로 옮깁니다. 옮길 날짜에 기록이 있으면 409입니다. 날짜만 바뀌고 그날 사진은 그대로입니다.
  - `save_daily()`(있으면 수정, 없으면 작성)는 로직 함수로만 남겨 두었고, 화면에서는 쓰지 않습니다(실수로 덮어쓰지 않도록).
- 편집기 날짜는 오늘이 기본이고, 새 기록이든 고치기든 언제든 바꿀 수 있습니다.
- 3D 링은 CSS 3D transform만으로 만듭니다(라이브러리 없음). 모양을 조정하는 값은 `static/js/diary.js` 맨 위 상수(`MIN_SLOTS`, `FACE_ANGLE`, `SPACING`, `FRONT_Y`, `TILT`)에 모아 두었습니다. `TILT`는 JS가 CSS 변수 `--tilt`로 넘기므로 JS 쪽만 고치면 됩니다.
- 링은 연도별로 나눠 그립니다(1년 최대 366장). 카드에는 요약문(`md.excerpt`)만 보내고, 본문은 카드를 열 때 따로 받아옵니다.

## 사진·일기 연결 규칙 (지도 ↔ 일기 ↔ 여행기)
- 사진과 일기는 **날짜(base_dt) + 사용자**로만 잇습니다. 연결용 컬럼이나 테이블은 없습니다.
- 지도: `/api/photo-dates`에 기간을 주면 그 기간의 일기 요약(`diaries`: 날짜·제목·`md.excerpt`)도 함께 옵니다. 날짜 목록에 📖를 붙이고, 날짜를 고르면 패널에 그날 일기 요약이 나옵니다(펼치기는 `/api/diary/<dt>`로 본문을 받아 창으로). 날짜 목록은 여전히 **사진이 있는 날만** 보여 주므로, 사진 없는 날의 일기는 여행기에서 봅니다.
- 일기 쓰기 연결: `/diary/?date=YYYYMMDD&write=1` → 그날 기록이 있으면 고치기, 없으면 그 날짜의 새 기록으로 편집기가 열립니다(`?open=1`은 읽기).
- 일기 읽기 창: `/api/diary/<dt>`의 `photos`는 지도와 같은 사진 JSON(`_photo_json`)입니다. 그날 사진이 있으면 창을 넓혀 오른쪽(모바일은 아래)에 동선 지도와 사진 줄을 보여 줍니다.
- 여행기 `/story?start=&end=&status=`: `story_logic.build_story`가 사진·일기·설명을 종류별 쿼리 1번씩으로 읽어 날짜별로 묶습니다. 사진이나 일기 중 하나라도 있는 날을 모두 넣고, 기간은 최대 366일(`MAX_DAYS`)입니다. 사진 설명은 `note_logic.first_notes_by_photo`(사진마다 가장 먼저 쓴 기록, `get_photo_note`와 같은 기준)를 씁니다.
  - 화면: 날짜 머리 → 일기 → 동선 지도(화면에 보일 때 그림) → 사진. 설명 있는 사진은 크게 나란히, 설명 없는 사진은 이어지는 것끼리 타일로 묶습니다(촬영순 유지).
- 공용 스크립트 `static/js/dayview.js`(`TPDay`): 동선 지도(`dayMap`, 지도 화면과 같은 `.photo-marker` 모양, 휠 확대 끔)와 사진 크게 보기(`lightbox`, ← →)를 일기와 여행기가 같이 씁니다. 지도 화면(`map.js`)은 클러스터·필름 때문에 자체 코드를 씁니다.

## 달력 · 검색 · PDF · 백업 규칙
- 달력 `/calendar?month=YYYYMM&day=&status=`: `calendar_logic.month_summary`가 한 달 사진·일기를 쿼리 1번씩 읽어 날짜별로 장수, 첫/마지막 촬영 시각, 이동 거리, 일기 여부를 계산합니다. 사진이 많을수록 칸 색이 진해집니다(1/4/10/20장 기준 4단계). 날짜 칸은 방향키로 이동합니다(Tab 정지점 하나).
- 이동 거리(`utils/geo.path_km`): 그날 **위치 있는 사진을 촬영순으로 이은 직선거리 합**입니다. 실제 이동 경로가 아니므로 실제보다 짧게 나옵니다. 여행기 날짜 머리에도 같은 값(`calendar_logic.day_stats`)을 씁니다.
- 검색 `/api/search?q=`: 일기(`daily_logic.search_daily`)와 사진 설명(`note_logic.search_notes`)의 제목·본문을 `LIKE`로 찾고, 각각 최근 것부터 최대 100건을 돌려줍니다. 검색어는 `utils/search.clean_keyword`로 정리(1~100자)하고, `like_contains`로 `\ % _`를 이스케이프한 뒤 `%s`로 바인딩합니다. 대소문자는 콜레이션이 무시합니다. 미리보기는 `md.snippet`(검색어 주변 평문)이고, 화면이 `<mark>`로 강조합니다(textContent만 사용). 일기 화면의 🔍 버튼이나 `/` 키로 엽니다. 인덱스 없이 전체를 훑으므로 기록이 아주 많아지면 FULLTEXT 인덱스를 검토합니다(DDL이라 사용자 확인 필요).
- PDF로 저장: 여행기에서 아직 안 그린 지도를 모두 그리고, 사진·타일이 다 불러와질 때까지(최대 8초) 기다린 뒤 `window.print()`를 부릅니다. 인쇄하는 동안 `body.printing`으로 본문 폭을 A4 인쇄 폭(700px)에 맞춥니다. 인쇄 CSS는 `story.css`의 `@media print`에 있습니다.
- 백업 내보내기 `GET /backup/download?start=&end=&status=&exif=0|1`(`routes/backup.py`, `logics/export_logic.py`):
  - zip 구성: `photos/날짜/촬영시각_번호.jpg`, `diary/날짜.md`, `notes/촬영시각_번호[_n].md`, `photos.csv`(UTF-8 BOM), `README.txt`. 기간은 최대 366일입니다.
  - 복호화한 사진은 **디스크에 쓰지 않고** zip을 만들면서 바로 응답으로 흘려보냅니다(`stream_with_context`, seek 불가 버퍼 `_Pipe`). 응답에는 `Cache-Control: private, no-store`를 붙입니다.
  - 검증과 조회는 응답을 시작하기 전에 끝내서(`prepare`), 잘못된 조건이면 zip 대신 400을 돌려줍니다. 파일이 없거나 복호화에 실패한 사진은 건너뛰고 README와 CSV에 기록합니다.
  - `exif=1`(기본)이면 `utils/exif.with_exif`가 JPEG를 다시 인코딩하지 않고 APP1에 촬영 시각·GPS를 넣습니다(백업을 다른 앱이나 TracePic에 다시 올리면 시각·위치가 복원됨). **저장소의 암호화 파일에는 계속 EXIF를 넣지 않습니다.**
  - 사진마다 다시 조회하지 않도록, 이미 user_id 조건으로 읽은 행으로 복호화합니다(`photo_file_logic.read_row_image`). 이 함수에는 본인 행만 넘깁니다.

## 진행 현황
- [x] 1회차: 프로젝트 골격 (config, factory, main 라우트, requirements), MySQL 연결 확인, MASTER_SALT 설정·백업 완료 (2026-11-13)
- [x] `sql/schema.sql`: 테이블 3개 DDL 정리
- [x] DB 계층: `db.py`(PyMySQL 헬퍼), `logics/` 도입, ORM 제거
- [x] 2회차: 로그인 (전역 가드, user_devices 토큰, 실패 횟수 제한)
- [x] logics: photo / note / daily CRUD (2026-11-17, 개발 DB 롤백 테스트 32항목 통과)
- [x] utils: exif / image / crypto / csrf (2026-11-17)
- [x] 사진 업로드 페이지·복호화 라우트 (2026-11-17, 통합 테스트 20항목 통과)
- [ ] HEIC: `pillow-heif` 설치 필요 (requirements에는 추가함. 설치하지 않으면 HEIC 업로드만 거부됨)
- [x] 지도 화면(메인 `/`) + 지도 API (2026-11-17)
- [x] 지도 상태 조건, 촬영 순서 번호·필름, 사진 크게 보기에서 상태 변경·마크다운 설명 (2026-11-17, 통합 테스트 32항목 통과)
- [x] 필름 방향키 이동, 크게 보기에서 위치 찍기·수정·지우기 (2026-11-18)
- [x] 사진·일기 연결: 지도 날짜별 일기(📖·요약·펼치기·쓰기), 일기 읽기 창의 동선 지도, 여행기 `/story` (2026-11-18, 테스트 26항목 통과)
- [x] 달력(사진 수·일기·첫/마지막 시각·이동 거리), 일기·사진 설명 검색, 여행기 PDF 저장, 백업 zip 내보내기 (2026-11-18, 테스트 53항목 통과)
- [x] 일기 화면 `/diary` (일별 마크다운 기록, 3D 카드 링) (2026-11-17)
- [x] user_info 비밀번호 bcrypt 일괄 변환 (2026-11-20, 5명)
- [x] 메일 가입 신청(인증 코드) · 관리자 승인 화면 · 비밀번호 찾기 (2026-11-20, 테스트 62항목 통과)
- [x] 동영상 업로드 → 3~7초 움직이는 WebP 클립 3종 (2026-11-20, 실제 ffmpeg 포함 테스트 49항목 통과, 사용자 실제 영상 확인 — 위치·촬영 시각 추출 정상)
- [x] 앱 API: 앱 로그인(device_token 발급)·업로드·로그아웃 (2026-11-20, 테스트 28항목 통과)
- [ ] 배포 (Nginx, systemd, gunicorn) — **HTTPS는 보류 (2026-11-13 사용자 결정, 기능 개발 우선)**. 배포할 때 Nginx + Let's Encrypt + ProxyFix로 진행할 예정

## Git 커밋 규칙
- **커밋할 때마다 `README.md`의 "작업 이력" 섹션에 회차별(N회차) 작업 내용을 추가하고, 같은 커밋에 포함합니다.** 새 회차는 목록 맨 아래에 붙입니다.
- 커밋에 앞서 이 파일의 "진행 현황"과 "미결정 사항"도 함께 갱신합니다.
- `.env`는 절대 커밋하지 않습니다(`.gitignore`로 막혀 있음). 저장소와 로그는 프로젝트 밖에 있습니다.
- 커밋 메시지는 한국어로 요약을 쓰고, 회차 번호를 붙입니다. 예: `[2회차] 사진 업로드 로직 추가`
