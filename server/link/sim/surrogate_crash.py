"""탐색 분석 B: 대리 지표(고속 접근 상충)와 실제 2차 사고의 연결.

  python -X utf8 surrogate_crash.py   # → results/report_b.json, results/report_b.md

등록문: docs/sim-preregistration.md '대리 지표와 2차 사고의 연결 B' (2026-11-04 21:43 고정).
- 예측면: Krauss 기준선(v2_main 씨앗 1~24 + r6_confirm 101~200, scheme 'official')에서
  log(fast+1) ~ 1 + blocked + dur_min + demand (최소제곱). 예측 상충 = exp(예측) - 1.
- 첫 사고: ITS 경부선 사고(end 있음, n_lanes>=1, ramp=0) ↔ 사고 DB 경부선, ±10분, 같은 진행 방향
  (ITS '서울 방향' = DB '부산'), 가장 가까운 시각. DB 의 시각·이정·방향을 붙인다.
- 2차 사고(6.3절·evidence.py 와 같은 정의): 0 < 시차 <= 2시간, 같은 방향, 상류 0~5 km
  (부산행은 이정이 큰 쪽이 상류). 하류 대조 = 같은 창 하류 0~5 km(0 제외). 시간 이동 대조 = ±1..8주.
- 교통량: 07~10·18~21시면 가장 가까운 경부선 조사 구간의 그 시간 값, 아니면 그 구간·방향 6개 값의 중앙값.
- 로지스틱(뉴턴법): 상류 2차 ~ log(예측) + 아침·저녁 더미(주), log(예측)만, 처리 시간만, 차단 차로만, 절편만.
"""
import csv
import datetime as dt
import json
import math
import statistics
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
DATA, RES = HERE / "data", HERE / "results"
MATCH_MIN, WIN_H, UP_KM = 10.0, 2.0, 5.0
SHIFT_WEEKS = [s * k for k in range(1, 9) for s in (1, -1)]
HOURS = [7, 8, 9, 18, 19, 20]
HCOL = {7: "07시에서 08시까지", 8: "08시에서 09시까지", 9: "09시에서 10시까지",
        18: "18시에서 19시까지", 19: "19시에서 20시까지", 20: "20시에서 21시까지"}
# 조사 구간 대략 이정(km, 부산 기점) — gyeongbu_conzones.json 의 IC/JC 이정으로 맞춘 구간 중점.
# 노포JC 는 콘존에 없어 양산JC(12.84) 남쪽 약 7 km 로 둠, 칠곡JC 는 금호JC(139.35)~칠곡물류IC(150.09) 사이 약 144,
# 독립기념관IC 는 콘존에 없어 옥산IC(317.6) 북쪽 약 329 로 둠(가정).
SECTION_KM = {"노포JCT~양산JCT": (7.0 + 12.84) / 2, "언양JCT~활천": (40.11 + 57.3) / 2,
              "도동JCT~북대구": (126.19 + 133.87) / 2, "금호JCT~칠곡JCT": (139.35 + 144.0) / 2,
              "왜관~남구미": (153.27 + 167.25) / 2, "금강~옥천": (248.31 + 259.71) / 2,
              "옥산JCT~독립기념관": (319.0 + 329.0) / 2, "기흥~수원신갈": (387.19 + 392.28) / 2,
              "금토JCT~양재": (409.3 + 416.05) / 2}
FALLBACK = "기흥~수원신갈"


