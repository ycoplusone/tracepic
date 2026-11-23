"""
백업 내보내기 — 기간·상태 조건의 사진(복호화한 JPEG)·일기·사진 설명을 zip 하나로

zip 안의 구성 (최상위 폴더 tracepic_backup_{시작}-{끝}/)
  README.txt                 구성 설명
  photos.csv                 사진 목록 (촬영 시각·좌표·상태·원본 파일명·파일 경로·설명 제목) — 엑셀에서 열리도록 UTF-8 BOM
  photos/{base_dt}/{YYYYMMDD_HHMMSS}_{pic_id}.jpg
                             웹용 JPEG (원본은 보관하지 않으므로 긴 변 IMAGE_MAX_SIDE 크기)
                             with_exif=True 면 촬영 시각·GPS 를 EXIF 로 다시 넣는다 (다른 앱·TracePic 에 다시 올릴 때 복원됨)
  diary/{base_dt}.md         일기 (# 제목 + 마크다운 본문)
  notes/{YYYYMMDD_HHMMSS}_{pic_id}.md   사진 설명 (사진 1장에 여러 건이면 모두, 작성순)

- 복호화한 사진은 디스크에 쓰지 않는다. zip 을 조금씩 만들어 바로 응답으로 흘려보낸다(stream_zip).
- 사진·일기·설명은 기간 전체를 종류별 쿼리 1번씩으로 읽는다.
"""
import csv
import io
import zipfile
from datetime import datetime

from ..utils import exif, video
from ..utils.dates import validate_base_dt
from . import daily_logic, note_logic, photo_file_logic, photo_logic, story_logic

MAX_DAYS = story_logic.MAX_DAYS   # 한 번에 내보낼 수 있는 최대 기간 (여행기와 같음)


class _Pipe(io.RawIOBase):
    """zipfile 이 쓰는 바이트를 모아 두었다가 꺼내 가는 쓰기 전용 버퍼 (seek 불가 → zipfile 이 스트리밍 형식으로 쓴다)"""

    def __init__(self):
        super().__init__()
        self._chunks: list[bytes] = []
        self._size = 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        data = bytes(b)
        self._chunks.append(data)
        self._size += len(data)
        return len(data)

    def tell(self) -> int:          # zipfile 이 현재 위치를 묻는다 (쓴 총량)
        return self._size

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


def _stamp(photo_at: datetime, pic_id: int) -> str:
    return f"{photo_at:%Y%m%d_%H%M%S}_{pic_id}"


def check_range(start_dt: str, end_dt: str) -> tuple[str, str]:
    """기간 검증 (여행기와 같은 규칙: 최대 MAX_DAYS 일) → (시작, 끝). 잘못되면 ValueError"""
    start_dt, end_dt = validate_base_dt(start_dt), validate_base_dt(end_dt)
    if start_dt > end_dt:
        raise ValueError("시작일이 종료일보다 늦습니다.")
    days = (datetime.strptime(end_dt, "%Y%m%d") - datetime.strptime(start_dt, "%Y%m%d")).days
    if days >= MAX_DAYS:
        raise ValueError(f"백업은 한 번에 {MAX_DAYS}일까지 내보낼 수 있습니다. 기간을 나눠 주세요.")
    return start_dt, end_dt


def prepare(user_id: str, start_dt: str, end_dt: str, statuses=photo_logic.VISIBLE_STATUSES) -> dict:
    """
    내보낼 대상 조회 (응답을 시작하기 전에 검증·조회를 끝내 둔다 — 잘못된 요청은 zip 대신 400 으로 응답하기 위해)
    → {"start", "end", "photos": [...], "dailies": [...], "notes": {pic_id: [기록...]}}
    """
    start_dt, end_dt = check_range(start_dt, end_dt)
    photos = photo_logic.list_photos_by_range(user_id, start_dt, end_dt, statuses=statuses)
    dailies = daily_logic.list_daily(user_id, start_dt, end_dt)
    notes: dict[int, list[dict]] = {}
    for n in note_logic.notes_for_photos(user_id, [p["pic_id"] for p in photos]):
        notes.setdefault(n["pic_id"], []).append(n)
    return {"start": start_dt, "end": end_dt, "photos": photos, "dailies": dailies, "notes": notes}


def file_name(data: dict) -> str:
    """내려받을 파일 이름"""
    return f"tracepic_backup_{data['start']}-{data['end']}.zip"


