"""
검색어 처리 (DB 와 무관)

- SQL LIKE 에서 % _ \\ 는 특수 문자다. 사용자가 입력한 검색어는 이 문자를 이스케이프한 뒤
  '%검색어%' 패턴으로 만들어 %s 로 바인딩한다 (SQL 을 문자열로 조립하지 않는다).
"""
MAX_KEYWORD = 100


def clean_keyword(raw) -> str:
    """검색어 정리: 앞뒤 공백 제거, 연속 공백 하나로. 비었거나 너무 길면 ValueError"""
    if not isinstance(raw, str):
        raise ValueError("검색어를 입력하세요.")
    keyword = " ".join(raw.split())
    if not keyword:
        raise ValueError("검색어를 입력하세요.")
    if len(keyword) > MAX_KEYWORD:
        raise ValueError(f"검색어는 {MAX_KEYWORD}자까지 입력할 수 있습니다.")
    return keyword


def like_contains(keyword: str) -> str:
    """'포함' 검색 패턴 — LIKE 특수 문자(\\ % _)를 글자 그대로 찾도록 이스케이프 (MySQL 기본 이스케이프 문자 \\)"""
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
