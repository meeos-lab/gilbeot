"""본 실험·민감도·오탐 결과 → results/report.json, results/report.md (분석 방법은 docs/sim-preregistration.md 5절에 고정).

  python -X utf8 analyze.py
- 짝 비교: 같은 씨앗끼리. 감소율 = 1 - 방식/비교 기준(씨앗마다), 평균과 부트스트랩 95 % 신뢰구간(씨앗 다시 뽑기 10,000회).
- 가설 검정: 짝지은 윌콕슨(양측) — H1·H3·H4. H2(보급률이 오를수록 효과가 커진다)는 순서 가설이라 페이지 추세 검정.
  네 p 값에 홀름 보정, α = 0.05.
- 전역 민감도: 표준화 회귀 계수(SRC) — 감소율을 표준화한 가정들에 회귀.
"""
import json
import random
import statistics
from pathlib import Path

import numpy as np
from scipy.stats import page_trend_test, wilcoxon

RES = Path(__file__).parent / "results"


def load(name):
    p = RES / name
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def by_seed(rows):
    t = {}
    for r in rows:
        t.setdefault(r["seed"], {})[r["scheme"]] = r
    return t


def boot_ci(xs, n=10000, seed=1):
    r = random.Random(seed)
    m = sorted(statistics.mean(r.choices(xs, k=len(xs))) for _ in range(n))
    return m[int(0.025 * n)], m[int(0.975 * n) - 1]


def reduction(tab, scheme, base, metric):
    """씨앗마다 1 - x/base(기준이 0 인 씨앗은 뺀다) → 평균·신뢰구간·합 비율"""
    pairs = [(d[base][metric], d[scheme][metric]) for d in tab.values() if base in d and scheme in d]
    red = [1 - b / a for a, b in pairs if a > 0]
    if not red:
        return None
    lo, hi = boot_ci(red)
    sa, sb = sum(a for a, _ in pairs), sum(b for _, b in pairs)
    return {"n": len(red), "mean": statistics.mean(red), "ci": [lo, hi], "median": statistics.median(red),
            "pooled": 1 - sb / sa if sa else None, "base_mean": sa / len(pairs), "mean_value": sb / len(pairs)}


def wil(tab, a, b, metric):
    xs = [(d[a][metric], d[b][metric]) for d in tab.values() if a in d and b in d]
    if len(xs) < 5 or not any(x - y for x, y in xs):
        return 1.0
    return float(wilcoxon([x for x, _ in xs], [y for _, y in xs]).pvalue)


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = run
    return adj


