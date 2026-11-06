"""확인 실험 R6 분석(사전 고정 docs/sim-preregistration.md 'R6' — 결과를 보기 전에 씀).

  python -X utf8 analyze_r6.py      → results/report_r6.json, report_r6.md
C1 일률 80 < 기준선, C2 일률 80 < 단계: 짝지은 윌콕슨 양측, 두 가설 홀름 보정.
효과: 씨앗별 변화율 평균(부트스트랩 10,000회 95 % CI), 합계 변화율(같은 부트스트랩), 짝 차이 중앙값, 나빠진 씨앗 비율.
탐색: TTC 문턱 × 속도 차 문턱 25칸의 씨앗별 변화율 평균.
"""
import json
import random
import statistics
from pathlib import Path

from scipy.stats import wilcoxon

RES = Path(__file__).parent / "results"
B, G, U = "official", "official+tago12+relay", "official+tago12+relay-u80"
TT = (0.75, 1.0, 1.5, 2.0, 3.0)
DV = (0, 10, 20, 30, 40)


def load():
    runs = {}
    for line in (RES / "r6_confirm.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        runs[(d["seed"], d["scheme"])] = d
    seeds = sorted({s for s, _ in runs if all((s, k) in runs for k in (B, G, U))})
    return runs, seeds


def boot(pairs, n=10000):
    r = random.Random("r6")
    seedwise, pooled = [], []
    for _ in range(n):
        smp = [pairs[r.randrange(len(pairs))] for _ in pairs]
        seedwise.append(statistics.mean((t - c) / c * 100 for c, t in smp if c > 0))
        pooled.append((sum(t for _, t in smp) - sum(c for c, _ in smp)) / sum(c for c, _ in smp) * 100)
    q = lambda v: (round(sorted(v)[int(0.025 * n)], 1), round(sorted(v)[int(0.975 * n)], 1))
    return q(seedwise), q(pooled)


def contrast(runs, seeds, ctrl, trt, key="fast"):
    pairs = [(runs[(s, ctrl)][key], runs[(s, trt)][key]) for s in seeds]
    ci_s, ci_p = boot(pairs)
    p = wilcoxon([t for _, t in pairs], [c for c, _ in pairs]).pvalue
    return {"n": len(pairs), "zero_ctrl": sum(1 for c, _ in pairs if c == 0),
            "seedwise_pct": round(statistics.mean((t - c) / c * 100 for c, t in pairs if c > 0), 1), "seedwise_ci": ci_s,
            "pooled_pct": round((sum(t for _, t in pairs) - sum(c for c, _ in pairs)) / sum(c for c, _ in pairs) * 100, 1), "pooled_ci": ci_p,
            "median_diff": statistics.median(t - c for c, t in pairs), "worse_share": round(sum(1 for c, t in pairs if t > c) / len(pairs), 3),
            "p": p}


def surface(runs, seeds, ctrl, trt):
    out = {}
    for i, th in enumerate(TT, 1):
        for d in DV:
            cnt = lambda r: sum(1 for p in r["pairs"] if p[0] < th and p[i] >= d - 1e-6)
            vals = [(cnt(runs[(s, ctrl)]), cnt(runs[(s, trt)])) for s in seeds]
            ok = [(c, t) for c, t in vals if c > 0]
            out[f"{th}|{d}"] = round(statistics.mean((t - c) / c * 100 for c, t in ok), 1) if ok else None
    return out


def main():
    runs, seeds = load()
    rep = {"seeds": [seeds[0], seeds[-1]], "n": len(seeds), "runs": len(runs)}
    c1, c2 = contrast(runs, seeds, B, U), contrast(runs, seeds, G, U)
    ps = sorted([("C1", c1["p"]), ("C2", c2["p"])], key=lambda x: x[1])
    adj, prev = {}, 0.0
    for i, (h, p) in enumerate(ps):
        prev = max(prev, min(1.0, p * (len(ps) - i))); adj[h] = prev
    c1["p_holm"], c2["p_holm"] = adj["C1"], adj["C2"]
    rep["C1_u80_vs_baseline"], rep["C2_u80_vs_graded"] = c1, c2
    rep["aux"] = {f"{name}_{k}": contrast(runs, seeds, ctrl, U, k) for name, ctrl in (("vs_baseline", B), ("vs_graded", G)) for k in ("conflicts", "severe")}
    rep["graded_vs_baseline"] = contrast(runs, seeds, B, G)
    rep["surface"] = {"u80_vs_baseline": surface(runs, seeds, B, U), "u80_vs_graded": surface(runs, seeds, G, U)}
    rep["per_seed"] = {s: {k: runs[(s, k)]["fast"] for k in (B, G, U)} for s in seeds}
    (RES / "report_r6.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    f = lambda c: (f"씨앗별 {c['seedwise_pct']:+.1f} % ({c['seedwise_ci'][0]:+.1f} ~ {c['seedwise_ci'][1]:+.1f}), 합계 {c['pooled_pct']:+.1f} % "
                   f"({c['pooled_ci'][0]:+.1f} ~ {c['pooled_ci'][1]:+.1f}), 짝 차이 중앙값 {c['median_diff']:+g}, 나빠진 씨앗 {c['worse_share'] * 100:.0f} %, "
                   f"p {c['p']:.2g}" + (f", 보정 p {c['p_holm']:.2g}" if "p_holm" in c else ""))
    L = [f"# 확인 실험 R6 (새 씨앗 {seeds[0]}~{seeds[-1]}, n = {len(seeds)})", "", "변화율: + = 늘어남(나쁨), − = 줄어듦.", "",
         f"- C1 일률 80 대 기준선, 고속 접근: {f(c1)}", f"- C2 일률 80 대 단계, 고속 접근: {f(c2)}",
         f"- 참고: 단계 대 기준선, 고속 접근: {f(rep['graded_vs_baseline'])}", ""]
    for k, c in rep["aux"].items():
        L.append(f"- 보조 {k}: {f(c)}")
    for name, sf in rep["surface"].items():
        L += ["", f"## 문턱 25칸: {name} (씨앗별 변화율 평균 %)", "", "| TTC \\ 속도 차 | " + " | ".join(f"≥{d}" for d in DV) + " |", "|---" * (len(DV) + 1) + "|"]
        for th in TT:
            L.append(f"| < {th} s | " + " | ".join("" if sf[f"{th}|{d}"] is None else f"{sf[f'{th}|{d}']:+.1f}" for d in DV) + " |")
    (RES / "report_r6.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
