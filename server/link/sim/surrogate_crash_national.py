"""탐색 분석 B 확장: 전국 노선 (대리 지표와 2차 사고의 연결).

  python -X utf8 surrogate_crash_national.py   # → results/report_b_national.json, results/report_b_national.md

등록문: docs/sim-preregistration.md '## B 확장: 전국 노선' (2026-11-04 21:58 고정). 방법은 B(surrogate_crash.py)와 같고
다른 점만 여기 적는다.
- ITS: data/its_event/*.zip 의 고속국도 교통사고 전부(its_events.py 와 같은 사고 키·차단 차로·처리 시간 규칙,
  lanes_from 을 그대로 import; 사고 키는 (돌발일시, 링크아이디, 도로명) — B 가 도로명 '경부선' 안에서 (돌발일시, 링크아이디)로 묶은 것과 같다;
  같은 키를 경찰청 기록('경부고속도로' 등)이 공유해 마지막 기록이 바뀌는 것을 막는다). 대상 = 종료 시각 있음, 본선 차단 차로 >= 1, 진출입로 아님(B 와 같음).
  파싱 결과는 _work/its_national_accidents.csv 에 캐시(있으면 다시 읽음; --reparse 로 새로 만듦).
- 맞춤: ITS (도로번호, 도로명) → DB 노선명 후보 집합(ROUTE_MAP, 아래 표). 후보 노선의 DB 사고 중 ±10분 안에서
  가장 가까운 시각. 방향·이정은 DB 값. ITS 방향은 쓰지 않는다.
- 상류: evidence.py 의 END(6.3절, 노선 번호 규칙: 남북 노선은 남쪽·동서 노선은 서쪽이 기점; 방향 = END[노선] 이면
  이정이 커지는 쪽으로 진행 → 이정이 작은 쪽이 상류). END 에 없는 노선의 첫 사고는 상류를 정할 수 없어 뺀다(6.3절과 같음).
  경부선은 END['경부선']='서울' 이라 B 의 규칙(부산행은 이정이 큰 쪽이 상류)과 같다.
- 2차 사고: 같은 노선·방향 DB 사고, 0 < 시차 <= 2h, 상류 0~5 km. 하류 대조 0~5 km(0 제외). 시간 이동 대조 ±1..8주.
- 교통량: 상시 교통량조사(commute_volume_20251231.csv)에 그 DB 노선에 대응하는 조사 노선이 있으면 그 노선 구간 값
  (구간 이정을 모르므로 '가장 가까운' = 그 노선·방향 구간들의 같은 시간 값 중앙값 — 한계로 적음), 07~10·18~21시 밖이면
  그 값들의 하루 중앙값(B 와 같은 규칙). 경부선은 B 와 같이 SECTION_KM 으로 가장 가까운 구간. 조사 노선이 없으면
  전체 중앙값(모든 구간·방향·시간 값의 중앙값)으로 가정하고 수를 센다.
- 예측면·로지스틱 5개·판정: surrogate_crash.py 를 import 해 그대로 쓴다(Krauss 경부선 4차로 모형 → 다른 노선 전이 가정).
"""
import csv
import datetime as dt
import io
import json
import math
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import surrogate_crash as B
from evidence import END
from its_events import lanes_from

HERE = Path(__file__).parent
DATA, RES = HERE / "data", HERE / "results"
CACHE = HERE / "_work" / "its_national_accidents.csv"
FMT = "%Y-%m-%d %H:%M:%S"

