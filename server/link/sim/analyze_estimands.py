"""보조 추정량 분석(심사 대응, 등록 밖 — 이미 본 결과에 대한 추정량 비교).

  python -X utf8 analyze_estimands.py      → results/report_estimands.json, report_estimands.md
같은 짝 비교마다 추정량 네 가지를 나란히 낸다: 씨앗별 변화율 평균(기존), 절대 짝 차이 평균, 호지스–레만, 합계 변화율.
부트스트랩: 비교마다 random.Random("estimands") 로 씨앗을 복원 추출 10,000회, 네 추정량이 같은 재표본을 쓴다(백분위 95 % CI).
검정: 짝지은 윌콕슨 양측(scipy.stats.wilcoxon, 처리−대조). 모두 PC 결과, 맥(results/mac/) 은 쓰지 않는다.
"""
import json
import random
import statistics
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

RES = Path(__file__).parent / "results"
B, G = "official", "official+tago12+relay"
U, NEAR, NONE = G + "-u80", G + "-near", G + "-none"
T12 = "official+tago12"
METRICS = ("fast", "severe", "conflicts")
MNAME = {"fast": "고속 접근 상충", "severe": "심각 상충", "conflicts": "전체 상충"}
NB = 10000
SMALL = 50


def rows(name):
    return [json.loads(x) for x in (RES / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def by(name, scheme):
    return {r["seed"]: r for r in rows(name) if r["scheme"] == scheme}


def label(ov):  # analyze_d1.label 과 같다
    if "relay_delay" in ov:
        return f"연계 지연 {ov['relay_delay']:.0f} s"
    if "loss" in ov:
        return f"연계 손실 {ov['loss'] * 100:.0f} %"
    return f"꼬리 위치 오차 {ov['tail_err']:+,.0f} m"


def hl(d):
    """호지스–레만: 짝 차이 d 의 월시 평균((d_i+d_j)/2, i≤j) 중앙값."""
    d = np.asarray(d, dtype=float)
    i, j = np.triu_indices(len(d))
    return float(np.median((d[i] + d[j]) / 2))


def seedwise(c, t):
    m = c > 0
    return float(np.mean((t[m] - c[m]) / c[m] * 100)) if m.any() else float("nan")


def pooled(c, t):
    return float((t.sum() - c.sum()) / c.sum() * 100) if c.sum() > 0 else float("nan")


def estimate(pairs):
    c = np.array([p[0] for p in pairs], dtype=float)
    t = np.array([p[1] for p in pairs], dtype=float)
    d = t - c
    n = len(pairs)
    pt = {"seedwise_pct": seedwise(c, t), "abs_diff": float(d.mean()), "hl": hl(d), "pooled_pct": pooled(c, t)}
    r = random.Random("estimands")
    bs = {k: [] for k in pt}
    iu, ju = np.triu_indices(n)
    for _ in range(NB):
        idx = np.array([r.randrange(n) for _ in range(n)])
        cs, ts = c[idx], t[idx]
        ds = ts - cs
        bs["seedwise_pct"].append(seedwise(cs, ts))
        bs["abs_diff"].append(float(ds.mean()))
        bs["hl"].append(float(np.median((ds[iu] + ds[ju]) / 2)))
        bs["pooled_pct"].append(pooled(cs, ts))
    out = {"n": n}
    for k, v in pt.items():
        v_bs = sorted(x for x in bs[k] if x == x)
        out[k] = round(v, 1)
        out[k + "_ci"] = [round(v_bs[int(0.025 * len(v_bs))], 1), round(v_bs[int(0.975 * len(v_bs))], 1)]
    try:
        out["p"] = float(wilcoxon(t, c).pvalue)
    except ValueError:  # 짝 차이가 모두 0
        out["p"] = 1.0
    out["worse_share_pct"] = round(float((d > 0).mean()) * 100, 1)
    out["small_ctrl"] = int((c < SMALL).sum())
    out["zero_ctrl"] = int((c == 0).sum())
    out["sum_ctrl"], out["sum_trt"] = int(c.sum()), int(t.sum())
    return out


def compare(ctrl, trt, metric):
    seeds = sorted(set(ctrl) & set(trt))
    return estimate([(ctrl[s][metric], trt[s][metric]) for s in seeds])


def experiments():
    v2 = {sc: by("v2_main.jsonl", sc) for sc in (B, T12, G)}
    fu = {sc: by("fu_pc.jsonl", sc) for sc in (U, NEAR, NONE)}
    rb = {sc: by("rb_comply.jsonl", sc) for sc in (B, G, U)}
    r6 = {sc: by("r6_confirm.jsonl", sc) for sc in (B, G, U)}
    d1 = {}
    for r in rows("d1.jsonl"):
        d1.setdefault(json.dumps(r["ov"], sort_keys=True), {})[r["seed"]] = r
    order = lambda k: (list(json.loads(k))[0], list(json.loads(k).values())[0])
    E = [
        ("v2", "v2 본 실험 (v2_main, 씨앗 1~24)", [
            ("H1 tago12 대 기준선", v2[B], v2[T12]),
            ("H3 tago12+연계(단계) 대 기준선", v2[B], v2[G])]),
        ("fu", "후속 권고 방식 (fu_pc 처리 + v2_main 대조, 씨앗 1~24)", [
            ("H5 일률 80 대 단계", v2[G], fu[U]),
            ("H6 꼬리 근처만 대 단계", v2[G], fu[NEAR]),
            ("H7 권고 없음 대 단계", v2[G], fu[NONE]),
            ("일률 80 대 기준선", v2[B], fu[U])]),
        ("rb1", "강건성 R1 따름 비율 (rb_comply 안, 씨앗 1~24)", [
            ("R1 일률 80 대 단계", rb[G], rb[U]),
            ("R1 일률 80 대 기준선", rb[B], rb[U])]),
        ("r6", "확인 R6 (r6_confirm, 씨앗 101~200)", [
            ("C1 일률 80 대 기준선", r6[B], r6[U]),
            ("C2 일률 80 대 단계", r6[G], r6[U]),
            ("단계 대 기준선", r6[B], r6[G])]),
        ("d1", "탐지·통신 실패 D1 (d1 처리 + v2_main 기준선 / fu_pc 일률 80 기본, 씨앗 1~24)",
         [(f"{label(json.loads(k))} 대 기준선", v2[B], d1[k]) for k in sorted(d1, key=order)]
         + [(f"{label(json.loads(k))} 대 일률 80 기본", fu[U], d1[k]) for k in sorted(d1, key=order)]),
    ]
    return E


def fmt_ci(c, k, unit=""):
    return f"{c[k]:+.1f}{unit} ({c[k + '_ci'][0]:+.1f} ~ {c[k + '_ci'][1]:+.1f})"


def main():
    rep = {"definitions": {}, "experiments": {}}
    defs = [
        ("seedwise_pct", "씨앗별 %", "씨앗마다 (처리−대조)/대조×100 을 구해 평균(대조 0 인 씨앗 제외). 기존 보고의 추정량."),
        ("abs_diff", "절대 차이", "씨앗별 짝 차이(처리−대조, 건)의 평균."),
        ("hl", "HL", "호지스–레만: 짝 차이의 월시 평균((dᵢ+dⱼ)/2, i≤j) 중앙값, 건. 윌콕슨 부호 순위 검정에 대응하는 위치 추정량."),
        ("pooled_pct", "합계 %", "(Σ처리−Σ대조)/Σ대조×100. 대조 건수로 가중한 변화율(노출 가중 합계에 해당)."),
        ("p", "p", "짝지은 윌콕슨 부호 순위 양측(짝 차이), 보정 전."),
        ("worse_share_pct", "나빠진 씨앗", "처리 > 대조인 씨앗 비율(%)."),
        ("small_ctrl", "분모<50", f"대조 값이 {SMALL}건 미만인 씨앗 수(씨앗별 비율이 불안정해지는 작은 분모)."),
    ]
    rep["definitions"] = {k: d for k, _, d in defs}
    rep["bootstrap"] = {"n": NB, "rng": 'random.Random("estimands"), 비교마다 새로 시작', "ci": "백분위 2.5·97.5 %"}
    L = ["# 보조 추정량: 같은 짝 비교의 네 가지 효과 크기", "",
         "심사 대응(등록 밖). 이미 보고한 짝 비교를 추정량만 바꿔 다시 낸다. 모두 PC 결과(맥 results/mac/ 은 섞지 않음). + = 처리가 늘어남(나쁨), − = 줄어듦.", "",
         "추정량 정의:", ""]
    L += [f"- **{h}**: {d}" for _, h, d in defs]
    L += ["", f"95 % CI: 씨앗을 복원 추출하는 부트스트랩 {NB:,}회(비교마다 `random.Random(\"estimands\")`), 네 추정량이 같은 재표본을 쓴다. "
          "수치는 소수 첫째 자리, p 는 유효숫자 두 자리.", "",
          "참고: r6_confirm 에는 잘린 실행(truncated) 9개(씨앗 104·128·149·151·166)가 있고, 기존 analyze_r6.py 와 같이 포함했다.", ""]
    flips = []
    for key, title, comps in experiments():
        ex = rep["experiments"][key] = {"title": title, "metrics": {}}
        for m in METRICS:
            L += [f"## {title} — {MNAME[m]} (`{m}`)", "",
                  "| 비교 | n | 씨앗별 % (CI) | 절대 차이 (CI) | HL (CI) | 합계 % (CI) | p | 나빠진 씨앗 | 분모<50 |",
                  "|---|---|---|---|---|---|---|---|---|"]
            ex["metrics"][m] = {}
            for name, ctrl, trt in comps:
                c = compare(ctrl, trt, m)
                ex["metrics"][m][name] = c
                L.append(f"| {name} | {c['n']} | {fmt_ci(c, 'seedwise_pct')} | {fmt_ci(c, 'abs_diff')} | {fmt_ci(c, 'hl')} | "
                         f"{fmt_ci(c, 'pooled_pct')} | {c['p']:.2g} | {c['worse_share_pct']:.1f} % | {c['small_ctrl']} |")
                if c["seedwise_pct"] * c["pooled_pct"] < 0:
                    flips.append({"experiment": key, "metric": m, "comparison": name,
                                  "seedwise_pct": c["seedwise_pct"], "pooled_pct": c["pooled_pct"]})
            L.append("")
    rep["sign_flips"] = flips
    L += ["## 씨앗별 평균과 합계 변화율의 부호가 다른 비교", "", "(점추정 부호가 서로 반대인 것만, 자동 추출. 0 은 부호 없음으로 봄.)", ""]
    L += [f"- {f['experiment']} · {MNAME[f['metric']]} · {f['comparison']}: 씨앗별 {f['seedwise_pct']:+.1f} %, 합계 {f['pooled_pct']:+.1f} %" for f in flips] or ["- 없음"]
    (RES / "report_estimands.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (RES / "report_estimands.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
