"""운영 보정 확인 C3 분석(사전 고정 docs/sim-preregistration.md 'C3' — 결과를 보기 전에 씀).

  python -X utf8 analyze_sevcal.py [mac]   → results/report_sevcal_mac.json, report_sevcal_mac.md
사고 규모(막힌 차로·처리 시간)를 V2 보정 분포에서 뽑은 씨앗 1~24(맥, 상류 30 km)에서 일률 80 대 기준선·대 단계·단계 대 기준선의
씨앗별 변화율 평균과 부트스트랩 CI, 합계 변화율, 짝지은 윌콕슨 p(앞 두 비교에 홀름 보정), 보조로 전체·심각 상충.
같은 기계의 기본 분포 결과(results/mac/fu_mac.jsonl, 씨앗 1~12, 상류 20 km)를 참고로 나란히 둔다(기계를 섞지 않음).
"""
import collections
import json
import statistics
import sys
from pathlib import Path

from analyze_r6 import contrast

RES = Path(__file__).parent / "results"
B, G, U = "official", "official+tago12+relay", "official+tago12+relay-u80"


def load(path):
    runs = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line); runs[(d["seed"], d["scheme"])] = d
    return runs


def holm2(block):
    ps = sorted([(block[c]["p"], c) for c in ("u80_vs_baseline", "u80_vs_graded")])
    block[ps[0][1]]["p_holm"] = min(1.0, 2 * ps[0][0]); block[ps[1][1]]["p_holm"] = min(1.0, max(ps[1][0], 2 * ps[0][0]))


def main(tag="mac"):
    cal = load(RES / "mac" / f"sev_cal_{tag}.jsonl")
    ref = load(RES / "mac" / "fu_mac.jsonl")
    seeds = sorted({s for s, _ in cal if all((s, k) in cal for k in (B, G, U))})
    rseeds = sorted({s for s, _ in ref if all((s, k) in ref for k in (B, G, U))})
    conds = [cal[(s, B)]["cond"] for s in seeds]
    out = {"n": len(seeds), "runs": len(cal), "truncated": sum(cal[k]["truncated"] for k in cal),
           "blocked_share": dict(collections.Counter(c["blocked"] for c in conds)),
           "dur_min": sorted(c["dur"] // 60 for c in conds), "ref_n": len(rseeds),
           "level": {}, "contrasts": {}}
    for name, runs, ss in (("보정 분포(30 km)", cal, seeds), ("기본 분포(20 km, 참고)", ref, rseeds)):
        out["level"][name] = {sc: {k: round(statistics.mean(runs[(s, sc)][k] for s in ss), 1) for k in ("fast", "severe", "conflicts", "queue_km")} for sc in (B, G, U)}
        out["contrasts"][name] = {}
        for key in ("fast", "severe", "conflicts"):
            out["contrasts"][name][key] = {"u80_vs_baseline": contrast(runs, ss, B, U, key), "u80_vs_graded": contrast(runs, ss, G, U, key),
                                           "graded_vs_baseline": contrast(runs, ss, B, G, key)}
        holm2(out["contrasts"][name]["fast"])
    L = [f"# 운영 보정 확인 C3 (맥, 씨앗 1~{len(seeds)}, 사고 규모 = V2 보정 분포, 상류 30 km)", "",
         f"실행 {out['runs']}회, 잘린 실행 {out['truncated']}회. 막힌 차로 분포 {out['blocked_share']}, 처리 시간(분) {out['dur_min']}.", "",
         "수준(씨앗 평균):", "", "| 분포 | 방식 | 고속 접근 | 심각 | 전체 | 정체 km |", "|---|---|---|---|---|---|"]
    for name in out["level"]:
        for sc in (B, G, U):
            v = out["level"][name][sc]; L.append(f"| {name} | {sc} | {v['fast']} | {v['severe']} | {v['conflicts']} | {v['queue_km']} |")
    L += ["", "대비(씨앗별 변화율 평균, 부트스트랩 95 % CI; 합계 변화율; 윌콕슨 p, 주 지표 두 비교는 홀름 보정):", "",
          "| 분포 | 지표 | 비교 | 씨앗별 (CI) | 합계 | p | 나빠진 씨앗 |", "|---|---|---|---|---|---|---|"]
    for name in out["contrasts"]:
        for key in ("fast", "severe", "conflicts"):
            for c in ("u80_vs_baseline", "u80_vs_graded", "graded_vs_baseline"):
                a = out["contrasts"][name][key][c]
                L.append(f"| {name} | {key} | {c} | {a['seedwise_pct']:+.1f} ({a['seedwise_ci'][0]:+.1f} ~ {a['seedwise_ci'][1]:+.1f}) | {a['pooled_pct']:+.1f} | {a.get('p_holm', a['p']):.2g} | {a['worse_share'] * 100:.0f} % |")
    (RES / f"report_sevcal_{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (RES / f"report_sevcal_{tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mac")