# ITS (도로번호, 도로명) → DB 노선명 후보. 결과를 보기 전에, ITS·DB 이름 목록만 보고 만든 표.
# 같은 번호에 DB 노선이 여럿이면(30·12·65·20) 이름으로 갈리는 것은 그 이름만, 갈리지 않는 고속도로 이름은 여러 후보.
ROUTE_MAP = {
    ("1", "경부선"): ["경부선"], ("1", "경부고속도로"): ["경부선"],
    ("10", "남해선(순천-부산)"): ["남해선"], ("10", "남해고속도로"): ["남해선"], ("10", "남해선"): ["남해선"],
    ("101", "남해선(영암-순천)"): ["남해선"],
    ("102", "남해1지선"): ["남해제1지선"], ("102", "남해고속도로제1지선"): ["남해제1지선"], ("102", "남해제1지선"): ["남해제1지선"],
    ("104", "남해2지선"): ["남해제2지선"], ("104", "남해고속도로제2지선"): ["남해제2지선"], ("104", "남해제2지선"): ["남해제2지선"],
    ("300", "대전남부선"): ["대전남부순환선"], ("141", "함양울산선"): ["함양울산선"],
    ("400", "수도권제2순환선(파주-포천)"): ["수도권제2순환선"], ("253", "고창담양선"): ["고창담양선"],
    ("12", "광주대구선"): ["광주대구선", "ㄱ광주대구선"], ("12", "광주대구고속도로"): ["광주대구선", "ㄱ광주대구선"],
    ("12", "무안광주선"): ["무안광주선"], ("12", "무안광주고속도로"): ["무안광주선"],
    ("14", "함양울산선"): ["함양울산선"], ("14", "함양울산고속도로"): ["함양울산선"],
    ("15", "서해안선"): ["서해안선"], ("15", "서해안고속도로"): ["서해안선"],
    ("151", "서천공주선"): ["서천공주선"], ("151", "서천공주고속도로"): ["서천공주선"],
    ("16", "울산선"): ["울산선"], ("16", "울산고속도로"): ["울산선"],
    ("20", "익산포항고속도로"): ["익산장수선", "대구포항선"], ("20", "익산장수선"): ["익산장수선"],
    ("20", "익산장수고속도로"): ["익산장수선"], ("20", "대구포항선"): ["대구포항선"], ("20", "대구포항고속도로"): ["대구포항선"],
    ("25", "호남선"): ["호남선"], ("25", "호남고속도로"): ["호남선"], ("25", "논산천안선"): ["호남선"],
    ("25", "논산천안고속도로"): ["호남선"],
    ("251", "호남고속도로지선"): ["호남선의 지선"], ("251", "호남지선"): ["호남선의 지선"], ("251", "호남선의 지선"): ["호남선의 지선"],
    ("27", "순천완주선"): ["순천완주선"], ("27", "순천완주고속도로"): ["순천완주선"],
    ("29", "세종포천선"): ["세종포천선"], ("29", "세종포천고속도로"): ["세종포천선"], ("29", "구리포천고속도로"): ["세종포천선"],
    ("30", "당진영덕고속도로"): ["당진대전선", "ㄷ당진대전선", "청주영덕선", "ㄷ청주상주선", "ㄷ상주영덕선"],
    ("30", "당진대전선"): ["당진대전선", "ㄷ당진대전선"], ("30", "당진대전고속도로"): ["당진대전선", "ㄷ당진대전선"],
    ("30", "청주영덕선"): ["청주영덕선", "ㄷ청주상주선", "ㄷ상주영덕선"], ("30", "청주영덕고속도로"): ["청주영덕선", "ㄷ청주상주선", "ㄷ상주영덕선"],
    ("30", "청주상주선"): ["ㄷ청주상주선", "청주영덕선"], ("30", "상주영덕선"): ["ㄷ상주영덕선", "청주영덕선"],
    ("32", "당진청주선"): ["당진청주선"], ("32", "당진청주고속도로"): ["당진청주선"],
    ("35", "중부선"): ["중부선"], ("35", "중부고속도로"): ["중부선"], ("35", "통영대전선"): ["중부선"],
    ("35", "통영대전고속도로"): ["중부선"],
    ("37", "제2중부선"): ["제2중부선"], ("37", "제2중부고속도로"): ["제2중부선"],
    ("40", "평택제천선"): ["평택제천선"], ("40", "평택제천고속도로"): ["평택제천선"],
    ("45", "중부내륙선"): ["중부내륙선"], ("45", "중부내륙고속도로"): ["중부내륙선"],
    ("451", "중부내륙고속도로지선"): ["중부내륙선의 지선"], ("451", "중부내륙지선"): ["중부내륙선의 지선"],
    ("451", "중부내륙선의 지선"): ["중부내륙선의 지선"],
    ("50", "영동선"): ["영동선"], ("50", "영동고속도로"): ["영동선"],
    ("55", "중앙선"): ["중앙선"], ("55", "중앙고속도로"): ["중앙선"],
    ("551", "중앙선지선"): ["중앙선의 지선"], ("551", "중앙고속도로지선"): ["중앙선의 지선"], ("551", "중앙선의 지선"): ["중앙선의 지선"],
    ("60", "서울양양선"): ["서1울양양선"], ("60", "서울양양고속도로"): ["서1울양양선"],
    ("65", "동해선(삼척-속초)"): ["동해선"], ("65", "동해선(부산-포항)"): ["부산포항선"],
    ("65", "동해고속도로"): ["동해선", "부산포항선"], ("65", "울산포항고속도로"): ["부산포항선"], ("65", "부산울산선"): ["부산포항선"],
    ("65", "부산울산고속도로"): ["부산포항선"], ("65", "동해선"): ["동해선", "부산포항선"], ("65", "부산포항선"): ["부산포항선"],
    ("100", "수도권제1순환선"): ["수도권제1순환선"], ("100", "서울외곽순환고속도로"): ["수도권제1순환선"],
    ("100", "수도권제1순환고속도로"): ["수도권제1순환선"],
    ("110", "제2경인선"): ["제2경인선"], ("110", "제2경인고속도로"): ["제2경인선"],
    ("120", "경인선"): ["경인선"], ("120", "경인고속도로"): ["경인선"],
    ("300", "대전남부순환선"): ["대전남부순환선"], ("300", "대전남부순환고속도로"): ["대전남부순환선"],
    ("400", "수도권제2순환선"): ["수도권제2순환선"], ("400", "수도권제2순환고속도로"): ["수도권제2순환선"],
    ("600", "부산외곽선"): ["부산외곽순환선"], ("600", "부산외곽순환고속도로"): ["부산외곽순환선"], ("600", "부산외곽순환선"): ["부산외곽순환선"],
    ("700", "대구외곽순환선"): ["대구외곽순환선"], ("700", "대구외곽순환고속도로"): ["대구외곽순환선"],
    ("-", "대구외곽순환선"): ["대구외곽순환선"], ("-", "대구외곽순환고속도로"): ["대구외곽순환선"],
    ("-", "광주외곽순환선"): ["광주외곽순환선"], ("-", "광주외곽순환고속도로"): ["광주외곽순환선"],
    ("20", "포항영덕선"): ["포항영덕선"], ("20", "포항영덕고속도로"): ["포항영덕선"],
}

