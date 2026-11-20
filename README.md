# TracePic

> 사진의 EXIF(GPS·촬영시간)를 지도에 매핑하고, 마크다운 여행 기록과 **암호화된 이미지**를 보관하는 개인용 셀프 호스팅 여행 아카이빙 플랫폼

- 배포 환경: Oracle Cloud (Linux) + Nginx + gunicorn
- 저장 방식: 이미지는 서버 로컬에 암호화 저장, 메타데이터는 MySQL

---

## 기술 스택

| 구분 | 사용 기술 |
|---|---|
| Backend | Python 3.x, Flask 3.1 (Application Factory 패턴) |
| Database | MySQL (utf8mb4), PyMySQL — **ORM 미사용, SQL 직접 작성** |
| Frontend | HTML / CSS / JS, Leaflet.js |
| 이미지 | Pillow (리사이징, EXIF 유지·재주입) |
| 보안 | cryptography (HKDF 키 유도 + Fernet 암호화) |
| 마크다운 | Markdown + nh3 (XSS 살균) |
| 운영 | gunicorn, python-dotenv |

## 핵심 기능

0. **로그인**: 모든 페이지는 로그인이 필요합니다. 브라우저 세션의 기기 토큰을 `user_devices`에서 확인하고, 로그인 후에는 원래 가려던 페이지로 이동합니다.
1. **이미지 업로드·처리**: 업로드한 사진을 웹용 해상도로 리사이징하고, 원본 EXIF(GPS·촬영시간)는 그대로 남깁니다.
2. **이미지 암호화**: `User ID + 파일명 타임스탬프 + 서버 Master Salt`로 파일마다 키를 따로 만들어 암호화한 뒤 저장합니다.
3. **위치 매핑**: 추출한 위도·경도를 Leaflet 지도에 Pin으로 표시합니다.
4. **여행 기록**: 사진마다 마크다운 형식의 기록을 연결합니다.

---

## 디렉토리 구조

```
~/                          # 프로젝트 상위 폴더
├── tracepic_storage/       # [외부] 암호화 이미지 저장소 (권한 0700) — STORAGE_DIR
├── tracepic_logs/          # [외부] 운영 회전 로그 — LOG_DIR
└── tracepic/               # ── 프로젝트 루트 ──
├── app.py                  # 실행 진입점 (gunicorn app:app)
├── config.py               # .env 로딩 + 환경별 설정 클래스
├── requirements.txt        # 의존 라이브러리
├── .env.example            # 환경 변수 견본 (.env 는 커밋 금지)
├── .gitignore
├── README.md               # 프로젝트 소개 + 작업 이력
├── CLAUDE.md               # 개발 규칙·핵심 결정사항 (AI 협업용)
├── sql/
│   └── schema.sql          # tracepic_photos / notes / daily DDL
└── tracepic/               # 애플리케이션 패키지
    ├── __init__.py         # create_app() 팩토리
    ├── db.py               # PyMySQL 커넥션·쿼리 헬퍼
    ├── routes/             # 블루프린트 — 요청/응답만
    │   ├── auth.py         #   로그인·로그아웃 + 전역 로그인 가드
    │   ├── main.py         #   메인(지도), 여행기(/story), 달력(/calendar), /health
    │   ├── photo.py        #   사진 업로드 화면·처리, 복호화 이미지·썸네일
    │   ├── diary.py        #   일기 화면 (/diary)
    │   ├── backup.py       #   백업 zip 내려받기 (/backup/download)
    │   └── api.py          #   JSON API (지도: /api/photo-dates, /api/map-photos · 사진: /api/photos/<id>[/note] · 일기: /api/diary · 여행기: /api/story · 달력: /api/calendar · 검색: /api/search)
    ├── logics/             # 비즈니스 로직 + SQL (*_logic.py)
    │   ├── auth_logic.py   #   계정 확인, 기기 토큰 발급·검증·폐기
    │   ├── photo_logic.py  #   사진 메타데이터 CRUD, 공개 범위·휴지통
    │   ├── photo_file_logic.py # 업로드(EXIF→리사이즈→암호화 저장→DB 등록), 복호화 읽기
    │   ├── note_logic.py   #   사진별 마크다운 기록 CRUD
    │   ├── daily_logic.py  #   일별 요약 기록 CRUD (하루 1건)
    │   ├── story_logic.py  #   여행기: 기간의 일기·사진·사진 설명을 날짜별로 묶기
    │   ├── calendar_logic.py # 달력: 날짜별 사진 수·첫/마지막 시각·이동 거리·일기
    │   ├── export_logic.py #   백업 zip 만들기 (스트리밍, EXIF 복원)
    │   └── system_logic.py #   DB 상태 확인
    ├── utils/              # DB와 무관한 기능
    │   ├── crypto.py       #   HKDF + Fernet 파일 암·복호화
    │   ├── csrf.py         #   CSRF 토큰 (모든 POST 검사)
    │   ├── dates.py        #   base_dt(YYYYMMDD) 변환·검증
    │   ├── exif.py         #   EXIF 촬영 시각·GPS 추출, 백업용 EXIF 다시 넣기
    │   ├── geo.py          #   GPS 거리 계산 (하버사인)
    │   ├── search.py       #   검색어 정리, LIKE 이스케이프
    │   ├── image.py        #   이미지 열기·포맷 확인, 웹용 JPEG·썸네일 변환
    │   ├── md.py           #   마크다운 → nh3 살균 HTML, 카드용 요약문
    │   ├── password.py     #   비밀번호 검증 (bcrypt / werkzeug / 평문)
    │   └── login_throttle.py # 로그인 실패 횟수 제한
    ├── templates/          # base.html, login.html, map.html(메인 지도), upload.html, diary.html, story.html(여행기), calendar.html(달력)
    └── static/             # css/app.css·diary.css·story.css·calendar.css, js/map.js(지도)·calendar.js(달력)·upload.js(업로드)·diary.js(일기 3D 링)·story.js(여행기)·dayview.js(공용 동선 지도·사진 크게 보기)
```

