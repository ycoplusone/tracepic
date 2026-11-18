"""
마크다운 → 안전한 HTML 변환 (DB 와 무관)

- 변환(Markdown) 결과는 항상 nh3 로 살균(sanitize)한다 — <script>, onerror= 같은 위험 요소 제거.
- 이미지(<img>)는 이 서비스의 사진(/photos/...)만 허용한다.
  외부 이미지를 허용하면 기록을 열 때마다 외부 서버로 접속 기록이 남을 수 있기 때문이다.
- 링크에는 rel="noopener noreferrer" 가 붙는다 (nh3 기본값).
"""
import re

import markdown
import nh3

# 마크다운 확장: 표·각주·코드블록(extra), 줄바꿈 그대로(nl2br — 일기처럼 엔터가 곧 줄바꿈), 목록 보정
_EXTENSIONS = ["extra", "nl2br", "sane_lists"]

# 허용 태그: nh3 기본 목록에 표·체크박스 관련 태그만 더한다
_TAGS = set(nh3.ALLOWED_TAGS) | {"input"}
_ATTRIBUTES = {k: set(v) for k, v in nh3.ALLOWED_ATTRIBUTES.items()}
_ATTRIBUTES["input"] = {"type", "checked", "disabled"}


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    """속성 값 검사: 이미지는 내부 사진 경로만, input 은 체크박스만 남긴다"""
    if tag == "img" and attr == "src":
        return value if value.startswith("/photos/") else None
    if tag == "input" and attr == "type":
        return value if value == "checkbox" else None
    return value


def render(md_text: str) -> str:
    """마크다운 원문 → 살균된 HTML"""
    html = markdown.markdown(md_text or "", extensions=_EXTENSIONS, output_format="html")
    html = _task_list(html)
    return nh3.clean(
        html,
        tags=_TAGS,
        attributes=_ATTRIBUTES,
        attribute_filter=_attribute_filter,
        url_schemes={"http", "https", "mailto"},
    )


def _task_list(html: str) -> str:
    """'- [ ] 할 일' / '- [x] 한 일' 을 체크박스로 바꾼다 (읽기 전용)"""
    html = re.sub(r"<li>\[ \]\s?", '<li><input type="checkbox" disabled> ', html)
    return re.sub(r"<li>\[[xX]\]\s?", '<li><input type="checkbox" checked disabled> ', html)


# 요약문을 만들 때 지울 마크다운 기호
_MD_NOISE = [
    (re.compile(r"```.*?```", re.S), " "),           # 코드 블록
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),       # 이미지
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),    # 링크 → 글자만
    (re.compile(r"^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s*", re.M), ""),  # 제목·인용·목록 기호
    (re.compile(r"[*_~`]+"), ""),                     # 강조 기호
    (re.compile(r"\[[ xX]\]\s?"), ""),                # 체크박스
    (re.compile(r"\s+"), " "),                        # 공백 정리
]


def excerpt(md_text: str, length: int = 120) -> str:
    """카드에 보여 줄 짧은 평문 요약 (마크다운 기호 제거)"""
    text = md_text or ""
    for pattern, repl in _MD_NOISE:
        text = pattern.sub(repl, text)
    text = text.strip()
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def plain_text(md_text: str) -> str:
    """마크다운 기호를 지운 평문 (요약·검색 미리보기용)"""
    text = md_text or ""
    for pattern, repl in _MD_NOISE:
        text = pattern.sub(repl, text)
    return text.strip()


def snippet(md_text: str, keyword: str, width: int = 70) -> str:
    """
    검색 결과 미리보기: 평문에서 검색어가 처음 나오는 곳 앞뒤 width 자 (대소문자 무시)
    - 검색어가 평문에 없으면(마크다운 기호 안에만 있는 경우 등) 앞부분 요약을 돌려준다.
    """
    text = plain_text(md_text)
    pos = text.lower().find(keyword.lower()) if keyword else -1
    if pos < 0:
        return excerpt(md_text, width * 2)
    start = max(0, pos - width)
    end = min(len(text), pos + len(keyword) + width)
    return ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")