# DB 노선명 → 상시 교통량조사 노선명(같은 노선이 조사에 있을 때만).
VOL_ROUTE = {
    "경부선": "경부선", "중부선": "중부·통영대전선", "중앙선": "중앙선", "서해안선": "서해안선", "남해선": "남해선",
    "수도권제1순환선": "수도권제1순환선", "평택제천선": "평택제천선", "중부내륙선": "중부내륙선", "영동선": "영동선",
    "세종포천선": "세종포천선", "남해제1지선": "남해제1지선", "경인선": "경인선", "수도권제2순환선": "수도권제2순환선",
    "중앙선의 지선": "중앙선지선", "대구외곽순환선": "대구외곽순환선", "광주대구선": "광주대구·무안광주선",
    "ㄱ광주대구선": "광주대구·무안광주선", "무안광주선": "광주대구·무안광주선", "함양울산선": "함양울산선",
    "호남선": "호남선", "서1울양양선": "서울양양선", "남해제2지선": "남해제2지선", "제2경인선": "제2경인선",
    "대전남부순환선": "대전남부순환선", "중부내륙선의 지선": "중부내륙선지선",
}


def parse_its(reparse=False):
    if CACHE.exists() and not reparse:
        with CACHE.open(encoding="utf-8-sig") as f:
            return list(csv.DictReader(f)), json.loads((CACHE.with_suffix(".meta.json")).read_text(encoding="utf-8"))
    rows = defaultdict(list)
    files = sorted((DATA / "its_event").glob("*.zip"))
    bad = []
    for f in files:
        try:
            z = zipfile.ZipFile(f)
        except zipfile.BadZipFile:
            bad.append(f.name); continue
        for n in z.namelist():
            text = z.read(n).decode("utf-8-sig", errors="replace")
            for r in csv.DictReader(io.StringIO(text)):
                if r.get("도로타입") != "고속국도" or r.get("돌발구분") != "교통사고":
                    continue
                rows[(r["돌발일시"], r["링크아이디"], r["도로명"])].append((f.stem, r))
    out = []
    for (start, link, _name), recs in rows.items():
        recs.sort(key=lambda x: x[0])
        last = recs[-1][1]
        ends = [x[1]["돌발종료일시"] for x in recs if x[1]["돌발종료일시"] not in ("-", "", None)]
        end = ends[-1] if ends else ""
        lanes, shoulder, ramp, allb = lanes_from(last["돌발내용"])
        try:
            dur = round((dt.datetime.strptime(end, FMT) - dt.datetime.strptime(start, FMT)).total_seconds() / 60, 1) if end else ""
        except ValueError:
            dur = ""
        out.append({"start": start, "end": end, "dur_min": dur, "road_no": last["도로번호"], "road_name": last["도로명"],
                    "agency": last["관리기관"], "direction": last["방향"], "lanes": ",".join(map(str, lanes)), "n_lanes": len(lanes),
                    "shoulder": int(shoulder), "ramp": int(ramp), "message": last["돌발내용"], "x": last["X"], "y": last["Y"],
                    "link_id": link})
    out.sort(key=lambda r: r["start"])
    CACHE.parent.mkdir(exist_ok=True)
    with CACHE.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    meta = {"files": len(files), "first": files[0].stem, "last": files[-1].stem, "bad_zip": bad}
    CACHE.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    with CACHE.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f)), meta


def load_db_all():
    acc = []
    with open(DATA / "accidents" / "accidents_2023_2025.csv", encoding="cp949") as f:
        for r in csv.DictReader(f):
            hh, mm = map(int, r["사고시각"].split(":"))
            t = dt.datetime.fromisoformat(r["사고일자"]) + dt.timedelta(hours=hh, minutes=mm)
            acc.append({"t": t, "km": float(r["사고발생이정"]), "dir": r["방향"], "route": r["노선명"]})
    return sorted(acc, key=lambda a: a["t"])