def surface():
    rows = []
    for f in ("v2_main.jsonl", "r6_confirm.jsonl"):
        for line in open(RES / f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("scheme") == "official":
                c = r["cond"]
                rows.append((c["blocked"], c["dur"] / 60.0, c["demand"], r["fast"], r["seed"]))
    X = np.array([[1.0, b, d, q] for b, d, q, _, _ in rows])
    y = np.log(np.array([f for *_, f, _ in rows], float) + 1)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    r2 = 1 - (res @ res) / ((y - y.mean()) @ (y - y.mean()))
    n, p = X.shape
    s2 = res @ res / (n - p)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    rng = {"blocked": sorted({r[0] for r in rows}), "dur_min": [min(r[1] for r in rows), max(r[1] for r in rows)],
           "demand": [min(r[2] for r in rows), max(r[2] for r in rows)], "fast": [min(r[3] for r in rows), max(r[3] for r in rows)]}
    return {"n": n, "seeds": sorted({r[4] for r in rows}), "names": ["const", "blocked", "dur_min", "demand"],
            "coef": beta.tolist(), "se": se.tolist(), "r2": float(r2), "range": rng}


def load_db():
    acc = []
    with open(DATA / "accidents" / "accidents_2023_2025.csv", encoding="cp949") as f:
        for r in csv.DictReader(f):
            if r["노선명"] != "경부선":
                continue
            hh, mm = map(int, r["사고시각"].split(":"))
            t = dt.datetime.fromisoformat(r["사고일자"]) + dt.timedelta(hours=hh, minutes=mm)
            acc.append({"t": t, "km": float(r["사고발생이정"]), "dir": r["방향"]})
    return sorted(acc, key=lambda a: a["t"])


def load_its():
    out = []
    with open(DATA / "its_gyeongbu_accidents.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not r["end"] or int(r["n_lanes"]) < 1 or int(r["ramp"]) != 0:
                continue
            out.append({"start": dt.datetime.fromisoformat(r["start"]), "dur_min": float(r["dur_min"]),
                        "n_lanes": int(r["n_lanes"]), "its_dir": r["direction"],
                        "db_dir": "부산" if r["direction"] == "서울 방향" else "서울"})
    return out


def load_volume():
    vol = {}
    with open(DATA / "commute_volume_20251231.csv", encoding="cp949") as f:
        for r in csv.DictReader(f):
            if r["노선명"] != "경부선":
                continue
            d = "부산" if r["방향"] == "기점" else "서울"
            vol[(r["구간"], d)] = {h: float(r[HCOL[h]]) for h in HOURS}
    return vol


def volume_for(vol, km, d, hour):
    secs = [s for s in SECTION_KM if (s, d) in vol]
    if not secs:
        s, fb = FALLBACK, True
    else:
        s, fb = min(secs, key=lambda s: abs(SECTION_KM[s] - km)), False
    v = vol[(s, d)]
    if hour in v:
        return v[hour], s, abs(SECTION_KM[s] - km), fb, True
    return statistics.median(v.values()), s, abs(SECTION_KM[s] - km), fb, False


def up_dist(a_km, b_km, d):
    """상류면 + (부산행: 이정이 큰 쪽이 상류, 서울행: 작은 쪽)"""
    return (b_km - a_km) if d == "부산" else (a_km - b_km)


def count_window(db_dir, t0, km, side):
    n = 0
    for b in db_dir:
        dtm = (b["t"] - t0).total_seconds() / 3600
        if dtm <= 0:
            continue
        if dtm > WIN_H:
            break
        u = up_dist(km, b["km"], b["dir"])
        if side == "up" and 0.0 <= u <= UP_KM:
            n += 1
        elif side == "down" and 0.0 < -u <= UP_KM:
            n += 1
    return n


def logit(X, y, names, iters=100):
    X = np.asarray(X, float); y = np.asarray(y, float)
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = X @ b
        p = 1 / (1 + np.exp(-eta))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None])
        g = X.T @ (y - p)
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-10:
            break
    eta = X @ b
    p = 1 / (1 + np.exp(-eta))
    ll = float(np.sum(y * np.log(np.clip(p, 1e-300, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-300, 1))))
    cov = np.linalg.inv(X.T @ (X * (p * (1 - p))[:, None]))
    se = np.sqrt(np.diag(cov))
    terms = [{"term": nm, "coef": float(c), "se": float(s), "ci_lo": float(c - 1.96 * s), "ci_hi": float(c + 1.96 * s),
              "odds_ratio": float(math.exp(c))} for nm, c, s in zip(names, b, se)]
    return {"n": int(len(y)), "events": int(y.sum()), "loglik": ll, "aic": float(2 * X.shape[1] - 2 * ll), "terms": terms}


