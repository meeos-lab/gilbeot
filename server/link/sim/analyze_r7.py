"""도로 형태 R7 분석(사전 고정 docs/sim-preregistration.md 'R7' — 결과를 보기 전에 씀).

  python -X utf8 analyze_r7.py     → results/report_r7.json, report_r7.md
3차로(results/r7_lanes3_*.jsonl, 씨앗 1~24, PC)에서 일률 80 대 기준선·대 단계·단계 대 기준선의 씨앗별 변화율 평균과 부트스트랩 CI,
합계 변화율, 짝지은 윌콕슨 p(앞 두 비교에 홀름 보정), 보조로 전체·심각 상충. 같은 PC 의 4차로 결과(v2_main·fu_pc)를 나란히 둔다.
"""
import json
import statistics
from pathlib import Path

from analyze_m1 import load, B, G, U
from analyze_r6 import contrast

RES = Path(__file__).parent / "results"


def main():
    r7 = {}
    for f in sorted(RES.glob("r7_lanes3_*.jsonl")):
        r7.update(load(f.name))
    l4 = {**{k: v for k, v in load("v2_main.jsonl").items() if k[1] in (B, G)}, **{k: v for k, v in load("fu_pc.jsonl").items() if k[1] == U}}
    seeds = sorted({s for s, _ in r7 if all((s, k) in r7 for k in (B, G, U))})
    out = {"n": len(seeds), "runs": len(r7), "truncated": sum(r7[k]["truncated"] for k in r7), "level": {}, "contrasts": {}}
    for name, runs, ss in (("3차로", r7, seeds), ("4차로", l4, seeds)):
        out["level"][name] = {sc: {k: round(statistics.mean(runs[(s, sc)][k] for s in ss), 1) for k in ("fast", "severe", "conflicts", "queue_km")} for sc in (B, G, U)}
        out["contrasts"][name] = {}
        for key in ("fast", "severe", "conflicts"):
            out["contrasts"][name][key] = {"u80_vs_baseline": contrast(runs, ss, B, U, key), "u80_vs_graded": contrast(runs, ss, G, U, key),
                                           "graded_vs_baseline": contrast(runs, ss, B, G, key)}
        ps = sorted([(out["contrasts"][name]["fast"][c]["p"], c) for c in ("u80_vs_baseline", "u80_vs_graded")])
        out["contrasts"][name]["fast"][ps[0][1]]["p_holm"] = min(1.0, 2 * ps[0][0])
        out["contrasts"][name]["fast"][ps[1][1]]["p_holm"] = min(1.0, max(ps[1][0], 2 * ps[0][0]))
    L = [f"# 도로 형태 R7: 3차로(수요 0.75배) 대 4차로 (씨앗 1~{len(seeds)}, PC, v2 설정)", "",
         f"실행 {out['runs']}회, 잘린 실행 {out['truncated']}회.", "", "수준(씨앗 평균):", "",
         "| 도로 | 방식 | 고속 접근 | 심각 | 전체 | 정체 km |", "|---|---|---|---|---|---|"]
    for name in out["level"]:
        for sc in (B, G, U):
            v = out["level"][name][sc]; L.append(f"| {name} | {sc} | {v['fast']} | {v['severe']} | {v['conflicts']} | {v['queue_km']} |")
    L += ["", "대비(씨앗별 변화율 평균, 부트스트랩 95 % CI; 합계; 윌콕슨 p, 주 지표 두 비교는 홀름 보정):", "",
          "| 지표 | 비교 | 3차로 씨앗별 (CI) | 3차로 합계 | 3차로 p | 4차로 씨앗별 (CI) | 4차로 합계 | 4차로 p | 방향 같음 |", "|---|---|---|---|---|---|---|---|---|"]
    for key in ("fast", "severe", "conflicts"):
        for c in ("u80_vs_baseline", "u80_vs_graded", "graded_vs_baseline"):
            a, b = out["contrasts"]["3차로"][key][c], out["contrasts"]["4차로"][key][c]
            L.append(f"| {key} | {c} | {a['seedwise_pct']:+.1f} ({a['seedwise_ci'][0]:+.1f} ~ {a['seedwise_ci'][1]:+.1f}) | {a['pooled_pct']:+.1f} | {a.get('p_holm', a['p']):.2g} | "
                     f"{b['seedwise_pct']:+.1f} ({b['seedwise_ci'][0]:+.1f} ~ {b['seedwise_ci'][1]:+.1f}) | {b['pooled_pct']:+.1f} | {b.get('p_holm', b['p']):.2g} | {'예' if (a['seedwise_pct'] > 0) == (b['seedwise_pct'] > 0) else '아니오'} |")
    (RES / "report_r7.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (RES / "report_r7.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
