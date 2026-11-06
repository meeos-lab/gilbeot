"""E1 공식 안내 지연의 실측 분포(분석 부분) — 등록: docs/sim-preregistration.md '## 관점 확장 E1~E8' 의 E1.
  python -X utf8 analyze_e1_delay.py
  → results/report_e1_delay.json, results/report_e1_delay.md, data/its_registration_delay.json

맞춤은 B·B 확장과 같은 코드·같은 규칙을 그대로 재사용한다(창만 매개변수):
- 경부선: surrogate_crash.load_its()/load_db(), ITS 방향 → DB 방향(같은 진행 방향), ±창 안 가장 가까운 시각.
- 전국: surrogate_crash_national.parse_its()/load_db_all()/ROUTE_MAP, 노선명 후보 안 ±창 가장 가까운 시각
  (동률은 (|시차|, 노선, 이정) 순, B 확장과 같음). 등록문의 770쌍 = B 확장의 'matched'(END 없는 노선으로 빠지기 전) 전체.
지연(분) = ITS 돌발일시 − DB 사고일시. 양수 = ITS 등록이 DB 시각보다 늦다.
통계: 중앙값·사분위(Q1·Q3, 선형 보간)·평균·13분(779 s) 초과 비율·음수 비율, 1분 구간 히스토그램.
민감도: 창 ±30분, 같은 통계.
모형 입력: 경부선 ±10분 쌍의 지연(초, 음수는 0) → data/its_registration_delay.json.
"""
import datetime as dt
import json
import math
import statistics
from collections import defaultdict

import surrogate_crash as B
import surrogate_crash_national as N

RES, DATA = B.RES, B.DATA
OFFICIAL_S = 779.0
WINDOWS = (10.0, 30.0)


def match_gyeongbu(win_min):
    db = B.load_db()
    its = B.load_its()
    db_by_dir = {d: [a for a in db if a["dir"] == d] for d in ("부산", "서울")}
    pairs = []
    for e in its:
        cands = [a for a in db_by_dir[e["db_dir"]] if abs((a["t"] - e["start"]).total_seconds()) <= win_min * 60]
        if not cands:
            continue
        a = min(cands, key=lambda a: abs((a["t"] - e["start"]).total_seconds()))
        pairs.append({"its_start": e["start"].isoformat(), "db_t": a["t"].isoformat(), "km": a["km"], "dir": a["dir"],
                      "n_lanes": e["n_lanes"], "dur_min": e["dur_min"],
                      "delay_min": (e["start"] - a["t"]).total_seconds() / 60})
    return pairs, len(its)


def match_national(win_min):
    its_all, _ = N.parse_its(False)
    db = N.load_db_all()
    db_by_route = defaultdict(list)
    for a in db:
        db_by_route[a["route"]].append(a)
    eligible = [r for r in its_all if r["end"] and r["dur_min"] != "" and int(r["n_lanes"]) >= 1 and int(r["ramp"]) == 0]
    pairs = []
    for e in eligible:
        start = dt.datetime.fromisoformat(e["start"])
        cr = N.ROUTE_MAP.get((e["road_no"], e["road_name"]))
        if not cr:
            continue
        cands = [a for rt in cr for a in db_by_route.get(rt, []) if abs((a["t"] - start).total_seconds()) <= win_min * 60]
        if not cands:
            continue
        a = min(cands, key=lambda a: (abs((a["t"] - start).total_seconds()), a["route"], a["km"]))
        pairs.append({"its_start": e["start"], "its_road": f"{e['road_no']} {e['road_name']}", "db_route": a["route"],
                      "db_t": a["t"].isoformat(), "km": a["km"], "dir": a["dir"], "in_END": a["route"] in N.END,
                      "delay_min": (start - a["t"]).total_seconds() / 60})
    return pairs, len(eligible)


def quant(s, q):
    s = sorted(s)
    k = (len(s) - 1) * q
    i = int(math.floor(k))
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


def stats(vals, win_min):
    n = len(vals)
    lo = -int(win_min)
    hist = []
    for b in range(lo, int(win_min)):
        c = sum(b <= v < b + 1 for v in vals) + (sum(v == win_min for v in vals) if b == int(win_min) - 1 else 0)
        hist.append({"lo": b, "hi": b + 1, "n": c})
    return {"n": n, "median": statistics.median(vals), "q1": quant(vals, 0.25), "q3": quant(vals, 0.75),
            "mean": statistics.fmean(vals), "sd": statistics.stdev(vals) if n > 1 else None,
            "min": min(vals), "max": max(vals),
            "share_gt_13min": sum(v * 60 > OFFICIAL_S for v in vals) / n,
            "share_negative": sum(v < 0 for v in vals) / n,
            "share_zero_exact": sum(v == 0 for v in vals) / n,
            "share_abs_gt_10min": sum(abs(v) > 10 for v in vals) / n,
            "hist_1min": hist}