def stream_zip(data: dict, with_exif: bool = True):
    """
    zip 을 만들며 조각(bytes)을 차례로 내보내는 제너레이터 — Flask 응답 본문으로 그대로 쓴다
    - 사진 파일이 없거나 복호화에 실패한 사진은 건너뛰고 README 의 '빠진 사진'에 적는다.
    - 이 함수는 응답을 보내는 동안 실행되므로 앱 컨텍스트가 필요하다 (라우트에서 stream_with_context 로 감싼다).
    """
    root = file_name(data)[: -len(".zip")]
    pipe = _Pipe()
    missing: list[str] = []
    with zipfile.ZipFile(pipe, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # ── 사진 (이미 압축된 JPEG 이라 다시 압축하지 않고 그대로 담는다) ──
        rows = []
        for p in data["photos"]:
            stamp = _stamp(p["photo_at"], p["pic_id"])
            jpeg = photo_file_logic.read_row_image(p)
            clip = jpeg is not None and video.is_webp(jpeg)       # WebP(동영상 클립·WebP 로 올린 사진)는 .webp, EXIF 없음
            path = f"photos/{p['base_dt']}/{stamp}.{'webp' if clip else 'jpg'}"
            if jpeg is None:
                missing.append(f"{p['pic_id']} ({p['photo_at']:%Y-%m-%d %H:%M}, {p['original_file_name'] or '-'})")
                path = ""
            else:
                if with_exif and not clip:
                    lat, lng = (p["latitude"], p["longitude"]) if photo_logic.has_location(p) else (None, None)
                    jpeg = exif.with_exif(jpeg, p["photo_at"], lat, lng)
                zf.writestr(_info(f"{root}/{path}", p["photo_at"]), jpeg, compress_type=zipfile.ZIP_STORED)
                yield pipe.drain()
            rows.append((p, path))

        # ── 사진 설명 ──
        for p in data["photos"]:
            for i, n in enumerate(data["notes"].get(p["pic_id"], []), start=1):
                suffix = "" if i == 1 else f"_{i}"
                body = (f"# {n['title']}\n\n" if n["title"] else "") + n["note"] + "\n"
                zf.writestr(_info(f"{root}/notes/{_stamp(p['photo_at'], p['pic_id'])}{suffix}.md", n["updated_at"]),
                            body.encode("utf-8"))
        # ── 일기 ──
        for d in data["dailies"]:
            body = (f"# {d['title']}\n\n" if d["title"] else "") + d["note"] + "\n"
            zf.writestr(_info(f"{root}/diary/{d['base_dt']}.md", d["updated_at"]), body.encode("utf-8"))
        yield pipe.drain()

        # ── 목록·설명 ──
        zf.writestr(_info(f"{root}/photos.csv", datetime.now()), _photos_csv(rows, data["notes"]))
        zf.writestr(_info(f"{root}/README.txt", datetime.now()), _readme(data, missing, with_exif).encode("utf-8"))
    yield pipe.drain()   # zip 끝(중앙 디렉터리)


def _info(name: str, when: datetime) -> zipfile.ZipInfo:
    """zip 항목 정보 — 파일 시각을 촬영·수정 시각으로 (zip 은 1980년 이전을 담지 못한다)"""
    when = when if when and when.year >= 1980 else datetime(1980, 1, 1)
    info = zipfile.ZipInfo(name, date_time=when.timetuple()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def _photos_csv(rows, notes) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["pic_id", "날짜", "촬영시각", "위도", "경도", "상태", "원본파일명", "파일", "설명제목"])
    for p, path in rows:
        located = photo_logic.has_location(p)
        first_note = (notes.get(p["pic_id"]) or [None])[0]
        w.writerow([
            p["pic_id"], p["base_dt"], f"{p['photo_at']:%Y-%m-%d %H:%M:%S}",
            p["latitude"] if located else "", p["longitude"] if located else "",
            photo_logic.STATUS_LABELS.get(p["status"].upper(), p["status"]),
            p["original_file_name"] or "", path or "(파일 없음)",
            (first_note["title"] or "") if first_note else "",
        ])
    return ("﻿" + buf.getvalue()).encode("utf-8")   # BOM — 엑셀이 한글을 깨뜨리지 않게


def _readme(data, missing, with_exif) -> str:
    lines = [
        "TracePic 백업",
        f"기간: {data['start']} ~ {data['end']}",
        f"만든 시각: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"사진 {len(data['photos']) - len(missing)}장 · 일기 {len(data['dailies'])}편 · "
        f"사진 설명 {sum(len(v) for v in data['notes'].values())}건",
        "",
        "구성",
        "  photos/날짜/촬영시각_번호.jpg   사진 (웹용 크기 — 원본은 TracePic 에 보관하지 않습니다)",
        "  photos/날짜/촬영시각_번호.webp  WebP 로 올린 사진·동영상 클립(영상의 3~7초, 소리 없음) — EXIF 없음, 시각·위치는 photos.csv",
        "  diary/날짜.md                    일기 (마크다운)",
        "  notes/촬영시각_번호.md           사진 설명 (마크다운, 사진 파일과 이름이 같습니다)",
        "  photos.csv                       사진 목록 (촬영 시각·위치·상태·원본 파일명)",
        "",
        ("사진 파일에는 촬영 시각과 위치(GPS)를 EXIF 로 넣었습니다. 다른 사진 앱이나 TracePic 에 다시 올리면 시각·위치가 그대로 잡힙니다."
         if with_exif else "사진 파일에는 촬영 시각·위치(EXIF)를 넣지 않았습니다. photos.csv 를 참고하세요."),
        "이 파일은 암호화되어 있지 않습니다. 안전한 곳에 보관하세요.",
    ]
    if missing:
        lines += ["", f"빠진 사진 {len(missing)}장 (저장소에 파일이 없거나 복호화 실패):"] + [f"  {m}" for m in missing]
    return "\n".join(lines) + "\n"
