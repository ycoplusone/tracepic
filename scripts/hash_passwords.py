"""
user_info 평문 비밀번호 → bcrypt 해시 일괄 변환 (한 번만 실행하는 관리 스크립트)

사용법 (프로젝트 루트에서):
    .venv/bin/python scripts/hash_passwords.py --dry-run   # 바꿀 건수만 확인
    .venv/bin/python scripts/hash_passwords.py             # 실제 변환

- 되돌릴 수 없습니다(평문이 사라짐). user_info 를 같이 쓰는 다른 서비스가 bcrypt 검증을 지원해야 합니다.
- 이미 해시인 행은 건너뛰므로 여러 번 실행해도 안전합니다. 비밀번호 값은 화면에 찍지 않고 건수만 보여 줍니다.
- 운영 서버에서도 .env 의 DB 를 대상으로 같은 방법으로 실행합니다.
"""
import argparse
import os
import sys

# scripts/ 에서 실행해도 프로젝트 루트의 app·tracepic 을 찾도록
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from tracepic.logics.auth_logic import hash_plain_passwords  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="user_info 평문 비밀번호를 bcrypt 로 변환")
    parser.add_argument("--dry-run", action="store_true", help="바꾸지 않고 건수만 확인")
    args = parser.parse_args()
    with app.app_context():
        r = hash_plain_passwords(dry_run=args.dry_run)
    mode = "확인만(dry-run)" if args.dry_run else "변환 완료"
    print(f"[{mode}] 전체 {r['total']}명 · 이미 해시 {r['already_hashed']} · "
          f"{'변환 대상' if args.dry_run else '변환'} {r['converted']} · 건너뜀 {r['skipped']}")


if __name__ == "__main__":
    main()