### 루트 파일

| 경로 | 역할 |
|---|---|
| `app.py` | **실행 진입점**입니다. `create_app()`으로 만든 앱을 `app` 변수에 담습니다. 개발 중에는 `python app.py`로, 운영 서버에서는 `gunicorn app:app`으로 실행합니다. |
| `config.py` | **설정 모듈**입니다. `.env`를 읽어 DB URI(utf8mb4, 커넥션 자동 재연결), Master Salt, 저장 경로, 업로드 제한, 리사이징 설정을 정합니다. 개발용 `DevelopmentConfig`와 운영용 `ProductionConfig`로 나뉩니다. |
| `requirements.txt` | 의존 라이브러리 목록입니다. `pip install -r requirements.txt` 한 번으로 같은 환경을 다시 만들 수 있습니다. |
| `.env.example` | 환경 변수 견본입니다. `.env`로 복사한 뒤 실제 값을 넣습니다. |
| `.gitignore` | `.env`, `.venv/`, 캐시, `*.log`가 Git에 올라가지 않게 막습니다. 저장소와 로그는 처음부터 프로젝트 밖에 있어서 커밋될 일이 없습니다. |

### 데이터·운영 폴더

| 경로 | 역할 |
|---|---|
| `../tracepic_storage/` | **[프로젝트 외부]** 암호화된 이미지 저장소입니다(`STORAGE_DIR`). 앱이 시작할 때 권한을 0700으로 맞추고, URL로 직접 접근할 수 없습니다. `{user_id}/{base_dt}/{timestamp}.enc` 형태로 저장할 예정입니다. 프로젝트 밖에 있어서 재배포하거나 프로젝트를 지워도 데이터가 남습니다. |
| `../tracepic_logs/` | **[프로젝트 외부]** 운영 로그(`tracepic.log`)가 저장됩니다(`LOG_DIR`). 5MB가 넘으면 새 파일로 넘어가고 최대 5개까지 보관합니다. |
| `sql/schema.sql` | 기존 테이블 3개(`tracepic_photos`, `tracepic_notes`, `tracepic_daily`)의 DDL입니다. 개발 DB의 `SHOW CREATE TABLE` 결과를 그대로 옮겼고, `IF NOT EXISTS`가 붙어 있어 여러 번 실행해도 안전합니다. |

### 애플리케이션 패키지 `tracepic/`

