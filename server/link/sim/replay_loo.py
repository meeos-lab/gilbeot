"""실제 사고 재현의 사고 하나 빼기 교차 검증(6.1절).

  python -X utf8 replay_loo.py
사고마다 최적 조합을 고르면 같은 실측으로 맞춘 표본 내 적합이다. 여기서는 나머지 두 사고의 제곱 오차 합이 가장 작은
(차단 차로, 처리 시간) 한 가지를 골라 뺀 사고에 적용하고, 24칸 전체의 상관·RMSE 를 낸다.
"""
import json
import math
from pathlib import Path

RES = Path(__file__).parent / "results"


def loo(tag):
    j = json.loads((RES / f"replay{tag}.json").read_text(encoding="utf-8"))
    tab = {d: {(f["blocked"], f["dur_min"]): f for f in e["fits"] if f["rmse_ratio"] is not None} for d, e in j.items()}
    combos = set.intersection(*(set(t) for t in tab.values()))
    xs, ys, rows = [], [], []
    for d, e in j.items():
        best = min(combos, key=lambda c: sum(tab[o][c]["rmse_ratio"] ** 2 for o in j if o != d))
        f = tab[d][best]
        rows.append((d, best, round(f["rmse_ratio"], 3), round(min(x["rmse_ratio"] for x in tab[d].values()), 3)))
        for k, v in e["obs_ratio"].items():
            if k in f["sim_ratio"]:
                xs.append(v); ys.append(f["sim_ratio"][k])
    n, mx, my = len(xs), sum(xs) / len(xs), sum(ys) / len(ys)
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    rmse = math.sqrt(sum((a - b) ** 2 for a, b in zip(xs, ys)) / n)
    return rows, r, rmse


if __name__ == "__main__":
    for tag, name in (("", "v1"), ("_v2", "v2")):
        rows, r, rmse = loo(tag)
        print(name, f"r {r:.2f} RMSE {rmse:.3f}")
        for d, c, out, ins in rows:
            print(f"  {d}: 빼고 고른 조합 {c[0]}차로 {c[1]}분 → RMSE {out} (사고별 최적 {ins})")