def load_volume_all():
    vol = defaultdict(list)          # (조사 노선, 방향 '기점'/'종점') → [{h: v}]
    allv = []
    with open(DATA / "commute_volume_20251231.csv", encoding="cp949") as f:
        for r in csv.DictReader(f):
            v = {h: float(r[B.HCOL[h]]) for h in B.HOURS}
            vol[(r["노선명"], r["방향"])].append(v)
            allv += list(v.values())
    return vol, statistics.median(allv)


def up_dist(route, a_km, b_km, d):
    """상류면 + . 방향 d 가 END[route](이정이 커지는 쪽으로 진행)이면 이정이 작은 쪽이 상류."""
    return (a_km - b_km) if d == END[route] else (b_km - a_km)


def count_window(dd, route, t0, km, side):
    n = 0
    for b in dd:
        dtm = (b["t"] - t0).total_seconds() / 3600
        if dtm <= 0:
            continue
        if dtm > B.WIN_H:
            break
        u = up_dist(route, km, b["km"], b["dir"])
        if side == "up" and 0.0 <= u <= B.UP_KM:
            n += 1
        elif side == "down" and 0.0 < -u <= B.UP_KM:
            n += 1
    return n


def volume_for(a, hour, vol_gb, vol_all, overall_med):
    """반환: (교통량, 출처, 시간대 실측 여부, 전체 중앙값 가정 여부)"""
    rt = a["route"]
    if rt == "경부선":
        q, sec, _, fb, hourly = B.volume_for(vol_gb, a["km"], a["dir"], hour)
        return q, f"경부선 {sec}", hourly, False
    vr = VOL_ROUTE.get(rt)
    if vr is None:
        return overall_med, "전체 중앙값(조사 노선 없음)", False, True
    side = "기점" if a["dir"] != END.get(rt, "\0") else "종점"
    # 방향 대응을 모르는 노선(END 없음)은 두 방향 모두를 쓴다.
    if rt in END:
        secs = vol_all.get((vr, side), [])
    else:
        secs = vol_all.get((vr, "기점"), []) + vol_all.get((vr, "종점"), [])
    if not secs:
        return overall_med, "전체 중앙값(조사 방향 없음)", False, True
    if hour in B.HOURS:
        return statistics.median(s[hour] for s in secs), f"{vr} {side if rt in END else '양방향'} {hour}시", True, False
    return statistics.median(v for s in secs for v in s.values()), f"{vr} {side if rt in END else '양방향'} 하루 중앙값", False, False


