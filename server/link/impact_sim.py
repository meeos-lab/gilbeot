"""충돌 감지 규칙 모의실험 — 앱 CarSignals.feedFast 를 그대로 옮겨, 10 Hz 차속 표본에서 제동과 충돌이 갈리는지 본다.

사용: python -X utf8 impact_sim.py [회수=200]
규칙(앱과 같은 값): 두 표본 사이 평균 감속률 >= 14 m/s², 속도 차 >= 2.2 m/s(8 km/h), 간격 0.08~0.5 s 이면 후보.
후보 뒤 0.5 s 동안 표본이 하나라도 사건 전 속도의 50 % 이상이면 튐으로 버리고, 0.5 s 를 넘긴 표본이 오면 충돌 확정.
표본: 10 Hz, 시각 지터 ±20 ms, 누락 0/30/50 %, 속도 잡음(선택). 같은 시드로 다시 돌리면 같은 결과가 나온다.
"""
import random
import sys

G = 9.80665
IMPACT_A, IMPACT_DV, DT_MIN, DT_MAX, HOLD = 14.0, 2.2, 0.08, 0.5, 0.5   # CarSignals.kt 의 상수


def detect(samples):
    """CarSignals.feedFast 와 같은 순서·조건. 표본 [(초, m/s)] → 충돌 확정이면 True"""
    fast, cand = [], None
    for t, v in samples:
        fast.append((t, v))
        fast = [p for p in fast if t - p[0] <= 2.5]
        if cand is not None:
            if v >= 0.5 * cand[1]:
                cand = None
                continue
            if t - cand[0] >= HOLD:
                return True
            continue
        for tk, vk in reversed(fast[:-1]):
            dt = t - tk
            if dt > DT_MAX:
                break
            if dt >= DT_MIN and vk - v >= IMPACT_DV and (vk - v) / dt >= IMPACT_A:
                cand = (t, vk, v)
                break
    return False


def sample(profile, rng, drop=0.0, jitter=0.02, noise=0.0, hz=10.0, length=6.0):
    out, t = [], 0.0
    while t < length:
        tt = t + rng.uniform(-jitter, jitter)
        if rng.random() >= drop:
            out.append((tt, max(0.0, profile(tt) + (rng.gauss(0, noise) if noise else 0.0))))
        t += 1.0 / hz
    return out


def brake(v0, g, t0=1.0):
    return lambda t: v0 if t < t0 else max(0.0, v0 - g * G * (t - t0))


def crash(v0, v1, dur, after=None, t0=1.0):
    """t0 에서 dur 동안 v0 → v1, 그 뒤 after(없으면 v1 유지)까지 2 m/s² 로 줄어든다"""
    def f(t):
        if t < t0:
            return v0
        if t < t0 + dur:
            return v0 + (v1 - v0) * (t - t0) / dur
        if after is None:
            return v1
        return max(after, v1 - 2.0 * (t - t0 - dur))
    return f


def glitch(v0, t0=1.0):
    return lambda t: 0.0 if t0 <= t < t0 + 0.1 else v0


SCENES = [
    ("제동 0.3 g (90 km/h)", brake(25, 0.3), False),
    ("제동 0.6 g", brake(25, 0.6), False),
    ("제동 0.8 g", brake(25, 0.8), False),
    ("ABS 한계 1.0 g", brake(25, 1.0), False),
    ("마른 노면 최대 1.1 g", brake(25, 1.1), False),
    ("1.1 g, 120 km/h 에서", brake(33, 1.1), False),
    ("한 표본 튐 25→0→25", glitch(25), False),
    ("정면 충돌 25→2 m/s, 120 ms", crash(25, 2, 0.12), True),
    ("충돌 20→8 m/s, 100 ms 뒤 정지", crash(20, 8, 0.10, after=0), True),
    ("약한 충돌 15→9 m/s(Δv 6), 150 ms 뒤 정지", crash(15, 9, 0.15, after=0), True),
    ("저속 추돌 8→0 m/s, 100 ms", crash(8, 0, 0.10), True),
    ("스침 25→20 m/s, 100 ms 뒤 계속 주행", crash(25, 20, 0.10), None),   # 규칙상 못 잡는다(한계)
]


def main(n=200):
    print(f"회수 {n}, 지터 ±20 ms. 값은 '충돌로 판정한 비율' — 제동·튐은 0 % 여야, 충돌은 100 % 에 가까워야 한다")
    print(f"{'장면':<34} {'누락 0%':>8} {'누락 30%':>9} {'누락 50%':>9} {'잡음 0.3':>9}")
    for name, prof, want in SCENES:
        cells = []
        for drop, noise in ((0.0, 0.0), (0.3, 0.0), (0.5, 0.0), (0.0, 0.3)):
            rng = random.Random(f"{name}|{drop}|{noise}")
            hit = sum(detect(sample(prof, rng, drop=drop, noise=noise)) for _ in range(n))
            cells.append(f"{100 * hit / n:.0f}%")
        tag = {True: "충돌", False: "충돌 아님", None: "한계"}[want]
        print(f"{name:<34} {cells[0]:>8} {cells[1]:>9} {cells[2]:>9} {cells[3]:>9}   ({tag})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
