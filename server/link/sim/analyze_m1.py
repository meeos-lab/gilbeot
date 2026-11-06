"""추종 모형 점검 M1 분석(사전 고정 docs/sim-preregistration.md 'M1' — 결과를 보기 전에 씀).

  python -X utf8 analyze_m1.py [idm]     → results/report_m1_idm.json, report_m1_idm.md
IDM(results/m1_idm.jsonl, 씨앗 1~24, PC)에서 일률 80 대 기준선·대 단계·단계 대 기준선의 씨앗별 변화율 평균과 부트스트랩 CI,
합계 변화율, 짝지은 윌콕슨 p(앞 두 비교에 홀름 보정), 보조로 전체·심각 상충. 같은 씨앗의 Krauss 결과(v2_main·fu_pc, PC)를 나란히 놓는다.
"""
import json
import statistics
import sys
from pathlib import Path

from analyze_r6 import contrast

RES = Path(__file__).parent / "results"
B, G, U = "official", "official+tago12+relay", "official+tago12+relay-u80"


def load(name):
    runs = {}
    for line in (RES / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line); runs[(d["seed"], d["scheme"])] = d
    return runs


def main(tag="idm"):
    idm = load(f"m1_{tag}.jsonl")
    kr = {**{k: v for k, v in load("v2_main.jsonl").items() if k[1] in (B, G)}, **{k: v for k, v in load("fu_pc.jsonl").items() if k[1] == U}}
    seeds = sorted({s for s, _ in idm if all((s, k) in idm for k in (B, G, U)) and all((s, k) in kr for k in (B, G, U))})
    out = {"n": len(seeds), "seeds": seeds, "runs": len(idm), "level": {}, "contrasts": {}}
    for name, runs in (("IDM", idm), ("Krauss", kr)):
        out["level"][name] = {sc: {k: round(statistics.mean(runs[(s, sc)][k] for s in seeds), 1) for k in ("fast", "severe", "conflicts", "crashes")} for sc in (B, G, U)}
        out["contrasts"][name] = {}
        for key in ("fast", "severe", "conflicts"):
            out["contrasts"][name][key] = {"u80_vs_baseline": contrast(runs, seeds, B, U, key), "u80_vs_graded": contrast(runs, seeds, G, U, key),
                                           "graded_vs_baseline": contrast(runs, seeds, B, G, key)}
        ps = sorted([(out["contrasts"][name]["fast"][c]["p"], c) for c in ("u80_vs_baseline", "u80_vs_graded")])
        holm = {ps[0][1]: min(1.0, 2 * ps[0][0]), ps[1][1]: min(1.0, max(ps[1][0], 2 * ps[0][0]))}
        for c, p in holm.items():
            out["contrasts"][name]["fast"][c]["p_holm"] = p
    L = [f"# 추종 모형 점검 M1: {tag.upper()} 대 Krauss (씨앗 1~{len(seeds)}, PC, v2 설정)", "",
         "수준(씨앗 평균 건수):", "", "| 모형 | 방식 | 고속 접근 | 심각 | 전체 | SUMO 충돌 판정 |", "|---|---|---|---|---|---|"]
    for name in ("IDM", "Krauss"):
        for sc in (B, G, U):
            v = out["level"][name][sc]; L.append(f"| {name} | {sc} | {v['fast']} | {v['severe']} | {v['conflicts']} | {v['crashes']} |")
    L += ["", "대비(씨앗별 변화율 평균, 부트스트랩 95 % CI; 합계 변화율; 윌콕슨 p, 홀름은 주 지표 두 비교):", "",
          "| 지표 | 비교 | IDM 씨앗별 (CI) | IDM 합계 | IDM p | Krauss 씨앗별 (CI) | Krauss 합계 | Krauss p | 방향 같음 |", "|---|---|---|---|---|---|---|---|---|"]
    for key in ("fast", "severe", "conflicts"):
        for c in ("u80_vs_baseline", "u80_vs_graded", "graded_vs_baseline"):
            a, b = out["contrasts"]["IDM"][key][c], out["contrasts"]["Krauss"][key][c]
            pa = a.get("p_holm", a["p"]); pb = b.get("p_holm", b["p"])
            L.append(f"| {key} | {c} | {a['seedwise_pct']:+.1f} ({a['seedwise_ci'][0]:+.1f} ~ {a['seedwise_ci'][1]:+.1f}) | {a['pooled_pct']:+.1f} | {pa:.2g} | "
                     f"{b['seedwise_pct']:+.1f} ({b['seedwise_ci'][0]:+.1f} ~ {b['seedwise_ci'][1]:+.1f}) | {b['pooled_pct']:+.1f} | {pb:.2g} | {'예' if (a['seedwise_pct'] > 0) == (b['seedwise_pct'] > 0) else '아니오'} |")
    (RES / f"report_m1_{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (RES / f"report_m1_{tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "idm")
