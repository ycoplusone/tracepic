"""
TracePic 비즈니스 로직 패키지

계층 규칙
- routes  : 요청 파싱 / 응답 반환만 담당 → logics 함수를 호출
- logics  : 업무 처리 + SQL 작성 (tracepic.db 헬퍼 사용) — 기능별 *_logic.py 파일로 분리
- utils   : DB 와 무관한 순수 기능 (EXIF, 이미지 처리, 암호화)
"""
