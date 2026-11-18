"""
GPS 거리 계산 (DB 와 무관)

- 하버사인(haversine) 공식으로 두 좌표 사이의 지표면 직선거리(km)를 구한다.
- '이동 거리'는 촬영 시각순으로 이어진 사진 좌표 사이 직선거리의 합이다.
  실제로 걷거나 달린 길이 아니라 '사진을 찍은 곳들을 차례로 이은 거리'이므로 실제보다 짧게 나온다.
"""
import math

EARTH_RADIUS_KM = 6371.0088   # 지구 평균 반지름


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이 거리(km)"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def path_km(points) -> float:
    """[(위도, 경도), ...] 를 차례로 이은 거리 합(km). 점이 2개 미만이면 0"""
    points = list(points)
    return sum(haversine_km(*a, *b) for a, b in zip(points, points[1:]))