| 경로 | 역할 |
|---|---|
| `__init__.py` | **Application Factory**입니다. 설정 로딩 → 비밀값 검증(운영 환경에서 실패하면 기동 중단) → DB 연결 → storage 준비 → 블루프린트 등록 → 에러 핸들러 → 로깅 순서로 앱을 조립합니다. |
| `db.py` | **DB 헬퍼**입니다. 요청마다 PyMySQL 커넥션을 하나 열고 요청이 끝나면 닫습니다(커밋하지 않은 작업은 롤백). `fetch_one`, `fetch_all`, `execute`, `transaction()`을 제공하고 결과는 dict로 돌려줍니다. |
| `routes/` | URL 처리(컨트롤러) 계층입니다. 요청을 해석하고 응답을 돌려주는 일만 하고, 실제 처리는 `logics`에 맡깁니다. 현재 `auth.py`(로그인), `main.py`(`/`, `/story`, `/calendar`, `/health`), `backup.py`(`/backup/download`), `photo.py`(`/photos/upload`, `/photos/<id>/image`, `/photos/<id>/thumb`), `api.py`(`/api/photo-dates`, `/api/map-photos`, `/api/photos/<id>`, `/api/photos/<id>/note`, `/api/markdown/preview`, `/api/diary`, `/api/story`, `/api/calendar`, `/api/search`)가 있습니다. |
| `logics/` | **비즈니스 로직 계층**입니다. 기능별로 `*_logic.py` 파일을 만들고, SQL도 여기서 직접 씁니다. 값은 항상 `%s` 파라미터 바인딩으로 넘깁니다. 현재 `auth_logic.py`(로그인), `photo_logic.py`(사진), `note_logic.py`(사진별 기록), `daily_logic.py`(일별 요약), `system_logic.py`(DB 연결 확인)가 있습니다. |
| `utils/` | DB와 상관없는 순수 기능(EXIF 추출, 이미지 리사이징, 암·복호화)을 둡니다. |
| `templates/`, `static/` | 화면 템플릿과 CSS·JS(Leaflet)를 둡니다. |

### 로그인 흐름

```
요청 ─▶ [전역 가드] 세션에 user_id + device_token 있음?
          ├─ 없음 ─────────────────────────────▶ /login?next=원래경로
          └─ 있음 ─▶ user_devices 확인 (토큰·아이디 일치, 만료 전, user_info에 계정 있음)
                      ├─ 실패 → 세션 삭제 ─────▶ /login?next=원래경로
                      └─ 성공 → 원래 페이지

/login (POST) ─▶ user_info 비밀번호 확인 ─▶ 새 토큰(64 hex) 발급 → user_devices INSERT (180일)
              ─▶ 세션에 user_id + device_token 저장 ─▶ next로 이동
/logout (POST) ─▶ 이 브라우저의 토큰 행 DELETE ─▶ /login
```

- 로그인 없이 접근할 수 있는 곳은 `/login`, `/health`, `/static`뿐입니다.
- `/api/*`에 로그인 없이 접근하면 리다이렉트 대신 401 JSON을 돌려줍니다.
- 같은 아이디로 5회 실패하면 10분 동안 잠깁니다(IP 기준은 15회).
- DB에서 토큰 행을 지우면 그 기기는 바로 로그아웃됩니다.

### 요청 처리 흐름

```
app.py → create_app() → config.py(.env) 로딩
                     → db.py 커넥션 정리 훅 등록
                     → routes/* 블루프린트 등록
요청 → routes → logics (SQL) → db.py (PyMySQL) → MySQL
                  ↘ utils (EXIF/이미지/암호화)
                                            ↘ ../tracepic_storage/ (암호화 파일)
응답 ← templates + static (Leaflet 지도)
```

---

## 시작하기

```bash
# 1) 가상환경 및 라이브러리 설치
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2) 환경 변수 설정
cp .env.example .env
# SECRET_KEY / DB_* / MASTER_SALT 값 수정
python -c "import secrets; print(secrets.token_urlsafe(48))"   # MASTER_SALT 생성

# 3) 실행
.venv/bin/python app.py                                 # 개발 (http://127.0.0.1:5000)
.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 app:app       # 운영 (Nginx 리버스 프록시 뒤)

# 4) 상태 확인
curl http://127.0.0.1:5555/health    # {"status":"ok","db":"ok"}
```

> ⚠️ `MASTER_SALT`를 잃어버리면 저장된 이미지를 **모두 복호화할 수 없습니다**. 반드시 서버 밖에 따로 백업하세요.

---

## 작업 이력

> 커밋할 때마다 회차별로 작업 내용을 여기에 남깁니다. 새 회차는 목록 맨 아래에 추가합니다.

### 1회차 — 프로젝트 초기 골격 구성
- 디렉토리 구조 설계: routes / logics / utils / templates / static 분리
- `requirements.txt` 작성: Flask, PyMySQL, bcrypt, Pillow, cryptography, Markdown, nh3, gunicorn
- `config.py`: `.env` 기반 설정, 개발·운영 설정 분리, MySQL 접속 정보(`DATABASE_URL` → PyMySQL 접속 정보 dict)
- `tracepic/__init__.py`: Application Factory, 운영 환경 비밀값 검증, storage 폴더(0700) 생성, 에러 핸들러, 회전 로그
- `routes/main.py`: `/`, `/health`(DB 연결 확인)
- 저장소·로그 폴더를 프로젝트 외부(`../tracepic_storage`, `../tracepic_logs`)로 분리하고 `STORAGE_DIR`, `LOG_DIR` 환경 변수로 지정할 수 있게 함
- `sql/schema.sql`: 기존 테이블 3개 DDL 정리
- ORM(SQLAlchemy)을 쓰지 않기로 결정: `tracepic/db.py`(PyMySQL 헬퍼)와 `tracepic/logics/`(로직 + SQL) 계층 도입, `models/`와 `extensions.py` 삭제
- DB 접속: `DATABASE_URL` 우선 지원, 원격 MySQL 8.0 연결 및 기존 `tracepic_*` 테이블 확인
- `.env.example`, `.gitignore`, `README.md`, `CLAUDE.md` 작성

