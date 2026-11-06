"""탐색 실험 J1 분석(사전 고정 docs/sim-preregistration.md 'J1' — 결과를 보기 전에 씀).

  python -X utf8 analyze_j1.py      → results/report_j1.json, report_j1.md
집합마다 고속 접근 상충의 씨앗별 변화율 평균: E1 = 일률 80 대 기준선, E2 = 일률 80 대 단계.
E 를 표준화한 매개변수 4개(주의 회복, log 다시 딴짓, 지연, 준수율)와 두 매개변수 곱으로 최소제곱 회귀.
"""
import json
import math
import statistics
from itertools import combinations
from pathlib import Path

import numpy as np

RES = Path(__file__).parent / "results"
B, G, U = "official", "official+tago12+relay", "official+tago12+relay-u80"
KEYS = ["attn_p", "redist", "delay", "comply"]
NAMES = {"attn_p": "주의 회복", "redist": "log 다시 딴짓까지", "delay": "반응 지연", "comply": "준수율"}


def main():
    rows = [json.loads(x) for x in (RES / "j1.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    by = {}
    for r in rows:
        k = json.dumps(r["ov"], sort_keys=True)
        by.setdefault(k, {}).setdefault(r["seed"], {})[r["scheme"]] = r
    sets = []
    for k, seeds in by.items():
        ov = json.loads(k)
        full = [s for s in seeds.values() if all(x in s for x in (B, G, U))]
        if not full:
            continue
        pct = lambda m, a, b: statistics.mean((s[b][m] - s[a][m]) / s[a][m] * 100 for s in full if s[a][m] > 0)
        rate = lambda s, sc: s[sc]["fast"] / max(1, s[sc]["exposed"]) * 1000
        sets.append({**ov, "n": len(full), "E1": pct("fast", B, U), "E2": pct("fast", G, U),
                     "E1_drac": pct("drac", B, U), "E2_drac": pct("drac", G, U),
                     "E1_rate": statistics.mean((rate(s, U) - rate(s, B)) / rate(s, B) * 100 for s in full if rate(s, B) > 0),
                     "E1_severe": pct("severe", B, U)})
    X0 = np.array([[s["attn_p"], math.log(s["redist"]), s["delay"], s["comply"]] for s in sets])
    Xs = (X0 - X0.mean(0)) / X0.std(0)
    cols = [NAMES[k] for k in KEYS] + [f"{NAMES[KEYS[i]]}×{NAMES[KEYS[j]]}" for i, j in combinations(range(4), 2)]
    X = np.column_stack([np.ones(len(sets)), Xs] + [Xs[:, i] * Xs[:, j] for i, j in combinations(range(4), 2)])
    rep = {"n_sets": len(sets), "sets": sets, "fits": {}}
    L = [f"# 탐색 실험 J1: 행동 가정 반응면 (집합 {len(sets)}개, 집합당 씨앗 {sets[0]['n'] if sets else 0}개)", "",
         "변화율: − = 일률 80 이 적음(좋음).", ""]
    for e in ("E1", "E2", "E1_drac", "E1_rate", "E1_severe"):
        y = np.array([s[e] for s in sets])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ beta
        r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        rep["fits"][e] = {"intercept": round(float(beta[0]), 2), "coef": {c: round(float(b), 2) for c, b in zip(cols, beta[1:])}, "r2": round(float(r2), 3),
                          "mean": round(float(y.mean()), 1), "worse_share": round(float((y > 0).mean()), 3)}
        f = rep["fits"][e]
        L += [f"## {e}: 평균 {f['mean']:+.1f} %, 나빠진 집합 {f['worse_share'] * 100:.0f} %, R² {f['r2']}", "",
              "| 항 | 계수(표준화, %p) |", "|---|---|"] + [f"| {c} | {b:+.2f} |" for c, b in f["coef"].items()] + [""]
    worse = [s for s in sets if s["E1"] > 0]
    if worse:
        L += ["## 기준선보다 나빠진 집합(E1 > 0)", "", "| 주의 회복 | 다시 딴짓 s | 지연 s | 준수율 | E1 | E2 |", "|---|---|---|---|---|---|"]
        L += [f"| {s['attn_p']:.2f} | {s['redist']:.0f} | {s['delay']:.1f} | {s['comply']:.2f} | {s['E1']:+.1f} | {s['E2']:+.1f} |" for s in sorted(worse, key=lambda s: -s["E1"])]
    (RES / "report_j1.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (RES / "report_j1.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
