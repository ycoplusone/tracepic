"""
짧은 시간 동안만 값을 기억하는 메모리 캐시 (DB 와 무관, 스레드 안전)

- 프로세스(gunicorn 워커)마다 따로 가진다. 워커끼리 공유하지 않는다.
- 크기가 max_size 를 넘으면 만료된 항목부터, 그래도 넘치면 가장 오래 넣은 항목부터 지운다.
"""
import threading
import time


class TTLCache:
    def __init__(self, max_size: int = 1024):
        self._data: dict = {}          # key → (만료 시각, 값). dict 는 넣은 순서를 기억한다
        self._lock = threading.Lock()
        self._max = max_size

    def get(self, key):
        """살아 있는 값이면 반환, 없거나 만료면 None"""
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            if item[0] < time.monotonic():
                del self._data[key]
                return None
            return item[1]

    def set(self, key, value, ttl: float) -> None:
        with self._lock:
            now = time.monotonic()
            self._data.pop(key, None)
            self._data[key] = (now + ttl, value)
            if len(self._data) > self._max:
                for k in [k for k, (exp, _) in self._data.items() if exp < now]:
                    del self._data[k]
                while len(self._data) > self._max:
                    del self._data[next(iter(self._data))]

    def delete(self, key) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