### 2회차 — 로그인 처리
- 전역 로그인 가드: 세션의 `user_id`와 `device_token`을 `user_devices`에서 검증하고(만료일, `user_info` 조인 포함), 실패하면 `/login?next=`로 보냄
- 로그인: `user_info`로 계정 확인 → 기기 토큰 발급(64 hex, 180일) → 세션 저장 → 원래 페이지로 이동
- 비밀번호 검증: bcrypt, werkzeug 해시, 평문(레거시) 모두 지원. 공유 테이블이라 저장 형식은 바꾸지 않음
- 보안: 로그인 실패 횟수 제한, 오픈 리다이렉트 차단, 세션 고정 공격 방지, 아이디 존재 여부를 알 수 없는 오류 메시지
- 로그아웃: 이 브라우저의 토큰만 삭제
- 화면: `base.html`, `login.html`, `index.html`, `app.css`(라이트/다크 모드)

### 3회차 — photo / note / daily CRUD 로직
- `photo_logic.py`: 사진 메타데이터 생성, 단건·일별·기간별(지도용 좌표 필터) 조회, 날짜별 장수, 좌표·촬영시각·공개 범위 수정, 휴지통(D)·복구·완전삭제(Z)
- `note_logic.py`: 사진별 기록 CRUD. `tracepic_notes`에 user_id가 없어서 `tracepic_photos`와 JOIN해 소유자를 확인하고, 삭제는 `use_yn='N'`으로 표시
- `daily_logic.py`: 일별 요약 조회·기간 목록, `save_daily()`로 하루 1건 유지(있으면 수정, 없으면 추가), 삭제는 `use_yn='N'`으로 표시
- `utils/dates.py`: base_dt(YYYYMMDD) 변환·검증
- 공통 규칙: 모든 조회·수정에 소유자 조건, 행 DELETE 없이 상태값으로 삭제, `updated_at = NOW()` 직접 갱신, SQL은 리터럴 + `%s` 바인딩
- 개발 서버 포트를 5000에서 5555로 변경(5000은 다른 개발 서비스가 사용 중), 운영 gunicorn 포트도 5555로 통일
- 개발 DB에서 커밋을 막고 롤백하는 방식으로 통합 테스트 32항목 통과(테스트 데이터 잔존 0건 확인)

### 4회차 — 사진 업로드 페이지
- 업로드 화면 `/photos/upload`: 여러 장 선택·끌어다 놓기, 파일별 진행률·결과(촬영 시각 출처, 위치 유무, 썸네일), 공개 범위 선택(기본 '나만 보기')
- 업로드 처리: 이미지 포맷 확인 → EXIF 촬영 시각·GPS 추출(없으면 파일 수정 시각 → 업로드 시각) → 웹용 JPEG(긴 변 2048) + 썸네일(400) → 파일별 키로 암호화 저장 → DB 등록, DB 실패 시 파일 정리
- 복호화 응답 `/photos/<id>/image`, `/photos/<id>/thumb`: 본인 사진만, `Cache-Control: private`
- utils: `crypto.py`(HKDF + Fernet), `exif.py`, `image.py`(EXIF 회전 반영, 투명 배경 합성, EXIF·GPS 제거)
- CSRF 도입: `utils/csrf.py`가 모든 POST를 검사하고, 로그인·로그아웃 폼과 업로드 XHR에 토큰을 추가함
- HEIC: `pillow-heif`를 requirements에 추가함(설치되어 있으면 자동으로 지원)
- 통합 테스트 20항목 통과(임시 저장소 + DB 롤백), 3회차 로직 테스트 재통과

### 5회차 — 지도 화면
- 메인 페이지 `/`를 사진 지도로 바꿈(`index.html` 삭제 → `map.html`)
- Leaflet 1.9.4 + markercluster 1.5.3(unpkg, 버전 고정 + SRI), OpenStreetMap 타일
- 썸네일 마커, 가까운 사진 묶음 표시, 촬영 시각순 이동 경로(켜고 끄기), 마커 팝업 → 크게 보기(dialog)
- 기간 선택(시작일~종료일, 전체), 날짜 목록(날짜별 장수, 누르면 그날만 표시), 위치 없는 사진 수 표시, 선택한 기간을 주소(`?start=&end=`)에 유지
- API: `/api/photo-dates`, `/api/map-photos` (`photo_logic.list_map_photos` 추가)
- 모바일: 패널을 위쪽에 두고 날짜 목록을 가로 스크롤로 표시
- 테스트 12항목 통과, 3·4회차 테스트 재통과

