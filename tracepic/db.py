"""
DB 접근 헬퍼 (PyMySQL 직접 사용, ORM 미사용)

- 요청(앱 컨텍스트)마다 커넥션 1개를 flask.g 에 두고 쓴다. 커넥션은 풀(_Pool)에서 빌려 오고,
  요청이 끝나면 롤백(커밋 안 된 작업 정리) 후 풀에 돌려준다 → 원격 MySQL 접속·인증을 요청마다 반복하지 않는다.
- 풀은 프로세스(gunicorn 워커)마다 하나씩 만든다. fork 전에 만든 소켓을 여러 워커가 함께 쓰지 않도록 pid 를 확인한다.
- 조회 결과는 dict 로 반환한다 (DictCursor).
- SQL 은 logics/ 에서 직접 작성하고, 값은 반드시 %s 파라미터 바인딩으로 넘긴다 (SQL 인젝션 방지).

사용 예 (logics 안에서):
    from tracepic.db import fetch_one, fetch_all, execute, transaction

    row  = fetch_one("SELECT * FROM tracepic_photos WHERE pic_id = %s", (pic_id,))
    rows = fetch_all("SELECT * FROM tracepic_photos WHERE user_id = %s", (user_id,))
    new_id = execute("INSERT INTO tracepic_notes (pic_id, note) VALUES (%s, %s)", (pic_id, md))

    with transaction() as cur:          # 여러 SQL 을 하나의 트랜잭션으로 묶을 때
        cur.execute("UPDATE ...", (...))
        cur.execute("INSERT ...", (...))
"""
import os
import queue
import threading
import time
from contextlib import contextmanager

import pymysql
from flask import Flask, current_app, g
from pymysql.cursors import DictCursor


class _Pool:
    """
    아주 단순한 커넥션 풀 (스레드 안전)
    - 빌려줄 커넥션이 없으면 새로 연결하고, 돌려받을 때 자리가 없으면 닫는다 (최대 동시 사용 수는 제한하지 않음).
    - 오래된(recycle) 커넥션은 닫고 새로 연결, 오래 쉰(ping_idle) 커넥션은 ping 으로 확인 후 쓴다.
    """

    def __init__(self, config: dict, size: int, recycle: int, ping_idle: int):
        self._config = config
        self._idle: queue.LifoQueue = queue.LifoQueue(maxsize=max(size, 0) or 1)  # 최근에 쓴 것부터 (살아 있을 확률이 높음)
        self._recycle = recycle
        self._ping_idle = ping_idle
        self.pid = os.getpid()

    def _connect(self) -> pymysql.connections.Connection:
        conn = pymysql.connect(
            **self._config,
            charset="utf8mb4",        # 한글·이모지 안전
            cursorclass=DictCursor,   # 결과를 dict 로
            autocommit=False,         # 쓰기는 commit 을 명시적으로
            connect_timeout=5,
        )
        conn._tp_born = conn._tp_used = time.monotonic()
        return conn

    def get(self) -> pymysql.connections.Connection:
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                return self._connect()
            now = time.monotonic()
            if now - conn._tp_born > self._recycle:
                _quiet_close(conn)
                continue
            if now - conn._tp_used > self._ping_idle:
                try:
                    conn.ping(reconnect=False)   # 끊겼으면 예외 → 버리고 다음 것(또는 새 연결)
                except Exception:  # noqa: BLE001
                    _quiet_close(conn)
                    continue
            return conn

    def put(self, conn: pymysql.connections.Connection) -> None:
        try:
            conn.rollback()                      # 커밋 안 된 작업은 버린다 (다음 요청에 섞이지 않게)
        except Exception:  # noqa: BLE001 — 끊긴 커넥션은 버린다
            _quiet_close(conn)
            return
        conn._tp_used = time.monotonic()
        try:
            self._idle.put_nowait(conn)
        except queue.Full:
            _quiet_close(conn)


def _quiet_close(conn) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


_pool_lock = threading.Lock()


def _get_pool() -> _Pool:
    """현재 앱·프로세스의 풀 (없거나 fork 로 프로세스가 바뀌었으면 새로 만든다)"""
    app = current_app._get_current_object()
    pool = app.extensions.get("tracepic_db_pool")
    if pool is None or pool.pid != os.getpid():
        with _pool_lock:
            pool = app.extensions.get("tracepic_db_pool")
            if pool is None or pool.pid != os.getpid():
                cfg = app.config
                pool = _Pool(cfg["DB_CONFIG"], cfg.get("DB_POOL_SIZE", 5),
                             cfg.get("DB_POOL_RECYCLE", 3600), cfg.get("DB_POOL_PING_IDLE", 60))
                app.extensions["tracepic_db_pool"] = pool
    return pool


def get_conn() -> pymysql.connections.Connection:
    """현재 요청의 DB 커넥션 반환 (없으면 풀에서 빌려 온다)"""
    if "db_conn" not in g:
        g.db_conn = _get_pool().get()
    return g.db_conn


def close_conn(_exc: BaseException | None = None) -> None:
    """요청 종료 시 커넥션 정리: 커밋되지 않은 작업은 롤백한 뒤 풀에 돌려준다."""
    conn = g.pop("db_conn", None)
    if conn is None:
        return
    _get_pool().put(conn)


def fetch_one(sql: str, params: tuple | dict | None = None) -> dict | None:
    """단건 조회: 결과가 없으면 None"""
    with get_conn().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_all(sql: str, params: tuple | dict | None = None) -> list[dict]:
    """다건 조회: 결과가 없으면 빈 리스트"""
    with get_conn().cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def execute(sql: str, params: tuple | dict | None = None) -> int:
    """
    단일 INSERT / UPDATE / DELETE 실행 후 즉시 커밋
    반환값: INSERT 면 새 AUTO_INCREMENT id, 그 외에는 영향받은 행 수
    """
    with transaction() as cur:
        affected = cur.execute(sql, params)
        return cur.lastrowid or affected


@contextmanager
def transaction():
    """여러 SQL 을 하나의 트랜잭션으로 묶음: 정상 종료 시 커밋, 예외 시 롤백"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_app(app: Flask) -> None:
    """앱에 요청 종료 시 커넥션 정리 훅 등록"""
    app.teardown_appcontext(close_conn)
