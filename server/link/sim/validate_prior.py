"""검증 V1: 맞추지 않은 사전 예측 검증(사전 고정 docs/sim-preregistration.md '검증 V1').

  python -X utf8 validate_prior.py      → results/validate_prior.json, .md
재생 격자(막힌 차로 1·2 × 처리 시간 20~120분 × 씨앗 3)를 모형의 사전 분포로 가중해 칸(콘존 2 × 07~10시)마다 예측 분포를 만들고,
실측 속도비가 80 % 예측 구간(10~90 백분위)에 드는 비율과 예측 평균의 RMSE 를 낸다. 사고별 최적 조합(표본 내 적합)은 참고로만.
"""
import json
import math
import statistics
from pathlib import Path

import tago_sim as S
from replay import zone_speed

HERE = Path(__file__).parent
OBS = {o["day"]: o for o in json.loads((HERE / "data" / "obs.json").read_text(encoding="utf-8"))}
ZONES, HOURS = ["0010CZS460", "0010CZS450"], [7, 8, 9, 10]
MU, SG, LO, HI = S.PARAMS["dur_ln"]
BINS = {20: (10, 30), 40: (30, 50), 60: (50, 75), 90: (75, 90), 120: (90, 90)}


def lncdf(x):
    return 0.5 * (1 + math.erf((math.log(x) - MU) / (SG * math.sqrt(2))))


Z = lncdf(HI) - lncdf(LO)
W_DUR = {m: (lncdf(b) - lncdf(a)) / Z for m, (a, b) in BINS.items()}
W_BLK = dict(S.PARAMS["blocked"])


def wquant(pairs, q):
    pairs = sorted(pairs)
    tot, acc = sum(w for _, w in pairs), 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * tot:
            return v
    return pairs[-1][0]


def validate(tag, wfun=None):
    wfun = wfun or (lambda b, m: W_BLK.get(b, 0) * W_DUR.get(m, 0))
    rows = [json.loads(x) for x in (S.RES / f"replay{tag}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    base = [r for r in rows if r["day"] == "base"]
    out, cells = {}, []
    for day in sorted({r["day"] for r in rows if r["day"] != "base"}):
        o, sims = OBS[day], [r for r in rows if r["day"] == day]
        inc = []
        for z in ZONES:
            for h in HOURS:
                ob = o["zones"][z]["hours"].get(str(h), {}).get("ratio")
                bv = [v for v in (zone_speed(r["det"], o["km"], o["zones"][z], h) for r in base) if v]
                if ob is None or not bv:
                    continue
                bm = statistics.mean(bv)
                samples = []
                for r in sims:
                    v = zone_speed(r["det"], o["km"], o["zones"][z], h)
                    w = wfun(r["blocked"], r["dur_min"]) / 3
                    if v and w > 0:
                        samples.append((v / bm, w))
                if not samples:
                    continue
                tw = sum(w for _, w in samples)
                mean = sum(v * w for v, w in samples) / tw
                q10, q90 = wquant(samples, 0.10), wquant(samples, 0.90)
                inc.append({"cell": f"{z}@{h}", "obs": round(ob, 3), "pred": round(mean, 3), "q10": round(q10, 3), "q90": round(q90, 3),
                            "inside": q10 <= ob <= q90})
        cells += inc
        rm = lambda key: math.sqrt(statistics.mean((c[key] - c["obs"]) ** 2 for c in inc)) if inc else None
        out[day] = {"n": len(inc), "coverage": round(sum(c["inside"] for c in inc) / len(inc), 3) if inc else None,
                    "rmse_pred": round(rm("pred"), 3) if inc else None,
                    "rmse_null": round(math.sqrt(statistics.mean((1 - c["obs"]) ** 2 for c in inc)), 3) if inc else None, "cells": inc}
    allc = cells
    summ = {"n": len(allc), "coverage": round(sum(c["inside"] for c in allc) / len(allc), 3),
            "rmse_pred": round(math.sqrt(statistics.mean((c["pred"] - c["obs"]) ** 2 for c in allc)), 3),
            "rmse_null": round(math.sqrt(statistics.mean((1 - c["obs"]) ** 2 for c in allc)), 3),
            "bias": round(statistics.mean(c["pred"] - c["obs"] for c in allc), 3)}
    return {"summary": summ, "incidents": out}


def main():
    rep = {"weights": {"blocked": W_BLK, "dur_min": {k: round(v, 3) for k, v in W_DUR.items()}}}
    L = ["# 검증 V1: 맞추지 않은 사전 예측", "", f"가중치: 막힌 차로 {W_BLK}, 처리 시간 {rep['weights']['dur_min']}", ""]
    for tag, name in (("", "v1"), ("_v2", "v2")):
        p = S.RES / f"replay{tag}.jsonl"
        if not p.exists():
            continue
        r = validate(tag)
        rep[name] = r
        s = r["summary"]
        L += [f"## {name}: {s['n']}칸, 80 % 구간 포함 {s['coverage'] * 100:.0f} %, 예측 평균 RMSE {s['rmse_pred']} (사고 없음 가정 {s['rmse_null']}), 치우침 {s['bias']:+}", "",
              "| 사고 | 칸 | 포함 | 예측 RMSE | 사고 없음 RMSE |", "|---|---|---|---|---|"]
        for d, e in r["incidents"].items():
            L.append(f"| {d} | {e['n']} | {e['coverage'] * 100:.0f} % | {e['rmse_pred']} | {e['rmse_null']} |")
        L.append("")
    (S.RES / "validate_prior.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (S.RES / "validate_prior.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
