"""
동영상 → 움직이는 WebP 클립 (DB 와 무관)

TracePic 은 동영상 자체를 보관하지 않는다. 영상의 3~7초 구간(4초)만 잘라 움직이는 WebP 3개를 만든다.
- image : 짧은 변 720px (720p) — 크게 보기
- thumb : 긴 변 400px          — 지도 팝업·일기·여행기 (사진 썸네일과 같은 크기)
- mini  : 128px 정사각형       — 지도 마커·촬영 순서 필름

ffmpeg 사용 방식
- 실행 파일: config FFMPEG_PATH → PATH 의 ffmpeg → (설치돼 있으면) imageio-ffmpeg 가 가진 ffmpeg 순서로 찾는다.
- `-ss 3` 을 입력 앞에 둬서 3초 근처 키프레임으로 바로 건너뛰고(앞부분은 읽지 않음), `-t 4` 로 4초 분량을 뽑으면
  ffmpeg 가 거기서 멈춘다 → 긴 영상도 처음 7초 남짓만 디코딩한다. 회전 정보(세로 영상)는 ffmpeg 가 자동 반영한다.
- 프레임은 PNG 로 표준출력(pipe)에 받아 메모리에서 처리한다 — 결과 프레임을 디스크에 쓰지 않는다.
- 소리는 쓰지 않는다(-an).

메타데이터(촬영 시각·위치)
- `ffmpeg -i 파일 -f ffmetadata -` 의 전역 태그 + 입력 정보(stderr)의 Metadata 를 함께 읽는다.
  (ffmetadata 출력은 creation_time 을 일부러 빼므로 촬영 시각은 입력 정보에서 얻는다)
  · 위치: com.apple.quicktime.location.ISO6709 / location / location-eng (예: '+37.5665+126.9780/')
  · 시각: com.apple.quicktime.creationdate(현지 시간대 포함 → 그 현지 시각 그대로)
          creation_time(UTC, 안드로이드·DJI) → 업로드한 브라우저의 시간대(tz_minutes)로 바꿈
- 1904/1970 같은 '0 시각' 값은 없는 것으로 본다.
"""
import io
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps

CLIP_START = 3.0          # 잘라 낼 구간 시작(초)
CLIP_END = 7.0            # 구간 끝(초)
CLIP_FPS = 10             # 초당 프레임 (4초 = 40장)
IMAGE_SHORT_SIDE = 720    # 크게 보기: 짧은 변
THUMB_SIDE = 400          # 썸네일: 긴 변 (utils/image.THUMB_SIDE 와 같음)
MINI_SIDE = 128           # 마커용 정사각형
QUALITY = {"image": 70, "thumb": 65, "mini": 60}   # WebP 손실 압축 품질

VIDEO_EXTENSIONS = {"mp4", "mov", "m4v", "3gp"}    # 업로드 허용 확장자 (실제 내용은 ffmpeg 가 판별)
_PNG_END = b"IEND\xaeB`\x82"                         # PNG 파일의 마지막 8바이트 (IEND 청크 + CRC)
_ISO6709 = re.compile(r"^\s*([+-]\d{1,2}(?:\.\d+)?)([+-]\d{1,3}(?:\.\d+)?)")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_TIMEOUT = 180            # ffmpeg 한 번 실행 최대 시간(초)


class VideoError(ValueError):
    """사용자에게 그대로 보여 줘도 되는 동영상 오류"""


def is_video_name(name: str | None) -> bool:
    """파일 이름 확장자로 동영상인지 (업로드 분기용 — 실제 판별은 ffmpeg 가 한다)"""
    return bool(name) and "." in name and name.rsplit(".", 1)[-1].lower() in VIDEO_EXTENSIONS


def find_ffmpeg(configured: str | None = None) -> str | None:
    """ffmpeg 실행 파일 경로 (없으면 None)"""
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # 선택 의존성: pip 로 ffmpeg 바이너리를 함께 받은 경우
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — 설치 안 됨 / 바이너리 없음
        return None


# ============================================================
# 메타데이터
# ============================================================
def probe(ffmpeg: str, path: Path) -> tuple[float | None, dict]:
    """(길이 초, 전역 메타데이터 태그 dict) — 동영상이 아니거나 읽을 수 없으면 VideoError"""
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostdin", "-i", str(path), "-f", "ffmetadata", "-"],
            capture_output=True, timeout=60,
        )
    except subprocess.TimeoutExpired as e:
        raise VideoError("동영상 정보를 읽는 데 시간이 너무 오래 걸립니다.") from e
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0 or "Video:" not in err:
        raise VideoError("동영상 파일을 읽을 수 없습니다.")
    # ffmetadata 출력은 creation_time 을 빼고 내보낸다 → 입력 정보(stderr)의 Metadata 를 바탕으로,
    # 값이 정확한(줄바꿈·이스케이프 처리된) ffmetadata 태그를 덮어쓴다.
    tags = parse_input_metadata(err)
    tags.update(parse_ffmetadata(r.stdout.decode("utf-8", "replace")))
    return parse_duration(err), tags