### 6회차 — 일기 화면 (3D 카드 링)
- `/diary`: 어두운 무대 위에 흰 종이 카드가 원형으로 늘어선 3D 링(CSS 3D transform, 외부 라이브러리 없음). 기록이 적으면 빈 종이로 링을 채움
- 조작: 드래그(관성), 휠, ← → / PageUp·PageDown / Home·End, 슬라이더, 가운데 카드 클릭이나 Enter로 열기, N으로 새 기록
- 앞에 선 카드는 정면으로 돌아 앞으로 나오고, 양옆 카드가 벌어짐. 연도별로 링을 나눠 표시
- 읽기: 마크다운 렌더링(서버에서 nh3로 살균) + 그날 사진 썸네일. 쓰기: 쓰기/미리보기 탭, Ctrl+S 저장, 저장하지 않고 닫을 때 확인
- 하루 1건(`tracepic_daily`): 새 기록의 날짜에 이미 기록이 있으면 불러와서 수정하게 함. 고칠 때는 날짜를 잠금
- 딥링크 `?date=YYYYMMDD`(그날 카드로 이동), `&open=1`(바로 읽기)
- `utils/md.py`: 외부 이미지 차단(`/photos/...`만 허용), 체크박스 목록, 요약문 생성
- 본문 최대 65,535바이트(TEXT) 검사 추가, 모바일 상단 바가 넘치지 않게 수정
- 일기 API 테스트 20항목 통과, 이전 회차 테스트 재통과. 데스크톱·모바일(390px) 화면을 헤드리스 Chrome으로 확인

### 7회차 — 일기 날짜 변경
- 편집기 날짜는 오늘이 기본이고, 새 기록·고치기 모두 날짜를 바꿀 수 있음(고치기에서 바꾸면 기록이 그 날짜로 옮겨짐)
- 날짜를 바꾸면 그날 기록이 있는지 바로 확인해 안내함: 새 기록이면 [그 기록 불러오기], 고치기면 "옮겨집니다" 또는 "옮길 수 없습니다"
- 덮어쓰기 방지: `PUT /api/diary`에 `mode`(create/update)를 추가하고, 대상 날짜에 기록이 있으면 409를 돌려줌
- `daily_logic.create_daily`, `update_daily`(날짜 이동 포함, 두 날짜를 `FOR UPDATE`로 잠근 뒤 처리), `DailyConflictError` 추가
- 일기 API 테스트 28항목 통과

### 8회차 — 일기 링 시점·간격 조정
- 링을 더 수평에서 바라보도록 조정: 기울기 14° → 6°, 시점 높이(perspective-origin) 20% → 42%
- 카드 간격 20% 확대(`SPACING` 0.30 → 0.36)
- 기울기 값을 JS 상수 `TILT` 하나로 관리(CSS 변수 `--tilt`로 전달)

### 9회차 — 이미지 암호화 키 단순화
- 키 유도를 `HKDF(MASTER_SALT, info = user_id + 파일 타임스탬프)`에서 `HKDF(MASTER_SALT, info = user_id)`로 변경(사용자별 키 1개)
- 파일 이름의 `time_ns`는 이름 충돌 방지용으로만 남김
- 촬영 시간·GPS는 저장 파일에 다시 넣지 않고 DB에만 기록하기로 확정
- 변경 시점에 저장된 사진이 0건이어서 기존 파일 재암호화는 필요 없었음

### 10회차 — 지도 상태 조건 · 촬영 순서 · 사진 설명(MD) · 상태 변경
- 지도 조회 조건에 사진 상태 추가(나만 보기 / 부분 공유 / 전체 공유 / 휴지통, 기본은 휴지통 제외). 날짜 목록 장수도 조건을 따르고, 주소(`?status=`)에 남음
- 촬영 시각순 번호: 마커 왼쪽 위 배지 + 지도 아래 '촬영 순서 필름'(날짜 구분, 위치 없는 사진도 포함). 마커·필름 테두리 색으로 상태 표시
- 사진 크게 보기 개편: 이전/다음(촬영순, ← → 키), 위치, 상태 변경(휴지통 이동·복구 포함), 마크다운 설명 쓰기·고치기·삭제(미리보기, Ctrl+S, 저장 안 한 내용 경고)
- 설명은 `tracepic_notes`에 사진당 1건으로 저장(`note_logic.get_photo_note` / `save_photo_note`)
- 상태 변경은 `photo_logic.change_status`(A/B/C/D 사이 이동, Z는 불가)
- API 추가: `GET/PATCH /api/photos/<id>`, `PUT/DELETE /api/photos/<id>/note`, `POST /api/markdown/preview`. `/api/map-photos`는 위치 없는 사진도 돌려줌(lat/lng = null)
- 패널 높이가 바뀌어도 지도 크기를 다시 계산하도록 수정(모바일에서 지도가 어긋나던 문제)
- 통합 테스트 32항목 통과, 이전 테스트(로직·업로드·지도·일기) 재통과. 데스크톱·모바일 화면 확인