def main():
    reparse = "--reparse" in sys.argv
    surf = B.surface()
    beta = np.array(surf["coef"])
    its_all, meta = parse_its(reparse)
    db = load_db_all()
    vol_gb = B.load_volume()
    vol_all, overall_med = load_volume_all()
    db_lo, db_hi = db[0]["t"].date(), db[-1]["t"].date()
    db_by_route = defaultdict(list)
    db_by_rd = defaultdict(list)
    for a in db:
        db_by_route[a["route"]].append(a)
        db_by_rd[(a["route"], a["dir"])].append(a)

    names_its = Counter((r["road_no"], r["road_name"]) for r in its_all)
    eligible = [r for r in its_all if r["end"] and r["dur_min"] != "" and int(r["n_lanes"]) >= 1 and int(r["ramp"]) == 0]
    names_elig = Counter((r["road_no"], r["road_name"]) for r in eligible)

    per_route = defaultdict(lambda: {"its_eligible": 0, "its_in_db_years": 0, "matched": 0})
    rows, unmapped, unmatched, out_years, no_end = [], Counter(), 0, 0, Counter()
    used = Counter()
    for e in eligible:
        start = dt.datetime.fromisoformat(e["start"])
        key = (e["road_no"], e["road_name"])
        cands_routes = ROUTE_MAP.get(key)
        if not cands_routes:
            unmapped[key] += 1
            continue
        rlabel = "/".join(cands_routes)
        per_route[rlabel]["its_eligible"] += 1
        per_route[rlabel]["db_total"] = sum(len(db_by_route.get(rt, [])) for rt in cands_routes)
        in_years = db_lo <= start.date() <= db_hi
        if not in_years:
            out_years += 1
        else:
            per_route[rlabel]["its_in_db_years"] += 1
        cands = [a for rt in cands_routes for a in db_by_route.get(rt, [])
                 if abs((a["t"] - start).total_seconds()) <= B.MATCH_MIN * 60]
        if not cands:
            unmatched += 1
            continue
        a = min(cands, key=lambda a: (abs((a["t"] - start).total_seconds()), a["route"], a["km"]))
        per_route[rlabel]["matched"] += 1
        if a["route"] not in END:
            no_end[a["route"]] += 1
            continue
        used[(a["t"], a["route"], a["km"], a["dir"])] += 1
        h = a["t"].hour
        q, vsrc, hourly, assumed = volume_for(a, h, vol_gb, vol_all, overall_med)
        tod = "morning" if 7 <= h <= 9 else "evening" if 18 <= h <= 20 else "other"
        n_l, dur = int(e["n_lanes"]), float(e["dur_min"])
        lp_raw = float(beta @ np.array([1.0, n_l, dur, q]))
        pred = math.exp(lp_raw) - 1
        dd = db_by_rd[(a["route"], a["dir"])]
        r = {"its_start": e["start"], "its_road": f"{e['road_no']} {e['road_name']}", "db_route": a["route"],
             "db_t": a["t"].isoformat(), "km": a["km"], "dir": a["dir"], "lag_min": (a["t"] - start).total_seconds() / 60,
             "n_lanes": n_l, "dur_min": dur, "volume": q, "vol_source": vsrc, "vol_hourly": hourly, "vol_overall_assumed": assumed,
             "tod": tod, "pred_fast": pred, "log_pred": math.log(pred) if pred > 0 else None,
             "sec_up_n": count_window(dd, a["route"], a["t"], a["km"], "up"),
             "sec_down_n": count_window(dd, a["route"], a["t"], a["km"], "down")}
        r["sec_up"] = int(r["sec_up_n"] > 0); r["sec_down"] = int(r["sec_down_n"] > 0)
        su = sd = ns = 0
        for w in B.SHIFT_WEEKS:
            t0 = a["t"] + dt.timedelta(days=7 * w)
            if t0.date() < db_lo or (t0 + dt.timedelta(hours=B.WIN_H)).date() > db_hi:
                continue
            ns += 1
            su += int(count_window(dd, a["route"], t0, a["km"], "up") > 0)
            sd += int(count_window(dd, a["route"], t0, a["km"], "down") > 0)
        r["shift_n"], r["shift_up"], r["shift_down"] = ns, su, sd
        rows.append(r)

    nonpos = sum(1 for r in rows if r["log_pred"] is None)
    fitrows = [r for r in rows if r["log_pred"] is not None]
    sens = [r for r in fitrows if 10 <= r["dur_min"] <= 180]

    def summary(rs):
        n = len(rs); nsh = sum(r["shift_n"] for r in rs)
        return {"n_first": n, "sec_up": sum(r["sec_up"] for r in rs), "sec_down": sum(r["sec_down"] for r in rs),
                "sec_up_accidents": sum(r["sec_up_n"] for r in rs), "sec_down_accidents": sum(r["sec_down_n"] for r in rs),
                "rate_up": sum(r["sec_up"] for r in rs) / n if n else None,
                "rate_down": sum(r["sec_down"] for r in rs) / n if n else None,
                "shift_windows": nsh,
                "shift_rate_up": sum(r["shift_up"] for r in rs) / nsh if nsh else None,
                "shift_rate_down": sum(r["shift_down"] for r in rs) / nsh if nsh else None}

    main_s, sens_s = summary(fitrows), summary(sens)
    fits = {"up": B.fit_set(fitrows, "sec_up"), "down": B.fit_set(fitrows, "sec_down")} if fitrows else {"up": {"note": "표본 없음"}, "down": {"note": "표본 없음"}}
    fits_sens = {"up": B.fit_set(sens, "sec_up"), "down": B.fit_set(sens, "sec_down")} if sens else {"up": {"note": "표본 없음"}, "down": {"note": "표본 없음"}}
    v = B.verdict(fits["up"], fits["down"], main_s["sec_up"])
    v_sens = B.verdict(fits_sens["up"], fits_sens["down"], sens_s["sec_up"])
    # 참고(등록 밖, 판정에 쓰지 않음): 같은 DB 사고에 여러 ITS 기록이 맞은 경우 DB 사고 하나로 셈
    seen, dedup = set(), []
    for r in fitrows:
        k = (r["db_t"], r["db_route"], r["km"], r["dir"])
        if k not in seen:
            seen.add(k); dedup.append(r)
    dedup_s = summary(dedup)

    by_db_route = defaultdict(lambda: {"first": 0, "sec_up": 0, "sec_down": 0, "shift_windows": 0, "shift_up": 0, "shift_down": 0})
    for r in fitrows:
        x = by_db_route[r["db_route"]]
        x["first"] += 1; x["sec_up"] += r["sec_up"]; x["sec_down"] += r["sec_down"]
        x["shift_windows"] += r["shift_n"]; x["shift_up"] += r["shift_up"]; x["shift_down"] += r["shift_down"]
    db_counts = Counter(a["route"] for a in db)

    lp = [r["log_pred"] for r in fitrows]
    sr = surf["range"]
    extrap = {"blocked_gt2": sum(r["n_lanes"] > 2 for r in fitrows),
              "dur_outside": sum(not (sr["dur_min"][0] <= r["dur_min"] <= sr["dur_min"][1]) for r in fitrows),
              "volume_outside": sum(not (sr["demand"][0] <= r["volume"] <= sr["demand"][1]) for r in fitrows)}
    extrap["any_outside"] = sum((r["n_lanes"] > 2) or not (sr["dur_min"][0] <= r["dur_min"] <= sr["dur_min"][1])
                                or not (sr["demand"][0] <= r["volume"] <= sr["demand"][1]) for r in fitrows)
    route_table = []
    for key, rts in ROUTE_MAP.items():
        if names_its.get(key, 0) or names_elig.get(key, 0):
            route_table.append({"its_road_no": key[0], "its_road_name": key[1], "db_routes": rts,
                                "its_all": names_its.get(key, 0), "its_eligible": names_elig.get(key, 0)})
    route_table.sort(key=lambda x: -x["its_eligible"])
    unmapped_all = {f"{k[0]} {k[1]}": c for k, c in sorted(unmapped.items(), key=lambda kv: -kv[1])}
    out = {"prereg": "docs/sim-preregistration.md '## B 확장: 전국 노선' (2026-11-04 21:58)", "its_files": meta, "surface": surf,
           "route_map": route_table,
           "matching": {"its_highway_accidents": len(its_all), "its_eligible": len(eligible),
                        "its_eligible_unmapped": sum(unmapped.values()), "unmapped_names": unmapped_all,
                        "its_mapped": len(eligible) - sum(unmapped.values()),
                        "its_mapped_outside_db_years": out_years, "unmatched": unmatched,
                        "matched": sum(x["matched"] for x in per_route.values()),
                        "matched_route_without_END_dropped": dict(no_end), "first_accidents": len(rows),
                        "db_accidents_matched_more_than_once": sum(1 for c in used.values() if c > 1),
                        "median_abs_lag_min": statistics.median(abs(r["lag_min"]) for r in rows) if rows else None},
           "per_its_route": {k: dict(v) for k, v in sorted(per_route.items(), key=lambda kv: -kv[1]["its_eligible"])},
           "per_db_route": {k: dict(v, db_total=db_counts[k]) for k, v in sorted(by_db_route.items(), key=lambda kv: -kv[1]["first"])},
           "db_total": len(db), "db_routes_without_END": {k: c for k, c in db_counts.most_common() if k not in END},
           "volume": {"hourly": sum(r["vol_hourly"] for r in rows),
                      "route_daily_median": sum((not r["vol_hourly"]) and (not r["vol_overall_assumed"]) for r in rows),
                      "overall_median_assumed": sum(r["vol_overall_assumed"] for r in rows), "overall_median_value": overall_med},
           "pred_nonpositive_dropped": nonpos,
           "log_pred_summary": {"min": min(lp), "median": statistics.median(lp), "max": max(lp)} if lp else None,
           "extrapolation_counts": extrap,
           "samples": main_s, "fits": fits, "verdict": v,
           "sensitivity_dur_10_180": {"samples": sens_s, "fits": fits_sens, "verdict": v_sens},
           "reference_dedup_db_accident": {"note": "등록 밖 참고, 판정에 쓰지 않음", "samples": dedup_s},
           "rows": rows}
    (RES / "report_b_national.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (RES / "report_b_national.md").write_text(render(out), encoding="utf-8")
    print(render(out))


f3 = B.f3


def render(o):
    s, m, vv, sv = o["surface"], o["matching"], o["volume"], o["samples"]
    ss = o["sensitivity_dur_10_180"]["samples"]
    ds = o["reference_dedup_db_accident"]["samples"]
    ex = o["extrapolation_counts"]
    nf = sv["n_first"]
    L = ["# 탐색 분석 B 확장: 전국 노선 — 대리 지표와 2차 사고 (6.4절 탐색)", "",
         f"등록문: {o['prereg']}. 가설 검정이 아니라 탐색이다. 코드: surrogate_crash_national.py (B 의 예측면·로지스틱·판정 함수를 import).", "",
         f"**판정:** {o['verdict']}", "",
         f"보조(처리 시간 10~180분): {o['sensitivity_dur_10_180']['verdict']}", "",
         "## 1. 예측면 (B 와 같음: Krauss 경부선 4차로 기준선 'official', PC)", "",
         f"log(fast+1) = {s['coef'][0]:.3f} + {s['coef'][1]:.3f}·막힌 차로 + {s['coef'][2]:.4f}·처리 시간(분) + {s['coef'][3]:.6f}·교통량, "
         f"n = {s['n']}, R² = {f3(s['r2'])}. 모형 범위: 막힌 차로 {s['range']['blocked']}, 처리 시간 {f3(s['range']['dur_min'][0],2)}~{f3(s['range']['dur_min'][1],2)}분, "
         f"교통량 {s['range']['demand'][0]}~{s['range']['demand'][1]} 대/시.", "",
         "## 2. 표본과 맞춤", "",
         f"- ITS 파일 {o['its_files']['files']}개({o['its_files']['first']}~{o['its_files']['last']}, 읽지 못한 zip {len(o['its_files']['bad_zip'])}개). "
         f"고속국도 교통사고 {m['its_highway_accidents']}건, 그중 대상(종료 시각·본선 차단 차로 ≥1·진출입로 아님) {m['its_eligible']}건.",
         f"- 대응표에 없는 ITS 도로명 {m['its_eligible_unmapped']}건(뺌): " + (", ".join(f"{k} {c}" for k, c in list(m["unmapped_names"].items())[:15]) or "없음")
         + (" …" if len(m["unmapped_names"]) > 15 else "") + ".",
         f"- 대응된 ITS {m['its_mapped']}건 중 DB 연도(2023~2025) 밖 {m['its_mapped_outside_db_years']}건. DB({o['db_total']}건)와 노선·±10분으로 맞음 {m['matched']}건, "
         f"못 맞음 {m['unmatched']}건 → 맞춤률 {f3(m['matched'] / m['its_mapped'] if m['its_mapped'] else None)} "
         f"(DB 연도 안 기준 {f3(m['matched'] / (m['its_mapped'] - m['its_mapped_outside_db_years']) if m['its_mapped'] - m['its_mapped_outside_db_years'] else None)}).",
         f"- 맞았으나 상류 규칙(END)이 없는 DB 노선이라 뺀 것: " + (", ".join(f"{k} {c}" for k, c in m["matched_route_without_END_dropped"].items()) or "없음")
         + f". 첫 사고 {m['first_accidents']}건. |시차| 중앙값 {f3(m['median_abs_lag_min'],2)}분. 같은 DB 사고에 둘 이상 맞은 DB 사고 {m['db_accidents_matched_more_than_once']}건(B 처럼 그대로 둠).",
         f"- 교통량: 조사 노선의 시간대 값 {vv['hourly']}건, 조사 노선의 하루 중앙값 {vv['route_daily_median']}건, **전체 중앙값 가정({vv['overall_median_value']:.0f} 대/시) {vv['overall_median_assumed']}건**.",
         f"- 예측 상충 ≤ 0 이라 뺀 사고 {o['pred_nonpositive_dropped']}건. log(예측) 최소 {f3(o['log_pred_summary']['min']) if o['log_pred_summary'] else '—'}, "
         f"중앙 {f3(o['log_pred_summary']['median']) if o['log_pred_summary'] else '—'}, 최대 {f3(o['log_pred_summary']['max']) if o['log_pred_summary'] else '—'}.",
         f"- **예측면 외삽**(분석 {nf}건 중): 막힌 차로 3개 이상 {ex['blocked_gt2']}건, 처리 시간 범위 밖 {ex['dur_outside']}건, 교통량 범위 밖 {ex['volume_outside']}건, 하나라도 밖 {ex['any_outside']}건.", "",
         "### 2.1 노선명 대응표 (ITS 도로번호·도로명 → DB 노선명)", "",
         "| ITS 번호 | ITS 도로명 | DB 노선명 후보 | ITS 고속국도 사고 | 그중 대상 |", "|---|---|---|---|---|"]
    for x in o["route_map"]:
        L.append(f"| {x['its_road_no']} | {x['its_road_name']} | {', '.join(x['db_routes']) or '(DB 없음)'} | {x['its_all']} | {x['its_eligible']} |")
    L += ["", "### 2.2 노선별 ITS·DB·맞춤 (ITS 쪽, DB 후보 묶음 기준)", "",
          "| DB 노선 후보 | ITS 대상 | 그중 DB 연도 안 | DB 사고 | 맞음 | 맞춤률(연도 안) |", "|---|---|---|---|---|---|"]
    for k, x in o["per_its_route"].items():
        L.append(f"| {k} | {x['its_eligible']} | {x['its_in_db_years']} | {x['db_total']} | {x['matched']} | {f3(x['matched'] / x['its_in_db_years'] if x['its_in_db_years'] else None)} |")
    L += ["", "### 2.3 DB 노선별 첫 사고와 2차 사고 (분석 표본)", "",
          "| DB 노선 | DB 사고 | 첫 사고 | 상류 2차 | 하류 2차 | 시간 이동 창 | 이동 상류 | 이동 하류 |", "|---|---|---|---|---|---|---|---|"]
    for k, x in o["per_db_route"].items():
        L.append(f"| {k} | {x['db_total']} | {x['first']} | {x['sec_up']} | {x['sec_down']} | {x['shift_windows']} | {x['shift_up']} | {x['shift_down']} |")
    L += ["", "상류 규칙(END)이 없어 분석에서 빠지는 DB 노선과 DB 사고 수: " + ", ".join(f"{k} {c}" for k, c in o["db_routes_without_END"].items()) + ".", "",
          "### 2.4 합계", "",
          "| 집합 | 첫 사고 | 상류 2차(첫 사고 수) | 하류 2차 | 상류 비율 | 하류 비율 | 시간 이동 창 | 이동 상류 비율 | 이동 하류 비율 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for nm, x in (("전체(주)", sv), ("처리 10~180분", ss), ("참고: DB 사고 중복 제거(등록 밖)", ds)):
        L.append(f"| {nm} | {x['n_first']} | {x['sec_up']} | {x['sec_down']} | {f3(x['rate_up'])} | {f3(x['rate_down'])} | "
                 f"{x['shift_windows']} | {f3(x['shift_rate_up'])} | {f3(x['shift_rate_down'])} |")
    L += ["", f"(주 집합에서 상류 창에 든 DB 사고 수 합 {sv['sec_up_accidents']}, 하류 {sv['sec_down_accidents']}.)", "",
          "## 3. 로지스틱 회귀 — 상류 2차 사고 (주)", "",
          ("판정 규칙에 따라 30건 미만이면 적합 결과는 참고용 추정이다." if sv["sec_up"] < 30 else "")
          + " 시간대 더미 계수가 ±수십이고 CI 가 터진 것은 그 시간대에 사건이 0건이라 생긴 분리(추정 불가)이다.", "",
          B.fit_table(o["fits"]["up"]), "",
          "## 4. 같은 회귀 — 하류 대조", "", B.fit_table(o["fits"]["down"]), "",
          "## 5. 보조: 처리 시간 10~180분", "", "상류:", "", B.fit_table(o["sensitivity_dur_10_180"]["fits"]["up"]), "",
          "하류:", "", B.fit_table(o["sensitivity_dur_10_180"]["fits"]["down"]), "",
          "## 6. 가정과 한계", "",
          "- 예측면 전이: 예측면은 경부선 한 구간(4차로 직선) Krauss 모형이다. 다른 노선(2·3차로, 곡선·산지, 교통량 구성 차이)에 그대로 쓴다는 B 보다 더 강한 가정이 들어간다. "
          "2절의 외삽 수만큼은 모형 실행 범위 밖 로그-선형 외삽이다.",
          "- 노선명 대응의 불확실: ITS 도로명은 같은 노선이 'OO선'·'OO고속도로' 두 이름으로, DB 노선명은 'ㄱ·ㄷ' 접두 구간명으로 갈린다. "
          "번호 30(당진영덕)·12(광주대구·무안광주)·65(동해·부산포항)·20(익산포항)처럼 한 번호에 DB 노선이 여럿이면 후보 여러 개 중 시각이 가장 가까운 사고를 골라 "
          "다른 구간 사고와 잘못 맞을 수 있다. 대응표는 이름 목록만 보고 만들었고 좌표로 검증하지 않았다.",
          "- ITS 방향 미사용: 등록대로 ITS 방향을 쓰지 않고 노선·시각만으로 맞췄다. 같은 노선 같은 10분 안의 다른 방향·다른 지점 사고와 잘못 맞을 수 있고, "
          "위치(좌표·이정)도 보지 않았다. 방향·이정은 맞은 DB 사고의 값이다.",
          "- 기점 규칙의 가정: 상류는 evidence.py END 표(6.3절)로 정했다 — 남북 노선은 남쪽, 동서 노선은 서쪽이 기점이라 '종점 쪽 방향'이면 이정이 커진다는 가정. "
          "경부선만 검지기로 확인했고 나머지 노선은 확인하지 않았다. END 에 없는 노선(순환선·지선·영동선 등)은 상류를 정할 수 없어 뺐다(2.3절 아래 목록). "
          "규칙이 어느 노선에서 반대라면 그 노선의 상류·하류가 뒤바뀐다(하류 대조와 시간 이동 대조로 일부만 걸러짐).",
          "- 교통량: 경부선 외 조사 구간은 이정을 모르므로 '가장 가까운 값' 대신 그 노선·방향 조사 구간들의 같은 시간 값 중앙값을 썼다. 조사 방향 '기점/종점'은 "
          "END 기준 '종점 쪽 방향 = 종점'으로 읽었다(가정). 조사 노선이 없으면 전체 중앙값으로 가정했다(2절 건수). 07~10·18~21시 밖은 하루 중앙값(B 와 같음). 2025-12-31 한 시점 값을 모든 날에 썼다.",
          "- 같은 DB 사고에 여러 ITS 기록(예: '경부선'·'경부고속도로' 이중 기록)이 맞으면 B 처럼 그대로 두었다. 중복을 뺀 참고 합계를 2.4절에 함께 적었다(판정에 쓰지 않음).",
          "- 사고 DB 에 2차 사고 표시가 없어 상류 0~5 km·2시간 안의 사고를 2차 사고로 본다(6.3절 정의). 시간 이동 대조 비율이 배경 확률이다.",
          "- 신뢰구간은 왈드 95 % 구간, 뉴턴법 최대우도(B 와 같은 구현).", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