def parse_duration(stderr_text: str) -> float | None:
    """ffmpeg 출력의 'Duration: 00:01:02.34' → 62.34 (없거나 N/A 면 None)"""
    m = _DURATION.search(stderr_text)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def parse_input_metadata(stderr_text: str) -> dict:
    """ffmpeg 입력 정보(stderr)의 전역 'Metadata:' 구역 → 태그 dict (키는 소문자)

    전역 구역에 creation_time 이 없으면 첫 스트림의 creation_time 을 쓴다(일부 카메라).
    """
    tags, in_global = {}, False
    for line in stderr_text.splitlines():
        if line.startswith("  Metadata:"):          # 들여쓰기 2칸 = 파일 전역 (스트림은 4칸)
            in_global = True
            continue
        if in_global:
            m = re.match(r"^    (\S[^:]*?)\s*:\s?(.*)$", line)
            if not m:
                break                              # 'Duration:' 등 다음 구역
            tags[m.group(1).strip().lower()] = m.group(2).strip()
    if "creation_time" not in tags:
        m = re.search(r"^\s+creation_time\s*:\s*(\S+)", stderr_text, re.M)
        if m:
            tags["creation_time"] = m.group(1)
    return tags


def parse_ffmetadata(text: str) -> dict:
    """';FFMETADATA1' 형식 → 전역 태그 dict (키는 소문자). 스트림·챕터 구역([STREAM] 등)은 무시"""
    tags = {}
    for line in text.splitlines():
        if line.startswith("["):
            break                       # 전역 구역 끝
        if not line or line.startswith(";") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        tags[k.strip().lower()] = v.replace("\\=", "=").replace("\\;", ";").replace("\\#", "#").strip()
    return tags


def parse_location(tags: dict) -> tuple[float, float] | None:
    """태그 → (위도, 경도). 없거나 범위를 벗어나거나 0,0 이면 None"""
    for key in ("com.apple.quicktime.location.iso6709", "location", "location-eng"):
        m = _ISO6709.match(tags.get(key, ""))
        if not m:
            continue
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0.0, 0.0):
            return round(lat, 7), round(lng, 7)
    return None


def parse_time(tags: dict, tz_minutes: int | None) -> datetime | None:
    """태그 → 촬영 현지 시각(시간대 없는 datetime). 없으면 None

    - creationdate(시간대 포함, 아이폰): 그 현지 시각 그대로 (사진 EXIF 와 같은 규칙)
    - creation_time(UTC): tz_minutes(브라우저 시간대, 동쪽 +분)를 더한다. 모르면 UTC 그대로 쓰지 않고 None
    """
    raw = tags.get("com.apple.quicktime.creationdate")
    if raw:
        dt = _parse_iso(raw)
        if dt is not None:
            return _sane(dt.replace(tzinfo=None))
    raw = tags.get("creation_time")
    if raw and tz_minutes is not None:
        dt = _parse_iso(raw)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            local = dt.astimezone(timezone(timedelta(minutes=tz_minutes)))
            return _sane(local.replace(tzinfo=None))
    return None


def _parse_iso(value: str) -> datetime | None:
    """'2026-11-03T02:40:12.000000Z' / '2026-11-03T11:40:12+0900' → datetime"""
    v = value.strip().replace("Z", "+00:00")
    v = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", v)      # +0900 → +09:00
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _sane(dt: datetime) -> datetime | None:
    """1990년 이전(1904·1970 '0 시각' 등)이나 먼 미래면 None"""
    if not (datetime(1990, 1, 1) <= dt <= datetime.now() + timedelta(days=1)):
        return None
    return dt.replace(microsecond=0)


def clip_window(duration: float | None) -> tuple[float, float]:
    """(시작 초, 길이 초) — 기본 3~7초. 7초보다 짧으면 끝에서 4초, 4초보다 짧으면 처음부터 전부"""
    length = CLIP_END - CLIP_START
    if duration is None or duration >= CLIP_END:
        return CLIP_START, length
    if duration > length:
        return round(duration - length, 3), length
    return 0.0, max(duration, 0.1)