def main():
    out = {"prereg": "docs/sim-preregistration.md '## 관점 확장 E1~E8' E1 (분석 부분)",
           "definition": "delay_min = ITS 돌발일시 − 사고 DB 사고일시 (분). 양수 = ITS 가 늦다.",
           "official_delay_s": OFFICIAL_S, "sets": {}}
    keep = {}
    for w in WINDOWS:
        gp, g_n = match_gyeongbu(w)
        np_, n_n = match_national(w)
        keep[w] = (gp, np_)
        out["sets"][f"pm{int(w)}"] = {
            "window_min": w,
            "gyeongbu": {"its_eligible": g_n, **stats([p["delay_min"] for p in gp], w)},
            "national": {"its_eligible": n_n, **stats([p["delay_min"] for p in np_], w),
                         "n_route_in_END": sum(p["in_END"] for p in np_)},
            "national_END_only": stats([p["delay_min"] for p in np_ if p["in_END"]], w),
        }

    # 검산: B·B 확장의 쌍과 같은지(±10)
    gp10, np10 = keep[10.0]
    rb = json.loads((RES / "report_b.json").read_text(encoding="utf-8"))
    rbn = json.loads((RES / "report_b_national.json").read_text(encoding="utf-8"))
    b_lags = sorted(-r["lag_min"] for r in rb["rows"])
    bn_lags = sorted(-r["lag_min"] for r in rbn["rows"])
    out["check"] = {
        "gyeongbu_n_vs_report_b": [len(gp10), rb["matching"]["matched"]],
        "gyeongbu_delays_equal_report_b": len(b_lags) == len(gp10) and all(
            abs(a - b) < 1e-9 for a, b in zip(b_lags, sorted(p["delay_min"] for p in gp10))),
        "national_n_vs_report_b_national": [len(np10), rbn["matching"]["matched"]],
        "national_END_delays_equal_report_b_national_rows": len(bn_lags) == sum(p["in_END"] for p in np10) and all(
            abs(a - b) < 1e-9 for a, b in zip(bn_lags, sorted(p["delay_min"] for p in np10 if p["in_END"]))),
    }
    # ±30 에서 새로 들어온 쌍(±10 에서는 못 맞췄던 ITS)과 ±10 쌍 중 다른 DB 로 바뀐 쌍
    for name, i in (("gyeongbu", 0), ("national", 1)):
        a10 = {p["its_start"] + p.get("its_road", ""): p for p in keep[10.0][i]}
        a30 = {p["its_start"] + p.get("its_road", ""): p for p in keep[30.0][i]}
        out["sets"]["pm30"][name]["added_vs_pm10"] = len(set(a30) - set(a10))
        out["sets"]["pm30"][name]["changed_partner_vs_pm10"] = sum(
            a30[k]["db_t"] != a10[k]["db_t"] for k in a10 if k in a30)
        add = [a30[k]["delay_min"] for k in set(a30) - set(a10)]
        out["sets"]["pm30"][name]["added_pairs_share_gt_13min"] = (sum(v * 60 > OFFICIAL_S for v in add) / len(add)) if add else None

    # 모형 입력: 경부선 ±10분, 초, 음수 0
    raw_s = [p["delay_min"] * 60 for p in gp10]
    clip = [max(0.0, v) for v in raw_s]
    dj = {"source": "analyze_e1_delay.py — 경부선 ITS 사고 ↔ 사고 DB, ±10분·같은 진행 방향(B 와 같은 맞춤), "
                    "ITS 돌발일시 − DB 사고일시, 음수는 0 (등록문 E1)",
          "unit": "s", "n": len(clip), "pairs_order": "ITS 돌발일시 순(load_its 순서)",
          "delay_s": [round(v, 1) for v in clip],
          "summary": {"median": statistics.median(clip), "q1": quant(clip, 0.25), "q3": quant(clip, 0.75),
                      "mean": statistics.fmean(clip), "min": min(clip), "max": max(clip),
                      "n_clipped_to_0": sum(v < 0 for v in raw_s), "share_gt_779s": sum(v > OFFICIAL_S for v in clip) / len(clip),
                      "official_delay_s_replaced": OFFICIAL_S},
          "caveat": "±10분 창으로 맞춘 쌍이라 최대 600 s 로 잘려 있다(779 s 를 넘는 값은 구조적으로 없음). "
                    "두 시각 모두 신고·등록 시각일 수 있어 사고 발생 → 공식 안내 지연이 아니다."}
    (DATA / "its_registration_delay.json").write_text(json.dumps(dj, ensure_ascii=False, indent=1), encoding="utf-8")
    out["model_input"] = {"path": "data/its_registration_delay.json", "n": dj["n"], **dj["summary"]}
    (RES / "report_e1_delay.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # 보고서
    S = out["sets"]
    f2 = lambda v: f"{v:+.2f}"
    pc = lambda v: f"{v*100:.1f} %"

    def row(lbl, s):
        return (f"| {lbl} | {s['n']} | {f2(s['median'])} | {f2(s['q1'])} ~ {f2(s['q3'])} | {f2(s['mean'])} | "
                f"{f2(s['min'])} ~ {f2(s['max'])} | {pc(s['share_gt_13min'])} | {pc(s['share_negative'])} |")

    L = ["# E1 공식 안내 지연의 실측 분포 — 분석 부분 (탐색, 서술)", "",
         "등록: `docs/sim-preregistration.md` '관점 확장 E1~E8' 의 E1. 이 문서는 분포와 모형 입력 파일까지만 다룬다"
         "(지연 분포로 기준선·단계·일률 80 을 다시 돌리는 72회 실행은 별도).", "",
         "## 한계 (먼저)", "",
         "1. **두 시각 모두 사고 '발생' 시각이 아닐 수 있다.** ITS 돌발일시는 돌발 등록 시각이고, 사고 DB 의 사고시각도 "
         "신고·접수 기준으로 적혔을 수 있다. 따라서 아래 값은 '사고 발생 → 공식 안내'의 지연이 아니라 "
         "'DB 기록 시각 → ITS 등록 시각'의 차이다. 발생 시각부터의 지연은 이보다 길 수 있다(DB 시각이 이미 신고 지연을 품으면).",
         f"2. **창에 의한 꼬리 절단.** 쌍을 ±10분 안에서 맞췄으므로 분포는 [−10, +10]분으로 잘려 있다. "
         f"특히 13분(779 s) 초과 비율은 ±10분 창에서는 **구조적으로 0** 이며, 이것은 '공식 등록이 늘 779 s 보다 빠르다'는 증거가 아니다. "
         "±30분 민감도는 꼬리를 일부 열지만, 창을 넓히면 서로 다른 사고가 잘못 맞는 쌍도 늘 수 있다(같은 노선에 30분 안 다른 사고).",
         "3. **시각 해상도.** DB 사고시각은 분(HH:MM) 단위, ITS 는 초 단위다. 지연에 최대 ±1분의 반올림 성분이 섞인다.",
         "4. **선택 편향.** 맞춘 쌍은 ITS 사고(종료 있음·본선 차단 ≥ 1·진출입로 아님) 중 DB 에 같은 시각대로 있는 것만이다"
         f"(경부선 {S['pm10']['gyeongbu']['its_eligible']}건 중 {S['pm10']['gyeongbu']['n']}건, "
         f"전국 {S['pm10']['national']['its_eligible']}건 중 {S['pm10']['national']['n']}건).", "",
         "## 정의", "",
         "지연(분) = ITS 돌발일시 − 사고 DB 사고일시. 양수 = ITS 등록이 DB 시각보다 늦다. 맞춤은 `surrogate_crash.py`(경부선, "
         "같은 진행 방향)·`surrogate_crash_national.py`(전국, 노선명 대응)의 로더·대응표를 import 해 같은 규칙으로 했다"
         "(가장 가까운 시각 1개). 전국 770쌍은 B 확장의 'matched' 전체(상류 규칙 END 가 없는 노선으로 빠지기 전)다.", "",
         f"검산(±10분): 경부선 {out['check']['gyeongbu_n_vs_report_b'][0]}쌍 (report_b {out['check']['gyeongbu_n_vs_report_b'][1]}), "
         f"지연 값 일치 {out['check']['gyeongbu_delays_equal_report_b']}; 전국 {out['check']['national_n_vs_report_b_national'][0]}쌍 "
         f"(report_b_national matched {out['check']['national_n_vs_report_b_national'][1]}), END 노선 588쌍의 지연 일치 "
         f"{out['check']['national_END_delays_equal_report_b_national_rows']}.", "",
         "## 표 1. 분포 요약 (분)", "",
         "| 집합 | n | 중앙값 | 사분위 Q1 ~ Q3 | 평균 | 최소 ~ 최대 | 13분(779 s) 초과 | 음수(ITS 가 먼저) |",
         "|---|---|---|---|---|---|---|---|",
         row("경부선 ±10분 (주)", S["pm10"]["gyeongbu"]), row("전국 ±10분 (주)", S["pm10"]["national"]),
         row("전국 ±10분, END 노선만(참고)", S["pm10"]["national_END_only"]),
         row("경부선 ±30분 (민감도)", S["pm30"]["gyeongbu"]), row("전국 ±30분 (민감도)", S["pm30"]["national"]), "",
         f"±30분에서 새로 맞춰진 쌍: 경부선 {S['pm30']['gyeongbu']['added_vs_pm10']}쌍"
         f"(그중 13분 초과 {pc(S['pm30']['gyeongbu']['added_pairs_share_gt_13min'] or 0)}), "
         f"전국 {S['pm30']['national']['added_vs_pm10']}쌍(그중 13분 초과 {pc(S['pm30']['national']['added_pairs_share_gt_13min'] or 0)}). "
         f"±10분 쌍 중 짝(DB 사고)이 바뀐 것: 경부선 {S['pm30']['gyeongbu']['changed_partner_vs_pm10']}, "
         f"전국 {S['pm30']['national']['changed_partner_vs_pm10']}(가장 가까운 시각 규칙이라 0 이어야 정상). "
         "새로 들어온 쌍은 시차가 10분을 넘는 것들이므로, 진짜 늦은 등록과 다른 사고와의 오맞춤이 섞여 있다 — 구분할 수 없다.", ""]
    for key, title in (("pm10", "±10분"), ("pm30", "±30분")):
        g, n = S[key]["gyeongbu"]["hist_1min"], S[key]["national"]["hist_1min"]
        L += [f"## 표 {2 if key == 'pm10' else 3}. 1분 구간 히스토그램 ({title}, [lo, hi))", "",
              "| 구간(분) | 경부선 | 전국 |", "|---|---|---|"]
        for a, b in zip(g, n):
            L.append(f"| {a['lo']:+d} ~ {a['hi']:+d} | {a['n']} | {b['n']} |")
        L.append("")
    mi = out["model_input"]
    L += ["## 모형 입력 파일", "",
          f"`data/its_registration_delay.json`: 경부선 ±10분 {mi['n']}쌍의 지연(초), 음수 {mi['n_clipped_to_0']}개는 0 으로. "
          f"중앙값 {mi['median']:.0f} s, 사분위 {mi['q1']:.0f} ~ {mi['q3']:.0f} s, 평균 {mi['mean']:.0f} s, 최대 {mi['max']:.0f} s "
          f"(기준선 779 s 를 대신할 경험 분포; 창 때문에 600 s 위가 없다는 점이 그대로 들어간다).", "",
          "## 서술", "",
          f"- 경부선: 중앙값 {f2(S['pm10']['gyeongbu']['median'])}분, 음수 {pc(S['pm10']['gyeongbu']['share_negative'])}. "
          f"전국: 중앙값 {f2(S['pm10']['national']['median'])}분, 음수 {pc(S['pm10']['national']['share_negative'])}.",
          f"- 13분 초과: ±10분 창에서는 구조적으로 0. ±30분 창에서 경부선 {pc(S['pm30']['gyeongbu']['share_gt_13min'])}, "
          f"전국 {pc(S['pm30']['national']['share_gt_13min'])} — 오맞춤 가능성을 안은 상한 쪽 값으로 읽는다.",
          "- 이 분포가 779 s 보다 짧다는 것은 'DB 기록 → ITS 등록'이 짧다는 뜻이며, 사고 발생부터 운전자에게 공식 안내가 닿기까지의 "
          "지연(779 s 의 원래 정의)과 같은 양인지는 이 자료로 확인할 수 없다."]
    (RES / "report_e1_delay.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps(out["check"], ensure_ascii=False))
    for key in ("pm10", "pm30"):
        for nm in ("gyeongbu", "national"):
            s = S[key][nm]
            print(key, nm, s["n"], round(s["median"], 3), round(s["q1"], 3), round(s["q3"], 3), round(s["mean"], 3),
                  round(s["share_gt_13min"], 4), round(s["share_negative"], 4))
    print("model input", mi)


if __name__ == "__main__":
    main()
