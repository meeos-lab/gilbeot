"""강건성 실험 분석 — 사전 고정 docs/sim-preregistration.md '강건성' → results/report_rb.json, report_rb.md
  python -X utf8 analyze_rb.py
PC: R1 현장 따름(rb_comply), R3 보급 1.5 %·R4 80+꼬리 70·R5 차로 권고 없음(rb_design, 짝은 v2_main·fu_pc), 홀름 4개.
맥: R2 주의 회복 0·35·100 %(mac/rb_attn*), 65 % 는 mac/fu_mac 씨앗 1~8, 홀름 3개.
"""
import json

import analyze as A

RES = A.RES
O, G, U = "official", "official+tago12+relay", "official+tago12+relay-u80"
G15, U15 = "official+tago1.5+relay", "official+tago1.5+relay-u80"
UN, UL = "official+tago12+relay-u80near", "official+tago12+relay-u80nl"
NAME = {O: "기준선", G: "단계 90·70·50", U: "일률 80", G15: "단계(보급 1.5 %)", U15: "일률 80(보급 1.5 %)",
        UN: "80 + 꼬리 1 km 안 70", UL: "일률 80, 차로 권고 없음"}
M3 = ("fast", "conflicts", "severe")


def red(tab, sc, base):
    return {m: A.reduction(tab, sc, base, m) for m in M3}


def main():
    out = {}
    pc = A.by_seed([r for r in A.load("v2_main.jsonl") if r["scheme"] in (O, G, G15)] + A.load("fu_pc.jsonl") + A.load("rb_design.jsonl"))
    cp = A.by_seed(A.load("rb_comply.jsonl"))
    tests = [("R1 현장 따름: 일률 80 < 단계", cp, G, U), ("R3 보급 1.5 %: 일률 80 < 단계", pc, G15, U15),
             ("R4 80+꼬리 70 대 일률 80(양측)", pc, U, UN), ("R5 차로 권고 없음 대 일률 80(양측)", pc, U, UL)]
    ps = [A.wil(t, a, b, "fast") for _, t, a, b in tests]
    adj = A.holm(ps)
    out["pc"] = {"hypotheses": {k: {"p": p, "p_holm": q, "effect": red(t, b, a), "n": len([d for d in t.values() if a in d and b in d])}
                                for (k, t, a, b), p, q in zip(tests, ps, adj)},
                 "comply_vs_official": {sc: red(cp, sc, O) for sc in (G, U)},
                 "design_vs_official": {sc: red(pc, sc, O) for sc in (U, UN, UL, G15, U15)}}
    mac = {}
    for p, f in ((0.0, "mac/rb_attn0.jsonl"), (0.35, "mac/rb_attn0.35.jsonl"), (0.65, "mac/fu_mac.jsonl"), (1.0, "mac/rb_attn1.jsonl")):
        rows = [r for r in A.load(f) if r["scheme"] in (O, G, U) and r["seed"] <= 8]
        if rows:
            t = A.by_seed(rows)
            mac[p] = {"n": len(t), "vs_official": {sc: red(t, sc, O) for sc in (G, U)}, "u80_vs_graded": red(t, U, G), "p": A.wil(t, G, U, "fast")}
    tp = [p for p in mac if p != 0.65]
    for p, q in zip(tp, A.holm([mac[p]["p"] for p in tp])):
        mac[p]["p_holm"] = q
    out["mac_attention"] = {str(k): v for k, v in mac.items()}
    (RES / "report_rb.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    f = lambda r: "" if not r else f"{r['mean']*100:+.1f} % ({r['ci'][0]*100:.1f} ~ {r['ci'][1]*100:.1f})"
    L = ["# 강건성 실험: 일률 80 권고", "", "감소율(+ = 상충이 줄어듦), 씨앗별 평균과 95 % CI.", "", "## PC 가설(홀름 보정, 양측 윌콕슨)", "",
         "| 가설 | 씨앗 | 고속 접근 | 전체 | 심각 | p | 보정 p |", "|---|---|---|---|---|---|---|"]
    for k, h in out["pc"]["hypotheses"].items():
        e = h["effect"]
        L.append(f"| {k} | {h['n']} | {f(e['fast'])} | {f(e['conflicts'])} | {f(e['severe'])} | {h['p']:.2g} | {h['p_holm']:.2g} |")
    L += ["", "## 기준선 대비", "", "| 조건 | 방식 | 고속 접근 | 전체 | 심각 |", "|---|---|---|---|---|"]
    for sc, e in out["pc"]["comply_vs_official"].items():
        L.append(f"| 현장 따름(PC) | {NAME[sc]} | {f(e['fast'])} | {f(e['conflicts'])} | {f(e['severe'])} |")
    for sc, e in out["pc"]["design_vs_official"].items():
        L.append(f"| v2(PC) | {NAME[sc]} | {f(e['fast'])} | {f(e['conflicts'])} | {f(e['severe'])} |")
    L += ["", "## 맥: 주의 회복 비율별(씨앗 1~8)", "", "| 회복 | 단계, 고속 접근 | 일률 80, 고속 접근 | 일률 80, 전체 | 일률 80, 심각 | 일률 80 대 단계, 고속 접근 | 보정 p |",
          "|---|---|---|---|---|---|---|"]
    for p, v in mac.items():
        g, u = v["vs_official"][G], v["vs_official"][U]
        L.append(f"| {p*100:.0f} % | {f(g['fast'])} | {f(u['fast'])} | {f(u['conflicts'])} | {f(u['severe'])} | {f(v['u80_vs_graded']['fast'])} | "
                 f"{'(후속 재현)' if 'p_holm' not in v else format(v['p_holm'], '.2g')} |")
    (RES / "report_rb.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