# ============================================================
# 프레임 → WebP
# ============================================================
def extract_frames(ffmpeg: str, path: Path, start: float, length: float) -> list[Image.Image]:
    """구간의 프레임(RGB, 짧은 변 최대 720px, 초당 CLIP_FPS)을 PIL 이미지 목록으로"""
    s = IMAGE_SHORT_SIDE
    # 회전 반영 뒤 크기 기준: 가로 영상이면 높이, 세로 영상이면 너비를 s 이하로 (확대는 안 함), 짝수로 맞춤
    scale = (f"scale='if(gte(iw,ih),-2,min({s},iw))':'if(gte(iw,ih),min({s},ih),-2)'"
             f":flags=lanczos")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
           "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path),
           "-an", "-sn", "-dn", "-vf", f"fps={CLIP_FPS},{scale}",
           "-pix_fmt", "rgb24", "-f", "image2pipe", "-c:v", "png", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise VideoError("동영상 변환 시간이 너무 오래 걸립니다.") from e
    frames = split_png_stream(r.stdout)
    if r.returncode != 0 or not frames:
        raise VideoError("동영상에서 장면을 뽑지 못했습니다. (지원하지 않는 코덱일 수 있습니다)")
    return frames


def split_png_stream(data: bytes) -> list[Image.Image]:
    """PNG 여러 장이 이어 붙은 바이트 → 이미지 목록 (IEND 로 경계를 찾는다)"""
    frames, pos = [], 0
    while True:
        end = data.find(_PNG_END, pos)
        if end < 0:
            break
        end += len(_PNG_END)
        img = Image.open(io.BytesIO(data[pos:end]))
        img.load()
        frames.append(img.convert("RGB"))
        pos = end
    return frames


def is_animated(img: Image.Image) -> bool:
    """움직이는 그림(프레임 2장 이상)인지 — 업로드된 움직이는 WebP 를 클립으로 저장할지 정할 때 쓴다"""
    return getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1


def frames_from_animation(img: Image.Image) -> list[Image.Image]:
    """
    움직이는 그림(WebP 등) → 클립 프레임 목록 (동영상 클립과 같은 규칙: 초당 CLIP_FPS, 최대 4초, 짧은 변 최대 720px)
    - 앞에서부터 4초만 쓴다. 더 짧으면 전체 길이만큼 (반복 재생은 to_webp 의 loop=0 이 맡음).
    - 원래 프레임 간격이 제각각이어도 0.1초마다 '그 순간 보이는 프레임'을 골라 고르게 맞춘다.
    - 메모리: 고른 프레임만 바로 줄여서 RGB 로 남긴다 (원본 크기 프레임을 모아 두지 않음). 4초를 넘는 프레임은 디코딩하지 않는다.
    - 투명한 부분은 흰색으로 채운다 (사진과 같은 규칙).
    """
    limit_ms = (CLIP_END - CLIP_START) * 1000
    step_ms = 1000 / CLIP_FPS
    frames: list[Image.Image] = []
    t = 0.0             # 지금 프레임이 시작하는 시각(ms)
    next_ms = 0.0       # 다음에 뽑을 시각(ms)
    for i in range(img.n_frames):
        img.seek(i)
        img.load()                                 # Pillow 는 load() 뒤에야 이 프레임의 duration 을 채운다
        dur = img.info.get("duration") or 100      # 0·없음이면 브라우저처럼 0.1초로 본다
        shown = None
        while next_ms < t + dur and next_ms < limit_ms:
            if shown is None:
                shown = _clip_frame(img)
            frames.append(shown)                   # 같은 프레임이 여러 번이면 같은 객체를 다시 쓴다
            next_ms += step_ms
        t += dur
        if next_ms >= limit_ms:
            break
    if not frames:
        img.seek(0)
        frames.append(_clip_frame(img))
    return frames


def _clip_frame(img: Image.Image) -> Image.Image:
    """지금 프레임 → 흰 배경 RGB, 짧은 변 IMAGE_SHORT_SIDE 이하 (확대는 안 함)"""
    rgba = img.convert("RGBA")
    frame = Image.new("RGB", rgba.size, (255, 255, 255))
    frame.paste(rgba, mask=rgba.getchannel("A"))
    w, h = frame.size
    scale = IMAGE_SHORT_SIDE / min(w, h)
    if scale < 1:
        frame = frame.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
    return frame


def to_webp(frames: list[Image.Image], kind: str) -> bytes:
    """프레임 목록 → 크기별 움직이는 WebP (무한 반복)"""
    if kind == "image":
        out = frames
    elif kind == "thumb":
        out = []
        for f in frames:
            f = f.copy()
            f.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
            out.append(f)
    elif kind == "mini":
        out = [ImageOps.fit(f, (MINI_SIDE, MINI_SIDE), Image.Resampling.LANCZOS) for f in frames]
    else:
        raise ValueError(f"알 수 없는 종류: {kind}")
    buf = io.BytesIO()
    out[0].save(buf, format="WEBP", save_all=True, append_images=out[1:], duration=round(1000 / CLIP_FPS),
                loop=0, quality=QUALITY[kind], method=4)
    return buf.getvalue()


def is_webp(data: bytes) -> bool:
    """복호화한 파일이 WebP 인지 (응답 Content-Type·백업 확장자 결정용)"""
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
