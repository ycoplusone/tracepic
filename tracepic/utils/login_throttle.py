"""
로그인 실패 횟수 제한 (무차별 대입 방지)

- 키(IP, 사용자ID)별 실패 횟수를 메모리에 기록하고, 한도를 넘으면 일정 시간 로그인을 막는다.
- 메모리 저장이므로 gunicorn 워커마다 따로 집계되고 재시작하면 초기화된다.
  개인용 서비스 규모에서는 충분하며, 필요해지면 DB/Redis 기반으로 교체한다.
- Nginx 뒤에서 운영할 때는 ProxyFix 를 적용해야 실제 클라이언트 IP 가 잡힌다.
"""
import threading
import time


class LoginThrottle:
    def __init__(self) -> None:
        # key → (실패 횟수, 첫 실패 시각)
        self._fails: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def locked_seconds(self, key: str, max_fails: int, window_sec: int) -> int:
        """잠겨 있으면 남은 초, 아니면 0"""
        with self._lock:
            count, first = self._fails.get(key, (0, 0.0))
            remain = int(first + window_sec - time.time())
            if remain <= 0:
                self._fails.pop(key, None)  # 기간 만료 → 초기화
                return 0
            return remain if count >= max_fails else 0

    def record_fail(self, key: str) -> None:
        """실패 1회 기록 (첫 실패 시각부터 기간 계산)"""
        with self._lock:
            count, first = self._fails.get(key, (0, time.time()))
            self._fails[key] = (count + 1, first)

    def reset(self, key: str) -> None:
        """로그인 성공 시 기록 삭제"""
        with self._lock:
            self._fails.pop(key, None)


# 앱 전역에서 공유하는 인스턴스
login_throttle = LoginThrottle()