def fit_set(rows, key):
    y = [r[key] for r in rows]
    one = [1.0] * len(rows)
    lp = [r["log_pred"] for r in rows]
    mor = [1.0 if r["tod"] == "morning" else 0.0 for r in rows]
    eve = [1.0 if r["tod"] == "evening" else 0.0 for r in rows]
    dur = [r["dur_min"] for r in rows]
    bl = [float(r["n_lanes"]) for r in rows]
    col = lambda *cs: np.column_stack(cs)
    if sum(y) == 0:
        return {"note": "사건 0건 — 적합하지 않음"}
    return {
        "logpred_tod": logit(col(one, lp, mor, eve), y, ["const", "log_pred", "morning", "evening"]),
        "logpred": logit(col(one, lp), y, ["const", "log_pred"]),
        "dur_only": logit(col(one, dur), y, ["const", "dur_min"]),
        "blocked_only": logit(col(one, bl), y, ["const", "blocked"]),
        "null": logit(col(one), y, ["const"]),
    }


def verdict(fits_up, fits_down, n_up):
    if n_up < 30:
        return f"판정하지 않음(상류 2차 사고 {n_up}건 < 30)."
    def pos(f):
        t = next(t for t in f["terms"] if t["term"] == "log_pred")
        return t["coef"] > 0 and t["ci_lo"] > 0
    up_ok = pos(fits_up["logpred_tod"])
    down_ok = ("logpred_tod" in fits_down) and pos(fits_down["logpred_tod"])
    if up_ok and not down_ok:
        return "주 지표가 2차 사고와 같은 방향이라는 약한 근거(상류 계수 양·CI>0, 하류 대조는 아님)."
    if up_ok and down_ok:
        return "상류 계수는 양·CI>0 이나 하류 대조도 같아 근거로 보지 않음(일반 사고 밀도 효과 가능)."
    return "근거 없음(상류 log(예측 상충) 계수의 95 % CI 가 0 을 넘지 않음)."


