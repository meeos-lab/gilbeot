"""v2 수정 모형 분석(사전 고정 docs/sim-preregistration.md 'v2') → results/report_v2.json, report_v2.md
  python -X utf8 analyze_v2.py
"""
import json
import statistics

import analyze as A

RES = A.RES


def main():
    rows = A.load("v2_main.jsonl")
    tab = A.by_seed(rows)
    out = {"n_seeds": len(tab), "truncated": sum(r["truncated"] for r in rows), "schemes": {}}
    for sc in ("none", "official", "official_ai", "tago12", "official+tago12", "official+tago1.5+relay", "official+tago12+relay", "tago100"):
        rs = [d[sc] for d in tab.values() if sc in d]
        if not rs:
            continue
        inc = [r["inc_at"] for r in rs if r["inc_at"] is not None]
        out["schemes"][sc] = {
            "n": len(rs), "fast": statistics.mean(r["fast"] for r in rs), "fast1": statistics.mean(r["fast1"] for r in rs),
            "crashes": statistics.mean(r["crashes"] for r in rs), "conflicts": statistics.mean(r["conflicts"] for r in rs), "severe": statistics.mean(r["severe"] for r in rs),
            "kinds": {k: statistics.mean(r["kinds"][k] for r in rs) for k in ("merge", "queue", "approach", "other")}, "queue_km_median": statistics.median(r["queue_km"] for r in rs),
            "queue_over6": sum(r["queue_km"] > 6 for r in rs) / len(rs), "inc_at_median": statistics.median(inc) if inc else None,
            "vs_official": {m: A.reduction(tab, sc, "official", m) for m in ("fast", "fast1", "conflicts", "severe")} if sc != "official" else None,
            "vs_none": A.reduction(tab, sc, "none", "fast") if sc != "none" else None}
    p3 = A.wil(tab, "official", "official+tago12+relay", "fast")
    p1 = A.wil(tab, "official", "official+tago12", "fast")
    adj = A.holm([p3, p1])
    out["hypotheses"] = {"H3": {"p": p3, "p_holm": adj[0], "effect": A.reduction(tab, "official+tago12+relay", "official", "fast")},
                         "H1": {"p": p1, "p_holm": adj[1], "effect": A.reduction(tab, "official+tago12", "official", "fast")}}
    sweep = {}                          # 주의 회복 민감도: 네 점 모두 맥에서(같은 기계끼리만 비교 — 칩이 다르면 결과가 미세하게 달라진다)
    for p in (0.0, 0.35, 0.65, 1.0):
        t = A.by_seed(A.load(f"mac/v2_attn{p}.jsonl"))
        if t:
            sweep[str(p)] = {"n": len(t), "machine": "Mac Studio M5 Max",
                             **{m: A.reduction(t, "official+tago12+relay", "official", m) for m in ("fast", "conflicts", "severe")},
                             "p_fast": A.wil(t, "official", "official+tago12+relay", "fast"),
                             "official_fast": statistics.mean(d["official"]["fast"] for d in t.values() if "official" in d)}
    out["attention_sweep"] = dict(sorted(sweep.items(), key=lambda kv: float(kv[0])))
    (RES / "report_v2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# v2 결과 (씨앗 {out['n_seeds']}개)", "", "| 방식 | 고속 접근 상충 | 기준선 대비 (95 % CI) | 경고 없음 대비 | TTC 1.0 s | 정체 중앙값 | 확정 중앙값 |", "|---|---|---|---|---|---|---|"]
    for sc, e in out["schemes"].items():
        v = (e["vs_official"] or {}).get("fast"); n = e["vs_none"]; f1 = (e["vs_official"] or {}).get("fast1")
        L.append(f"| {sc} | {e['fast']:.0f} | " + (f"{v['mean']*100:+.1f} % ({v['ci'][0]*100:.1f} ~ {v['ci'][1]*100:.1f})" if v else "기준") +
                 " | " + (f"{n['mean']*100:.1f} %" if n else "") + " | " + (f"{f1['mean']*100:.1f} %" if f1 else "") + f" | {e['queue_km_median']:.1f} km | {e['inc_at_median'] or ''} |")
    L += ["", "가설(홀름 보정): " + ", ".join(f"{k} 효과 {h['effect']['mean']*100:.1f} % p {h['p']:.2g} 보정 {h['p_holm']:.2g}" for k, h in out["hypotheses"].items()), "",
          "주의 회복 확률별 넘김 방식 기준선 대비(맥, 씨앗 1~8): " + ", ".join(f"p={k}: 고속 접근 {v['fast']['mean']*100:.1f} % ({v['fast']['ci'][0]*100:.1f}~{v['fast']['ci'][1]*100:.1f}), 전체 {v['conflicts']['mean']*100:.1f} %, 심각 {v['severe']['mean']*100:.1f} %" for k, v in out["attention_sweep"].items())]
    (RES / "report_v2.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