def src(rows_x, y):
    X = np.array(rows_x, float)
    Y = np.array(y, float)
    keep = X.std(0) > 0
    X = (X[:, keep] - X[:, keep].mean(0)) / X[:, keep].std(0)
    Y = (Y - Y.mean()) / Y.std()
    A = np.column_stack([np.ones(len(Y)), X])
    coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
    pred = A @ coef
    r2 = 1 - ((Y - pred) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()
    out, j = [], 1
    for k in keep:
        out.append(float(coef[j]) if k else 0.0)
        j += bool(k)
    return out, float(r2)


def pct(x):
    return "" if x is None else f"{x * 100:.1f} %"


def main():
    out = {}
    main_rows = load("main.jsonl")
    tab = by_seed(main_rows)
    schemes = [s for s in ("none", "official", "official_ai", "tago1.5", "tago12", "tago50", "tago50-inc", "tago100",
                           "official+tago12", "official+tago50", "official+tago1.5+relay", "official+tago12+relay")
               if any(s in d for d in tab.values())]
    out["n_seeds"] = len(tab)
    out["truncated"] = sum(r["truncated"] for r in main_rows)
    metrics = ["fast", "fast1", "conflicts", "severe", "travel", "crashes", "queue_km"]
    out["schemes"] = {}
    for sc in schemes:
        rs = [d[sc] for d in tab.values() if sc in d]
        e = {m: statistics.mean([r[m] for r in rs if r.get(m) is not None]) for m in metrics if any(r.get(m) is not None for r in rs)}
        e["n"] = len(rs)
        e["kinds"] = {k: statistics.mean(r["kinds"][k] for r in rs) for k in rs[0]["kinds"]}
        inc = [r["inc_at"] for r in rs if r["inc_at"] is not None]
        e["inc_at_median"] = statistics.median(inc) if inc else None
        e["vs_official"] = {m: reduction(tab, sc, "official", m) for m in ("fast", "fast1", "conflicts", "severe")} if sc != "official" else None
        e["vs_none"] = {m: reduction(tab, sc, "none", m) for m in ("fast", "fast1", "conflicts")} if sc != "none" else None
        tv = [d[sc]["travel"] - d["official"]["travel"] for d in tab.values()
              if sc in d and "official" in d and d[sc]["travel"] and d["official"]["travel"]]
        e["travel_vs_official_s"] = statistics.mean(tv) if tv else None
        out["schemes"][sc] = e
    # 가설
    p1 = wil(tab, "official", "official+tago12", "fast")
    lv = ["tago1.5", "tago12", "tago50", "tago100"]
    full = [d for d in tab.values() if all(k in d for k in lv + ["none"]) and d["none"]["fast"] > 0]
    p2 = float(page_trend_test([[1 - d[k]["fast"] / d["none"]["fast"] for k in lv] for d in full]).pvalue) if len(full) >= 3 else 1.0
    p3 = wil(tab, "official", "official+tago12+relay", "fast")
    p4 = wil(tab, "tago50-inc", "tago50", "fast")
    adj = holm([p1, p2, p3, p4])
    out["hypotheses"] = {
        "H1": {"label": "기준선 + Tago 12 % 가 기준선보다 주 지표가 적다", "p": p1, "p_holm": adj[0],
               "effect": reduction(tab, "official+tago12", "official", "fast")},
        "H2": {"label": "보급률이 오를수록(1.5·12·50·100 %) 경고 없음 대비 효과가 커진다", "p": p2, "p_holm": adj[1],
               "effects": {k: reduction(tab, k, "none", "fast") for k in lv}},
        "H3": {"label": "기준선 + Tago 12 % + 공식 채널 넘김이 기준선보다 주 지표가 적다", "p": p3, "p_holm": adj[2],
               "effect": reduction(tab, "official+tago12+relay", "official", "fast")},
        "H4": {"label": "같은 보급률(50 %)에서 꼬리 기준 단계 경고가 사고 지점 경고보다 주 지표가 적다", "p": p4, "p_holm": adj[3],
               "effect": reduction(tab, "tago50", "tago50-inc", "fast")},
    }
    if "official" in schemes and "official+tago12+relay" in schemes:
        diffs = [d["official"]["fast"] - d["official+tago12+relay"]["fast"] for d in tab.values() if "official" in d and "official+tago12+relay" in d]
        lo, hi = boot_ci(diffs)
        base = statistics.mean(d["official"]["fast"] for d in tab.values() if "official" in d)
        out["precision"] = {"half_width": (hi - lo) / 2, "base_mean": base, "ratio": (hi - lo) / 2 / base if base else None}
    sub = {}
    for key, f in (("1차로 막힘", lambda c: c["blocked"] == 1), ("2차로 막힘", lambda c: c["blocked"] == 2), ("비", lambda c: c["rain"] > 0),
                   ("주시태만 30 % 이상", lambda c: c["inatt"] >= 0.3), ("처리 40분 이상", lambda c: c["dur"] >= 2400)):
        t2 = {s: d for s, d in tab.items() if "official" in d and f(d["official"]["cond"])}
        if len(t2) >= 3:
            sub[key] = {"n": len(t2), **{sc: (reduction(t2, sc, "official", "fast") or {}).get("mean")
                                         for sc in ("official+tago12", "official+tago12+relay", "tago100")}}
    out["subgroups"] = sub
    lhs = load("lhs.jsonl")
    if lhs:
        lt = by_seed(lhs)
        keys = ["demand", "dur", "inatt", "comply", "tau", "sigma", "truck", "blocked"]
        out["lhs"] = {"n": len(lt), "keys": keys}
        for sc in ("official+tago12", "official+tago12+relay"):
            xs, ys = [], []
            for d in lt.values():
                if "official" in d and sc in d and d["official"]["fast"] > 0:
                    c = d["official"]["cond"]
                    xs.append([c[k] for k in keys])
                    ys.append(1 - d[sc]["fast"] / d["official"]["fast"])
            if len(ys) > len(keys) + 2:
                coef, r2 = src(xs, ys)
                out["lhs"][sc] = {"src": dict(zip(keys, coef)), "r2": r2, "mean": statistics.mean(ys), "n": len(ys)}
    fa = load("false.jsonl")
    if fa:
        ft = by_seed(fa)
        out["false"] = {}
        for sc in ("tago12", "official+tago12+relay"):
            pr = [(d["none"], d[sc]) for d in ft.values() if "none" in d and sc in d]
            if pr:
                cl = [b["false_cleared"] for _, b in pr if b["false_cleared"] is not None]
                out["false"][sc] = {"n": len(pr),
                                    "travel_s": statistics.mean(b["travel"] - a["travel"] for a, b in pr if a["travel"] and b["travel"]),
                                    "conflicts_add": statistics.mean(b["conflicts"] - a["conflicts"] for a, b in pr),
                                    "fast_add": statistics.mean(b["fast"] - a["fast"] for a, b in pr),
                                    "travel_ci": boot_ci([b["travel"] - a["travel"] for a, b in pr if a["travel"] and b["travel"]]),
                                    "fast_ci": boot_ci([b["fast"] - a["fast"] for a, b in pr]),
                                    "cleared_s_median": statistics.median(cl) if cl else None,
                                    "not_cleared": sum(b["false_cleared"] is None for _, b in pr)}
    for fname, key in (("main_cal.jsonl", "calibrated"), ("audit_numeric.jsonl", "audit_numeric"), ("audit_noattn.jsonl", "audit_noattn")):
        rows_x = load(fname)                             # 리뷰 대응 탐색 분석(사전 고정 밖) — 본 실험과 같은 씨앗끼리
        if rows_x:
            tx = by_seed(rows_x)
            out[key] = {"n_seeds": len(tx), "schemes": {}}
            for sc in sorted({r["scheme"] for r in rows_x}):
                if sc == "official":
                    continue
                out[key]["schemes"][sc] = {m: reduction(tx, sc, "official", m) for m in ("fast", "fast1", "conflicts")}
                out[key]["schemes"][sc]["p_vs_official"] = wil(tx, "official", sc, "fast")
            out[key]["official_mean"] = {m: statistics.mean(d["official"][m] for d in tx.values() if "official" in d) for m in ("fast", "crashes", "queue_km")}
    nar = RES / "narrative.json"                         # 사람이 쓴 머리말(결과를 본 뒤 쓴 해석 문장)
    if nar.exists():
        out.update(json.loads(nar.read_text(encoding="utf-8")))
    (RES / "report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# 결과 요약 (씨앗 {out['n_seeds']}개, 정체가 도로 끝까지 찬 실행 {out['truncated']}회)", "",
         "## 주 지표: 고속 접근 상충(TTC < 1.5 s, 속도 차 30 km/h 이상)", "",
         "| 방식 | 평균(쌍) | 기준선 대비 감소: 씨앗 평균 (95 % CI) | 합 비율 | TTC < 1.0 s 기준 | 통행 시간 차(s) | 확정 중앙값(s) |",
         "|---|---|---|---|---|---|---|"]
    for sc, e in out["schemes"].items():
        v = e["vs_official"] or {}
        f, f1 = v.get("fast"), v.get("fast1")
        ci = f"{f['mean'] * 100:+.1f} % ({f['ci'][0] * 100:.1f} ~ {f['ci'][1] * 100:.1f})" if f else "기준선"
        tv = "" if e["travel_vs_official_s"] is None else f"{e['travel_vs_official_s']:+.0f}"
        L.append(f"| {sc} | {e['fast']:.0f} | {ci} | {pct(f['pooled']) if f else ''} | {pct(f1['mean']) if f1 else ''} | {tv} | {e['inc_at_median'] or ''} |")
    L += ["", "## 가설 (홀름 보정, α = 0.05)", ""]
    for k, h in out["hypotheses"].items():
        L.append(f"- {k} {h['label']}: p = {h['p']:.2g}, 보정 p = {h['p_holm']:.2g}")
    if "precision" in out:
        L += ["", f"정밀도: 기준선 대비 차이의 95 % 반폭 / 기준선 평균 = {pct(out['precision']['ratio'])} (목표 5 % 이내)"]
    if out.get("subgroups"):
        L += ["", "## 하위 집단(보고만): 기준선 대비 주 지표 감소", "", "| 집단 | 씨앗 | 기준선+Tago12 | +넘김 | Tago 100 % |", "|---|---|---|---|---|"]
        for k, s in out["subgroups"].items():
            L.append(f"| {k} | {s['n']} | {pct(s.get('official+tago12'))} | {pct(s.get('official+tago12+relay'))} | {pct(s.get('tago100'))} |")
    if out.get("lhs"):
        L += ["", f"## 전역 민감도 (라틴 하이퍼큐브 {out['lhs']['n']}표본, 표준화 회귀 계수)", ""]
        for sc in ("official+tago12", "official+tago12+relay"):
            if sc in out["lhs"]:
                d = out["lhs"][sc]
                L.append(f"- {sc}: 평균 감소 {pct(d['mean'])}, R² {d['r2']:.2f}, " + ", ".join(f"{k} {v:+.2f}" for k, v in sorted(d["src"].items(), key=lambda kv: -abs(kv[1]))))
    if out.get("false"):
        L += ["", "## 오탐 비용(사고 없이 잘못 확정)", ""]
        for sc, d in out["false"].items():
            L.append(f"- {sc}: 통행 시간 {d['travel_s']:+.1f} s (95 % CI {d['travel_ci'][0]:+.1f} ~ {d['travel_ci'][1]:+.1f}), 상충 {d['conflicts_add']:+.1f}, "
                     f"고속 접근 {d['fast_add']:+.1f} (95 % CI {d['fast_ci'][0]:+.1f} ~ {d['fast_ci'][1]:+.1f}), 해제 중앙값 {d['cleared_s_median']} s, 해제 안 됨 {d['not_cleared']}/{d['n']}")
    (RES / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