### 11회차 — 설명 있는 사진 표시
- 설명(note)이 있는 사진은 마커·필름에 보라색 바깥 테두리를 한 겹 더 둘러 구분(안쪽 테두리는 상태 색 그대로). 패널에 범례 추가
- `/api/map-photos`, `/api/photos/<id>`에 `has_note` 추가. `note_logic.photo_ids_with_notes`로 조회한 사진 전체를 쿼리 1번에 확인
- 크게 보기에서 설명을 저장·삭제하거나 휴지통으로 옮기면 테두리가 바로 바뀜
- 통합 테스트에 has_note 5항목 추가, 전체 통과

### 12회차 — 지도 조회 기간 기본값 · 일자별 날짜 목록
- 조회 기간 기본값을 이번 달 1일 ~ 오늘로 변경(이전: 사진이 있는 전체 기간)
- 날짜 목록을 조회 기간 안의 일자별 목록으로 변경(맨 위 '기간 전체' + 날짜 오름차순). 날짜를 누르면 기간은 유지한 채 그날만 표시
- `/api/photo-dates`에 기간 조건(`start`, `end`) 추가, `photo_logic.list_photo_dates`에 기간 인자 추가(SQL은 항상 BETWEEN — 조건별 조립 없음)
- '전체' 버튼은 사진이 있는 첫날~마지막 날로 기간을 넓혀 조회. 주소에 고른 날(`day`)도 남김
- 기간 안에 사진이 없으면 안내 문구 표시. 쓰지 않게 된 '첫 사진 올리기' 안내 블록 제거
- 테스트: 날짜 목록 기간 조건 4항목 추가, 전체 통과

### 13회차 — 크게 보기 사진 잘림 수정
- 세로 사진이나 화면보다 큰 사진이 크게 보기에서 아래가 잘리던 문제 수정: 그리드 행을 `minmax(0, 1fr)`로 고정하고, 사진은 사진 칸 안에 비율을 유지해 맞춤(`object-fit: contain`)
- 세로·파노라마 사진의 지도 마커가 늘어나 보이던 문제 수정(Leaflet 기본 CSS보다 우선하는 크기 규칙 추가, 48px 정사각형 유지)
- 세로(800×1600)·가로(2400×600) 사진으로 데스크톱·모바일 화면 확인

### 14회차 — 성능 개선 (커넥션 풀 · 이미지 캐시 · 로그인 캐시 · 인덱스 · 디코딩 · 마커용 썸네일)
- DB 커넥션 풀(`db.py`): 요청마다 원격 MySQL에 새로 접속하지 않고 재사용. 조회 1회 약 77ms → 16ms(개발 DB 측정)
- 이미지 응답에 ETag + `private, max-age=1년, immutable`. `If-None-Match`가 맞으면 소유 확인만 하고 304(복호화 없음)
- 로그인 확인 결과를 워커 메모리에 60초 캐시(`AUTH_CACHE_SECONDS`). 실패는 캐시하지 않고, 로그아웃하면 즉시 삭제
- 인덱스 `tracepic_photos_inx02 (user_id, base_dt)` 추가(온라인 DDL). notes의 pic_id 인덱스는 외래키로 이미 있어 `schema.sql`에 반영
- JPEG 업로드는 draft로 필요한 크기만큼만 디코딩. 2400만 화소 사진 처리 약 2.5초 → 0.47초
- 마커용 128px 정사각형 썸네일(`.mini.enc`, `/photos/<id>/mini`) 추가. 지도 마커와 필름이 사용. 예전 사진은 처음 요청할 때 생성
- 설정 추가: `DB_POOL_SIZE`, `DB_POOL_RECYCLE`, `DB_POOL_PING_IDLE`, `AUTH_CACHE_SECONDS` (`.env.example` 반영)
- 성능 테스트 22항목 추가, 기존 테스트 전체 재통과(업로드 테스트는 파일 3종 기준으로 수정)

