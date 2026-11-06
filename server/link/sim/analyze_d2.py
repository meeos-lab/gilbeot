"""결합 실패 D2 분석(사전 고정 docs/sim-preregistration.md 'D2' — 결과를 보기 전에 씀).

  python -X utf8 analyze_d2.py      → results/report_d2.json, report_d2.md
조건(중간 결합·나쁜 결합)마다 고속 접근 상충의 기준선(v2_main 'official') 대비·일률 80 기본(fu_pc) 대비
씨앗별 변화율 평균과 부트스트랩 95 % CI, 합계 변화율과 CI, 절대 짝 차이 평균과 CI, 나빠진 씨앗 비율, 심각 상충. 씨앗 1~24, 모두 PC.
"""
import json
import random
import statistics
from pathlib import Path

from analyze_d1 import B, U, rows

RES = Path(__file__).parent / "results"


def label(ov):
    return f"지연 {ov['relay_delay']:.0f} s + 손실 {ov['loss'] * 100:.0f} % + 꼬리 오차 {ov['tail_err']:+,.0f} m"


def est(pairs, n=10000, key="d2"):
    """(대조, 처리) 짝 → 씨앗별 %·합계 %·절대 차이의 추정값과 부트스트랩 CI"""
    r = random.Random(key)
    f_seed = lambda smp: statistics.mean((t - c) / c * 100 for c, t in smp if c > 0)
    f_pool = lambda smp: (sum(t for _, t in smp) - sum(c for c, _ in smp)) / sum(c for c, _ in smp) * 100
    f_abs = lambda smp: statistics.mean(t - c for c, t in smp)
    bs = {k: [] for k in ("seed", "pool", "abs")}
    for _ in range(n):
        smp = [pairs[r.randrange(len(pairs))] for _ in pairs]
        bs["seed"].append(f_seed(smp)); bs["pool"].append(f_pool(smp)); bs["abs"].append(f_abs(smp))
    q = lambda v: [round(sorted(v)[int(0.025 * n)], 1), round(sorted(v)[int(0.975 * n)], 1)]
    return {"seedwise": round(f_seed(pairs), 1), "seedwise_ci": q(bs["seed"]), "pooled": round(f_pool(pairs), 1), "pooled_ci": q(bs["pool"]),
            "abs": round(f_abs(pairs), 1), "abs_ci": q(bs["abs"])}


def main():
    base = {r["seed"]: r for r in rows("v2_main.jsonl") if r["scheme"] == B}
    u80 = {r["seed"]: r for r in rows("fu_pc.jsonl") if r["scheme"] == U}
    conds = {}
    for r in rows("d2.jsonl"):
        conds.setdefault(json.dumps(r["ov"], sort_keys=True), {})[r["seed"]] = r
    seeds = sorted(set(base) & set(u80))
    out = {"n_seeds": len(seeds), "u80_default_vs_baseline": est([(base[s]["fast"], u80[s]["fast"]) for s in seeds]), "conds": []}
    fmt = lambda e: f"{e['seedwise']:+.1f} % ({e['seedwise_ci'][0]:+.1f} ~ {e['seedwise_ci'][1]:+.1f}) | {e['pooled']:+.1f} % ({e['pooled_ci'][0]:+.1f} ~ {e['pooled_ci'][1]:+.1f}) | {e['abs']:+.1f} ({e['abs_ci'][0]:+.1f} ~ {e['abs_ci'][1]:+.1f})"
    L = ["# 결합 실패 D2 (씨앗 1~24, PC, v2)", "", "변화율: − = 적음(좋음). 씨앗별 = 씨앗별 변화율 평균, 합계 = Σ처리/Σ대조 − 1, 절대 = 처리−대조 건수 평균. 괄호는 부트스트랩 95 % CI.", "",
         f"일률 80 기본 대 기준선: {fmt(out['u80_default_vs_baseline'])}", "",
         "| 조건 | 씨앗 | 대 기준선 씨앗별 | 합계 | 절대 | 대 일률 80 기본 씨앗별 | 합계 | 절대 | 기준선보다 나빠진 씨앗 | 심각 대 기준선 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(conds, key=lambda k: json.loads(k)["relay_delay"]):
        ov, rs = json.loads(k), conds[k]
        ss = [s for s in seeds if s in rs]
        vb = est([(base[s]["fast"], rs[s]["fast"]) for s in ss])
        vu = est([(u80[s]["fast"], rs[s]["fast"]) for s in ss])
        sev = est([(base[s]["severe"], rs[s]["severe"]) for s in ss])
        worse = sum(1 for s in ss if rs[s]["fast"] > base[s]["fast"]) / len(ss)
        out["conds"].append({"ov": ov, "label": label(ov), "n": len(ss), "vs_baseline": vb, "vs_u80": vu, "severe_vs_baseline": sev, "worse_share": round(worse, 3)})
        L.append(f"| {label(ov)} | {len(ss)} | {fmt(vb)} | {fmt(vu)} | {worse * 100:.0f} % | {sev['seedwise']:+.1f} % ({sev['seedwise_ci'][0]:+.1f} ~ {sev['seedwise_ci'][1]:+.1f}) |")
    bad = [c["label"] for c in out["conds"] if c["vs_baseline"]["seedwise"] > 0]
    L += ["", "기준선보다 나빠진 조건(씨앗별 평균 > 0): " + (", ".join(bad) if bad else "없음")]
    (RES / "report_d2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (RES / "report_d2.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
