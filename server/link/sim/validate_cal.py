"""검증 V2: 다른 사고로 사고 규모 분포를 보정한 뒤 시험 사고 예측(사전 고정 docs/sim-preregistration.md '검증 V2').

  python -X utf8 validate_cal.py      → results/validate_cal.json, .md
보정 자료 = 경부선 '정체를 만든 사고'(results/evidence.json) 중 시험 사고 4건을 뺀 사고의 사고 콘존 첫 시간 속도비 r0 와 정체 지속 시간(시간 수).
시뮬레이션의 같은 두 값 = 시험 사고 위치의 재생 격자 실행에서 사고 콘존·사고 시각(07시)부터 같은 규칙으로 잰 값.
격자 조합 10개의 가중치를 단체(simplex)에서 무작위 탐색해 두 값의 5개 분위(10·30·50·70·90) 차 제곱합이 가장 작은 것을 고른다.
"""
import json
import random
import statistics
from pathlib import Path

import tago_sim as S
from replay import zone_speed
from validate_prior import OBS, validate

RES = S.RES
TEST = {"2023-07-04", "2023-11-03", "2025-01-09", "2025-04-14"}
QS = (0.1, 0.3, 0.5, 0.7, 0.9)
COMBOS = [(b, m) for b in (1, 2) for m in (20, 40, 60, 90, 120)]


def quant(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))]


def wquant(pairs, q):
    pairs = sorted(pairs)
    tot, acc = sum(w for _, w in pairs), 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * tot - 1e-12:
            return v
    return pairs[-1][0]


def incident_zone(o):
    for z, e in o["zones"].items():
        if e["to_km"] < o["km"] <= e["from_km"]:
            return z
    return None


def main():
    ev = json.loads((RES / "evidence.json").read_text(encoding="utf-8"))
    field = [r for r in ev["rows"] if r.get("impact") and r["t"][:10] not in TEST and r["r0"][0] is not None]
    f_r0 = [r["r0"][0] for r in field]
    f_dur = [r["dur_h"] for r in field]
    fq = [quant(f_r0, q) for q in QS], [quant(f_dur, q) for q in QS]

    rows = [json.loads(x) for x in (RES / "replay_v2.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    base = [r for r in rows if r["day"] == "base"]
    sims = {c: [] for c in COMBOS}      # 조합 → [(r0, dur)]
    for r in rows:
        if r["day"] == "base" or r["day"] not in OBS:
            continue
        o = OBS[r["day"]]; z = incident_zone(o)
        if not z:
            continue
        ratios = []
        for h in (7, 8, 9, 10):
            bv = [v for v in (zone_speed(b["det"], o["km"], o["zones"][z], h) for b in base) if v]
            v = zone_speed(r["det"], o["km"], o["zones"][z], h)
            ratios.append(v / statistics.mean(bv) if (v and bv) else None)
        if ratios[0] is None:
            continue
        dur = 0
        for x in ratios:
            if x is not None and x < 0.7:
                dur += 1
            else:
                break
        sims[(r["blocked"], r["dur_min"])].append((ratios[0], dur))

    def loss(w):
        p0 = [(x[0], w[i] / len(sims[c])) for i, c in enumerate(COMBOS) for x in sims[c] if sims[c]]
        p1 = [(x[1], w[i] / len(sims[c])) for i, c in enumerate(COMBOS) for x in sims[c] if sims[c]]
        a = sum((wquant(p0, q) - fq[0][k]) ** 2 for k, q in enumerate(QS))
        b = sum(((wquant(p1, q) - fq[1][k]) / 4) ** 2 for k, q in enumerate(QS))   # 지속 시간(0~4)을 비율 척도로
        return a + b

    rnd = random.Random("v2cal")
    best, bw = 9e9, None
    for _ in range(20000):
        g = [rnd.gammavariate(0.5, 1) for _ in COMBOS]
        t = sum(g); w = [x / t for x in g]
        L = loss(w)
        if L < best:
            best, bw = L, w
    W = {c: bw[i] for i, c in enumerate(COMBOS)}
    res = validate("_v2", lambda b, m: W.get((b, m), 0.0))
    rep = {"field_n": len(field), "field_q_r0": fq[0], "field_q_dur": fq[1], "loss": best,
           "weights": {f"{b}차로 {m}분": round(w, 3) for (b, m), w in W.items()}, "validation": res}
    (RES / "validate_cal.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    s = res["summary"]
    L = ["# 검증 V2: 다른 사고로 보정한 뒤 시험 사고 예측(v2)", "",
         f"보정 자료: 정체를 만든 경부선 사고 {len(field)}건(시험 4건 제외). r0 분위 {[round(x, 2) for x in fq[0]]}, 지속 시간 분위 {fq[1]}",
         f"보정 가중치: " + ", ".join(f"{k} {v:.2f}" for k, v in rep["weights"].items() if v >= 0.01), "",
         f"시험: {s['n']}칸, 80 % 구간 포함 {s['coverage'] * 100:.0f} %, 예측 평균 RMSE {s['rmse_pred']} (사고 없음 {s['rmse_null']}), 치우침 {s['bias']:+}", "",
         "| 사고 | 칸 | 포함 | 예측 RMSE | 사고 없음 RMSE |", "|---|---|---|---|---|"]
    L += [f"| {d} | {e['n']} | {e['coverage'] * 100:.0f} % | {e['rmse_pred']} | {e['rmse_null']} |" for d, e in res["incidents"].items()]
    (RES / "validate_cal.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