def main():
    surf = surface()
    beta = np.array(surf["coef"])
    db = load_db()
    its = load_its()
    vol = load_volume()
    db_by_dir = {d: [a for a in db if a["dir"] == d] for d in ("부산", "서울")}
    db_lo, db_hi = db[0]["t"].date(), db[-1]["t"].date()

    rows, unmatched, out_of_range = [], 0, 0
    used = {}
    for e in its:
        if not (db_lo - dt.timedelta(days=1) <= e["start"].date() <= db_hi + dt.timedelta(days=1)):
            out_of_range += 1
        cands = [a for a in db_by_dir[e["db_dir"]] if abs((a["t"] - e["start"]).total_seconds()) <= MATCH_MIN * 60]
        if not cands:
            unmatched += 1
            continue
        a = min(cands, key=lambda a: abs((a["t"] - e["start"]).total_seconds()))
        key = (a["t"], a["km"], a["dir"])
        used[key] = used.get(key, 0) + 1
        h = a["t"].hour
        q, sec, sec_d, fb, hourly = volume_for(vol, a["km"], a["dir"], h)
        tod = "morning" if 7 <= h <= 9 else "evening" if 18 <= h <= 20 else "other"
        lp_raw = float(beta @ np.array([1.0, e["n_lanes"], e["dur_min"], q]))
        pred = math.exp(lp_raw) - 1
        dd = db_by_dir[a["dir"]]
        r = {"its_start": e["start"].isoformat(), "db_t": a["t"].isoformat(), "km": a["km"], "dir": a["dir"],
             "lag_min": (a["t"] - e["start"]).total_seconds() / 60, "n_lanes": e["n_lanes"], "dur_min": e["dur_min"],
             "volume": q, "vol_section": sec, "vol_section_dist_km": sec_d, "vol_fallback": fb, "vol_hourly": hourly,
             "tod": tod, "pred_fast": pred, "log_pred": math.log(pred) if pred > 0 else None,
             "sec_up_n": count_window(dd, a["t"], a["km"], "up"), "sec_down_n": count_window(dd, a["t"], a["km"], "down")}
        r["sec_up"] = int(r["sec_up_n"] > 0); r["sec_down"] = int(r["sec_down_n"] > 0)
        # 시간 이동 대조
        su = sd = ns = 0
        for w in SHIFT_WEEKS:
            t0 = a["t"] + dt.timedelta(days=7 * w)
            if t0.date() < db_lo or (t0 + dt.timedelta(hours=WIN_H)).date() > db_hi:
                continue
            ns += 1
            su += int(count_window(dd, t0, a["km"], "up") > 0)
            sd += int(count_window(dd, t0, a["km"], "down") > 0)
        r["shift_n"], r["shift_up"], r["shift_down"] = ns, su, sd
        rows.append(r)

    nonpos = sum(1 for r in rows if r["log_pred"] is None)
    fitrows = [r for r in rows if r["log_pred"] is not None]
    sens = [r for r in fitrows if 10 <= r["dur_min"] <= 180]

    def summary(rs):
        n = len(rs); nsh = sum(r["shift_n"] for r in rs)
        return {"n_first": n, "sec_up": sum(r["sec_up"] for r in rs), "sec_down": sum(r["sec_down"] for r in rs),
                "rate_up": sum(r["sec_up"] for r in rs) / n if n else None,
                "rate_down": sum(r["sec_down"] for r in rs) / n if n else None,
                "shift_windows": nsh,
                "shift_rate_up": sum(r["shift_up"] for r in rs) / nsh if nsh else None,
                "shift_rate_down": sum(r["shift_down"] for r in rs) / nsh if nsh else None}

    main_s, sens_s = summary(fitrows), summary(sens)
    fits = {"up": fit_set(fitrows, "sec_up"), "down": fit_set(fitrows, "sec_down")}
    fits_sens = {"up": fit_set(sens, "sec_up"), "down": fit_set(sens, "sec_down")}
    v = verdict(fits["up"], fits["down"], main_s["sec_up"])
    v_sens = verdict(fits_sens["up"], fits_sens["down"], sens_s["sec_up"])
    lp = [r["log_pred"] for r in fitrows]
    sr = surf["range"]
    extrap = {"blocked_gt2": sum(r["n_lanes"] > 2 for r in fitrows),
              "dur_outside": sum(not (sr["dur_min"][0] <= r["dur_min"] <= sr["dur_min"][1]) for r in fitrows),
              "volume_outside": sum(not (sr["demand"][0] <= r["volume"] <= sr["demand"][1]) for r in fitrows)}
    out = {"prereg": "docs/sim-preregistration.md '대리 지표와 2차 사고의 연결 B'", "surface": surf,
           "matching": {"its_eligible": len(its), "matched": len(rows), "unmatched": unmatched,
                        "its_outside_db_years": out_of_range,
                        "db_accidents_matched_more_than_once": sum(1 for k, c in used.items() if c > 1),
                        "median_abs_lag_min": statistics.median(abs(r["lag_min"]) for r in rows) if rows else None},
           "volume": {"hourly": sum(r["vol_hourly"] for r in rows), "daily_median_assumed": sum(not r["vol_hourly"] for r in rows),
                      "fallback_kiheung": sum(r["vol_fallback"] for r in rows),
                      "median_dist_to_section_km": statistics.median(r["vol_section_dist_km"] for r in rows) if rows else None,
                      "max_dist_to_section_km": max(r["vol_section_dist_km"] for r in rows) if rows else None},
           "pred_nonpositive_dropped": nonpos,
           "log_pred_summary": {"min": min(lp), "median": statistics.median(lp), "max": max(lp)} if lp else None,
           "extrapolation_counts": extrap,
           "samples": main_s, "fits": fits, "verdict": v,
           "sensitivity_dur_10_180": {"samples": sens_s, "fits": fits_sens, "verdict": v_sens},
           "rows": rows}
    (RES / "report_b.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (RES / "report_b.md").write_text(render(out), encoding="utf-8")
    print(render(out))


def f3(x, d=3):
    return "—" if x is None else f"{x:.{d}f}"


def fit_table(fits):
    L = ["| 모형 | 항 | 계수 | 95 % CI | AIC | n / 사건 |", "|---|---|---|---|---|---|"]
    label = {"logpred_tod": "log(예측)+시간대", "logpred": "log(예측)", "dur_only": "처리 시간만",
             "blocked_only": "차단 차로만", "null": "절편만"}
    if "note" in fits:
        return fits["note"]
    for k, f in fits.items():
        for i, t in enumerate(f["terms"]):
            L.append(f"| {label[k] if i == 0 else ''} | {t['term']} | {f3(t['coef'])} | {f3(t['ci_lo'])} ~ {f3(t['ci_hi'])} | "
                     f"{f3(f['aic'], 2) if i == 0 else ''} | {str(f['n']) + ' / ' + str(f['events']) if i == 0 else ''} |")
    return "\n".join(L)


def render(o):
    s, m, vv, sv = o["surface"], o["matching"], o["volume"], o["samples"]
    ss = o["sensitivity_dur_10_180"]["samples"]
    L = ["# 탐색 분석 B: 대리 지표와 2차 사고의 연결 (6.4절 탐색)", "",
         f"등록문: {o['prereg']}. 가설 검정이 아니라 탐색이다.", "",
         f"**판정:** {o['verdict']}", "",
         f"보조(처리 시간 10~180분): {o['sensitivity_dur_10_180']['verdict']}", "",
         "## 1. 예측면 (Krauss 기준선 'official', PC)", "",
         f"log(fast+1) ~ 1 + 막힌 차로 + 처리 시간(분) + 교통량(대/시), 최소제곱, n = {s['n']} (씨앗 1~24, 101~200). R² = {f3(s['r2'])}.", "",
         "| 항 | 계수 | 표준오차 |", "|---|---|---|"]
    for nm, c, e in zip(s["names"], s["coef"], s["se"]):
        L.append(f"| {nm} | {c:.4g} | {e:.3g} |")
    r = s["range"]
    L += ["", f"모형 실행 범위: 막힌 차로 {r['blocked']}, 처리 시간 {f3(r['dur_min'][0],2)}~{f3(r['dur_min'][1],2)}분, "
          f"교통량 {r['demand'][0]}~{r['demand'][1]} 대/시, fast {r['fast'][0]}~{r['fast'][1]}.", "",
          "## 2. 표본", "",
          f"- ITS 대상 사고 {m['its_eligible']}건 → DB 와 맞음 {m['matched']}건, 못 맞음 {m['unmatched']}건 "
          f"(그중 DB 연도 밖 ITS 기록 {m['its_outside_db_years']}건). |시차| 중앙값 {f3(m['median_abs_lag_min'],2)}분. "
          f"같은 DB 사고에 둘 이상 맞은 경우 {m['db_accidents_matched_more_than_once']}건(그대로 둠).",
          f"- 교통량: 시간대 실측 {vv['hourly']}건, 하루 중앙값 가정 {vv['daily_median_assumed']}건, 기흥~수원신갈 대체 {vv['fallback_kiheung']}건. "
          f"가장 가까운 조사 구간까지 거리 중앙값 {f3(vv['median_dist_to_section_km'],1)} km, 최대 {f3(vv['max_dist_to_section_km'],1)} km.",
          f"- 예측 상충 ≤ 0 이라 log 가 없는 사고 {o['pred_nonpositive_dropped']}건(제외). "
          f"log(예측) 최소 {f3(o['log_pred_summary']['min'])}, 중앙 {f3(o['log_pred_summary']['median'])}, 최대 {f3(o['log_pred_summary']['max'])}.",
          f"- 모형 범위 밖 외삽: 막힌 차로 3개 이상 {o['extrapolation_counts']['blocked_gt2']}건, 처리 시간 범위 밖 {o['extrapolation_counts']['dur_outside']}건, "
          f"교통량 범위 밖 {o['extrapolation_counts']['volume_outside']}건.", "",
          "| 집합 | 첫 사고 | 상류 2차 | 하류 2차 | 상류 비율 | 하류 비율 | 시간 이동 창 | 이동 상류 비율 | 이동 하류 비율 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for nm, x in (("전체(주)", sv), ("처리 10~180분", ss)):
        L.append(f"| {nm} | {x['n_first']} | {x['sec_up']} | {x['sec_down']} | {f3(x['rate_up'])} | {f3(x['rate_down'])} | "
                 f"{x['shift_windows']} | {f3(x['shift_rate_up'])} | {f3(x['shift_rate_down'])} |")
    L += ["", "## 3. 로지스틱 회귀 — 상류 2차 사고 (주)", "", fit_table(o["fits"]["up"]), "",
          "## 4. 같은 회귀 — 하류 대조", "", fit_table(o["fits"]["down"]), "",
          "## 5. 보조: 처리 시간 10~180분", "", "상류:", "", fit_table(o["sensitivity_dur_10_180"]["fits"]["up"]), "",
          "하류:", "", fit_table(o["sensitivity_dur_10_180"]["fits"]["down"]), "",
          "## 6. 가정과 한계", "",
          "- 예측면 전이: 예측면은 한 구간(4차로 직선) 모형의 실행으로 만들었고, 경부선의 다른 차로 수·선형·구간에 그대로 쓴다고 가정했다. "
          "1절의 모형 실행 범위(막힌 차로·처리 시간·교통량) 밖의 사고는 로그-선형 외삽이다(2절의 외삽 수).",
          "- log(예측)은 막힌 차로·처리 시간·교통량의 고정된 결합이라, 이 회귀는 그 결합 방향이 2차 사고와 같은 쪽인지를 본다. 처리 시간·차단 차로 단독 모형과의 AIC 비교가 그 결합이 단독 변수보다 나은지를 보여 준다.",
          "- 교통량 대체: 경부선 조사 구간이 9개뿐이라 가장 가까운 구간 값을 썼고(구간 이정은 콘존 IC/JC 이정으로 대략 맞춤, 노포JC·칠곡JC·독립기념관IC 는 추정), "
          "07~10·18~21시 밖은 그 구간 6개 시간 값의 중앙값으로 가정했다. 2025-12-31 조사 한 시점 값을 2023~2025 모든 날에 썼다.",
          "- ITS–DB 맞춤 오차: ±10분·같은 방향만으로 맞추고 위치는 보지 않아, 같은 시각 다른 지점 사고와 잘못 맞을 수 있다. "
          "방향 대응(ITS '서울 방향' = DB '부산')은 등록문을 따랐다. 같은 DB 사고에 여러 ITS 기록이 맞으면 그대로 두었다.",
          "- 사고 DB 에 2차 사고 표시가 없어 상류 0~5 km·2시간 안의 사고를 2차 사고로 본다(6.3절 정의). 시간 이동 대조 비율이 배경 확률이다.",
          "- 신뢰구간은 왈드(정규 근사) 95 % 구간, 뉴턴법 최대우도(numpy 구현; statsmodels 없음).", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