### 15회차 — 필름 방향키 이동 · 크게 보기에서 위치 찍기/수정
- 촬영 순서 필름: Tab 정지점을 하나(선택된 사진)로 줄이고, 필름 안에서는 ← → (Home/End)로 이동. Enter는 크게 보기
  - 방향키로 옮기면 위치 있는 사진은 지도가 그 마커로 이동(팝업), 위치 없는 사진은 강조만 하고 크게 보기는 열지 않음
  - 마커를 누르거나 크게 보기를 닫은 뒤에도 바로 ← →로 이어서 넘길 수 있음(포커스를 필름으로 돌려 줌)
- 크게 보기: '위치 찍기/수정' → 작은 지도에서 누르거나 핀을 끌어 위치 지정 후 저장, '위치 지우기'. 휴지통 사진은 불가
  - 위치 없는 사진은 촬영 순서상 가장 가까운 위치 있는 사진 근처에서 지도가 열림
  - 저장하면 다시 조회하지 않고 마커·이동 경로·필름·요약을 바로 갱신
- API: `PATCH /api/photos/<id>`가 `{"latitude", "longitude"}`(둘 다 null이면 지우기)도 받음. 상태와 위치는 따로 보내야 함. NaN·bool·문자열은 400
- 지도 테스트에 위치 변경 16항목 추가

### 16회차 — 사진·일기 연결 (지도의 일기 · 일기의 동선 지도 · 여행기)
- 지도: 날짜 목록에 일기가 있는 날 📖 표시. 날짜를 고르면 패널에 그날 일기 제목·요약, '일기 펼치기'(지도 화면 안에서 전체 읽기), '이날 일기 쓰기/고치기'
  - `/api/photo-dates`에 기간을 주면 그 기간의 일기 요약(`diaries`)도 함께 돌려줌
- 일기: `/diary/?date=YYYYMMDD&write=1`로 그날 기록을 바로 쓰기(없으면)·고치기(있으면)
- 일기 읽기 창: 그날 사진이 있으면 오른쪽(모바일은 아래)에 '이날의 동선' 지도(순번 마커 + 이동 경로)와 사진 줄. 사진·마커를 누르면 크게 보기(← →), '지도에서 크게 보기'로 그날 지도 조회
  - `/api/diary/<dt>`의 photos를 지도와 같은 사진 JSON으로 바꿈(좌표·상태·설명 여부·마커용 썸네일)
- 여행기 `/story?start=&end=&status=` 추가 (상단 메뉴, 지도의 '여행기' 버튼): 날짜별로 일기 → 동선 지도 → 사진(설명 있는 사진은 크게, 없는 사진은 타일)
  - `GET /api/story`, `story_logic.build_story`(종류별 쿼리 1번), `note_logic.first_notes_by_photo`. 기간 최대 366일
  - 동선 지도는 화면에 보일 때 그리고, 크게 보기는 기간 전체 사진을 촬영순으로 넘김
- 공용 스크립트 `static/js/dayview.js`(동선 지도·라이트박스) 추가
- 연결 테스트 26항목 추가(`test_story`), 기존 테스트 전체 재통과

### 17회차 — 달력 · 검색 · PDF로 저장 · 백업 내보내기
- 달력 `/calendar` (상단 메뉴): 날짜 칸에 사진 수(색 진하기 4단계), 📖 일기, 첫·마지막 촬영 시각, 이동 거리. 날짜를 누르면 자세히와 지도·여행기·일기 링크. 방향키로 날짜 이동(PageUp/Down 한 달)
  - 이동 거리 = 그날 위치 있는 사진을 촬영순으로 이은 직선거리 합(`utils/geo.py`). 여행기 날짜 머리에도 시각·거리 표시
