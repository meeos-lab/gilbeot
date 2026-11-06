"""탐지·통신 실패 D1 분석(사전 고정 docs/sim-preregistration.md 'D1' — 결과를 보기 전에 씀).

  python -X utf8 analyze_d1.py      → results/report_d1.json, report_d1.md
조건마다 고속 접근 상충의 씨앗별 변화율: 기준선(v2_main 'official') 대비 평균과 부트스트랩 95 % CI,
일률 80 기본(fu_pc, 연계 지연 30 s·손실 0·오차 0) 대비 평균과 CI. 씨앗 1~24, 모두 PC.
"""
import json
import random
import statistics
from pathlib import Path

RES = Path(__file__).parent / "results"
B, U = "official", "official+tago12+relay-u80"


def rows(name):
    return [json.loads(x) for x in (RES / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def label(ov):
    if "relay_delay" in ov:
        return f"연계 지연 {ov['relay_delay']:.0f} s"
    if "loss" in ov:
        return f"연계 손실 {ov['loss'] * 100:.0f} %"
    return f"꼬리 위치 오차 {ov['tail_err']:+,.0f} m"


def ci(pairs, n=10000, key="d1"):
    r = random.Random(key)
    est = lambda smp: statistics.mean((t - c) / c * 100 for c, t in smp if c > 0)
    bs = sorted(est([pairs[r.randrange(len(pairs))] for _ in pairs]) for _ in range(n))
    return round(est(pairs), 1), [round(bs[int(0.025 * n)], 1), round(bs[int(0.975 * n)], 1)]


def main():
    base = {r["seed"]: r for r in rows("v2_main.jsonl") if r["scheme"] == B}
    u80 = {r["seed"]: r for r in rows("fu_pc.jsonl") if r["scheme"] == U}
    conds = {}
    for r in rows("d1.jsonl"):
        conds.setdefault(json.dumps(r["ov"], sort_keys=True), {})[r["seed"]] = r
    seeds = sorted(set(base) & set(u80))
    ref = ci([(base[s]["fast"], u80[s]["fast"]) for s in seeds])
    out = {"n_seeds": len(seeds), "default_vs_baseline": {"mean": ref[0], "ci": ref[1]}, "conds": []}
    L = ["# 탐지·통신 실패 D1 (씨앗 1~24, PC, v2)", "", "변화율: − = 적음(좋음). 일률 80 기본 = 연계 지연 30 s, 손실 0, 꼬리 오차 0.", "",
         f"일률 80 기본 대 기준선: {ref[0]:+.1f} % ({ref[1][0]:+.1f} ~ {ref[1][1]:+.1f})", "",
         "| 조건 | 씨앗 | 대 기준선 | 95 % CI | 대 일률 80 기본 | 95 % CI | 기준선보다 나빠진 씨앗 |", "|---|---|---|---|---|---|---|"]
    order = lambda k: (list(json.loads(k))[0], list(json.loads(k).values())[0])
    for k in sorted(conds, key=order):
        ov, rs = json.loads(k), conds[k]
        ss = [s for s in seeds if s in rs]
        vb = ci([(base[s]["fast"], rs[s]["fast"]) for s in ss])
        vu = ci([(u80[s]["fast"], rs[s]["fast"]) for s in ss])
        worse = sum(1 for s in ss if rs[s]["fast"] > base[s]["fast"]) / len(ss)
        sev = ci([(base[s]["severe"], rs[s]["severe"]) for s in ss])
        out["conds"].append({"ov": ov, "label": label(ov), "n": len(ss), "vs_baseline": {"mean": vb[0], "ci": vb[1]},
                             "vs_u80": {"mean": vu[0], "ci": vu[1]}, "worse_share": round(worse, 3), "severe_vs_baseline": {"mean": sev[0], "ci": sev[1]}})
        L.append(f"| {label(ov)} | {len(ss)} | {vb[0]:+.1f} % | {vb[1][0]:+.1f} ~ {vb[1][1]:+.1f} | {vu[0]:+.1f} % | {vu[1][0]:+.1f} ~ {vu[1][1]:+.1f} | {worse * 100:.0f} % |")
    bad = [c["label"] for c in out["conds"] if c["vs_baseline"]["mean"] > 0]
    L += ["", "기준선보다 나빠진 조건(평균): " + (", ".join(bad) if bad else "없음")]
    # 결과를 본 뒤 추가한 점검(탐색, 등록 밖): 조건 크기와 효과가 단조롭지 않아, 씨앗별 비율이 작은 분모에 끌리는지 본다.
    worse_u80 = sum(1 for s in seeds if u80[s]["fast"] > base[s]["fast"]) / len(seeds)
    L += ["", "## 결과를 본 뒤 추가한 점검(탐색, 등록 밖)", "",
          f"일률 80 기본이 기준선보다 나빠진 씨앗: {worse_u80 * 100:.0f} %. 일률 80 기본 고속 접근이 가장 적은 씨앗: "
          + ", ".join(f"{s}({u80[s]['fast']})" for s in sorted(seeds, key=lambda s: u80[s]["fast"])[:3]), "",
          "| 조건 | 합계 대 기준선 | 합계 대 일률 80 기본 | 대 기본 씨앗별 중앙값 | 대 기본 씨앗별 절대 변화 평균 | 대 기본 최대 |", "|---|---|---|---|---|---|"]
    out["post_hoc"] = {"default_worse_share": round(worse_u80, 3), "conds": []}
    for k in sorted(conds, key=order):
        rs = conds[k]
        ss = [s for s in seeds if s in rs]
        tb, tu, tr = (sum(d[s]["fast"] for s in ss) for d in (base, u80, rs))
        rat = [(rs[s]["fast"] - u80[s]["fast"]) / u80[s]["fast"] * 100 for s in ss if u80[s]["fast"] > 0]
        ph = {"label": label(json.loads(k)), "sum_vs_baseline": round((tr / tb - 1) * 100, 1), "sum_vs_u80": round((tr / tu - 1) * 100, 1),
              "median_vs_u80": round(statistics.median(rat), 1), "mean_abs_vs_u80": round(statistics.mean(abs(x) for x in rat), 1), "max_vs_u80": round(max(rat))}
        out["post_hoc"]["conds"].append(ph)
        L.append(f"| {ph['label']} | {ph['sum_vs_baseline']:+.1f} % | {ph['sum_vs_u80']:+.1f} % | {ph['median_vs_u80']:+.1f} % | {ph['mean_abs_vs_u80']:.1f} % | {ph['max_vs_u80']:+d} % |")
    (RES / "report_d1.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (RES / "report_d1.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