- 검색: 일기 화면 🔍(또는 `/` 키) → 일기·사진 설명의 제목/본문 검색(`/api/search`), 검색어 강조. 일기 결과는 그날 읽기 창으로, 사진 설명 결과는 그날 여행기로
  - LIKE 특수문자(`% _ \`)는 글자 그대로 찾도록 이스케이프
- 여행기 'PDF로 저장': 모든 지도·사진을 미리 불러온 뒤 인쇄 창(→ PDF로 저장), A4 인쇄용 CSS
- 여행기 '백업 내보내기': 기간·상태의 사진(JPEG)·일기·사진 설명(.md)·photos.csv·README 를 zip 으로(`/backup/download`)
  - 복호화한 사진을 디스크에 쓰지 않고 스트리밍. 사진 파일에 촬영 시각·GPS(EXIF)를 다시 넣는 선택(기본 켬, 재인코딩 없음)
- 테스트 53항목 추가(`test_tools`), 기존 테스트 전체 재통과

### 18회차 — 비밀번호 bcrypt 변환
- `user_info.password` 평문 → bcrypt(`$2b$12$`, 60자) 일괄 변환 (2026-11-20 사용자 결정, 같은 테이블을 쓰는 다른 서비스도 bcrypt 검증 지원)
  - `scripts/hash_passwords.py` (`--dry-run`으로 건수만 확인) → `auth_logic.hash_plain_passwords`
  - 한 트랜잭션, 해시 검증 후 저장, 이미 해시인 행은 건너뜀(여러 번 실행해도 안전), 그사이 바뀐 행은 덮어쓰지 않음, 비밀번호 값은 출력하지 않음
  - 개발 DB 5명 변환 완료. 운영 DB가 따로 있으면 서버에서 같은 스크립트를 실행
- `utils/password.py`: `hash_password()`(72바이트 제한), `is_hashed()` 추가. 로그인 검증은 기존대로 bcrypt·werkzeug·평문 자동 판별

### 19회차 — 메일 가입 · 관리자 승인 · 비밀번호 찾기
- 메일 발송 `utils/mail.py`(SMTP, Brevo). 설정은 `.env`의 `SMTP_*`, `MAIL_FROM`, `PUBLIC_BASE_URL`
- 가입 신청 `/signup` → 6자리 인증 코드 메일 → `/signup/verify` → 관리자 승인 대기 → 승인 시 `user_info` INSERT(아이디 = 메일 주소, role `user`)
- 비밀번호 찾기 `/password/forgot` → 코드 메일 → `/password/reset`(가입 여부를 알 수 없게 같은 안내, 변경 알림 메일)
- 관리자 화면 `/admin`: `user_info.role = 'admin'`만 접근(그 외 404), 상단 '관리' 메뉴도 관리자에게만 표시
- 새 테이블 `tracepic_signup`, `tracepic_email_codes`(사용자 확인 후 추가, `sql/schema.sql` 갱신)
  - 코드는 HMAC 해시만 저장, 10분 유효, 5회 오류 시 무효, 메일·IP별 발송 제한
- 테스트 62항목 추가(`test_account`)

### 20회차 — 동영상 → 움직이는 WebP 클립
- 동영상(mp4·mov·m4v·3gp, 최대 500MB)을 올리면 3~7초 구간만 잘라 WebP 3종(크게 보기 720p / 썸네일 / 마커) 생성, 영상 자체는 보관하지 않음
  - ffmpeg `-ss 3 -t 4`(입력 앞)로 7초 지점까지만 디코딩, 프레임은 메모리에서 Pillow로 WebP 변환
  - ffmpeg: `FFMPEG_PATH` → PATH → `imageio-ffmpeg` 순서로 찾음
- 영상 메타데이터에서 위치(ISO 6709)·촬영 시각 추출. `creation_time`(UTC)은 브라우저 시간대로 변환
  - ffmetadata 출력에 `creation_time`이 빠지는 문제 → 입력 정보의 Metadata 블록도 함께 읽도록 수정
- 사진/클립은 WebP 여부로 구분(응답 Content-Type, 백업 zip `.webp`)
- 테스트 49항목 추가(`test_video`, 실제 ffmpeg 확인 포함), 기존 테스트 전체 재통과

### 21회차 — 브라우저 아이콘
- `static/img/favicon.svg`(초록 바탕 + 위치 핀·렌즈 + 점선 동선) 추가, `base.html`에 연결(모든 화면 적용)

### 22회차 — 마크다운 편집기 (OverType)
- 일기 본문 · 사진 설명 입력칸을 OverType 2.7.0 편집기로 교체(jsDelivr, 버전 고정 + SRI)
  - `static/js/mdedit.js`(`TPMd.attach`)가 textarea 자리에 끼우고 textarea처럼 쓰게 해 줌. 스크립트를 못 불러오면 기존 textarea 사용
  - 툴바(굵게·기울임·제목·목록·할 일·인용·링크, 한국어 설명), 목록 자동 이어쓰기. 미리보기·저장 형식은 기존 그대로(서버 렌더, 마크다운 글자)
- 사진 설명: '쓰기/고치기' 버튼과 탭 키움, 크게 보기 옆 칸 380 → 400px, 툴바 한 줄(넘치면 스크롤 대신 줄바꿈)

### 23회차 — 휴대폰 사진 선택 시 사진첩 우선
- 업로드 `accept`를 `image/*,video/*` 와일드카드로 변경 → 안드로이드가 파일 탐색기(구글 드라이브 등) 대신 휴대폰 사진첩(사진 선택 도구)을 엶. 형식 확인은 기존대로 서버가 함
