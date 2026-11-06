"""검토 뒤 보강 실험 P1·P2·P3·P5·P6(c)·P7·P8 분석(PC 자료, 탐색; 판정 규칙은 P8 만) — 사전 고정
docs/sim-preregistration.md '## 검토 뒤 보강 실험 P1~P8'.
  python -X utf8 analyze_p.py [--main results/p_main.jsonl] [--p8 results/p8_comply.jsonl] [--out results/report_p]
  → results/report_p.json, results/report_p.md

입력
- p_main.jsonl(TAGO_AGG=1): 씨앗 1~24 × 기준선 official, 단계 official+tago12+relay, 일률 80 -u80, -u80right;
  none(false=True, 사고 없음); official-slack, official+tago12+relay-slack, -u80slack. 레코드 "agg":
  zone[12][n, Σv, Σv², n_wc, Σv_wc, Σv²_wc](500 m 칸, m/s), lanevar[12][Σ차로간 sd, n, Σ인접 최대 차, n](m/s),
  lanepos[6][차로][경고준수, 전체], road[23][n, Σv], brake{e25_all, e25_zone, e35_all, e35_zone, v25_all, v25_zone, veh},
  travel_grp{warned_comply:[n, 평균], other:[n, 평균]}.
- p8_comply.jsonl: TAGO_COMPLY=0.64,0.73,0.82 아래 official·단계·u80, 씨앗 1~24.
- data/gyeongbu_speed.csv.gz·data/gyeongbu_conzones.json(P5 VDS 평상시), data/accidents/accidents_2023_2025.csv(보조 행).
관례(analyze_e.py·analyze_p_existing.py 와 같음)
- 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균, 대조 0 인 씨앗 제외. 짝 차이 = 처리−대조의 씨앗별 평균.
- 부트스트랩: 씨앗 1~24 복원 추출 10,000회, random.Random("p"), 같은 재표본 행렬을 모든 칸에, 백분위 95 % CI(선형 보간).
- 윌콕슨: analyze.py 의 wil()(짝, 양측).
- 줄이 덜 써진 줄(json 오류)은 건너뛴다. 빠진 씨앗은 있는 것으로 계산하고 머리에 '부분 자료 — 확정 결과 아님'과 빠진 수를 적는다.
  파일이 없으면 그 절은 '자료 없음'.
"""
import argparse
import csv
import datetime as dt
import gzip
import json
import math
import random
import statistics
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
RES = HERE / "results"
DATA = HERE / "data"
SEEDS = list(range(1, 25))
N_BOOT = 10000
RNG_KEY = "p"
KMH = 3.6
METRICS = ("fast", "severe", "conflicts")
MNAME = {"fast": "고속 접근", "severe": "심각", "conflicts": "전체 상충"}
O = "official"
P = "official+tago12+relay"
MAIN = [(O, "base", "기준선(공식 안내)"), (P, "graded", "단계 90·70·50"), (P + "-u80", "u80", "일률 80"),
        (P + "-u80right", "u80right", "일률 80 + 오른쪽 차로(u80right)")]
SLACK = [("official-slack", "base_s", "기준선-slack"), (P + "-slack", "graded_s", "단계-slack"), (P + "-u80slack", "u80_s", "일률 80-slack")]
NONE = [("none", "none", "사고 없음(none, false)")]
P8S = [(O, "base", "기준선(공식 안내)"), (P, "graded", "단계 90·70·50"), (P + "-u80", "u80", "일률 80")]
NM = {k: n for _, k, n in MAIN + SLACK + NONE}
SLACK_OF = {"base_s": "base", "graded_s": "graded", "u80_s": "u80"}
ROAD_LO, ROAD_HI = 2, 18          # P5: 1 km 칸 번호 2~18(포함) = 2~19 km 지점(진입·종점 영향 밖)


# ---------------------------------------------------------------- 자료
def read_jsonl(path):
    """→ (레코드 목록, 파일 있음, 깨진 줄 수)"""
    p = Path(path)
    if not p.exists():
        return [], False, 0
    out, bad = [], 0
    for x in p.read_text(encoding="utf-8", errors="replace").splitlines():
        x = x.strip()
        if not x:
            continue
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            bad += 1
    return out, True, bad


def table(recs, sch, false=False, ov_ok=lambda ov: not ov, seeds=SEEDS):
    """키 -> 씨앗 -> 레코드(같은 것이 두 번이면 마지막)."""
    inv = {s: k for s, k, _ in sch}
    t = {}
    for r in recs:
        if r.get("scheme") not in inv or bool(r.get("false")) != false or r.get("seed") not in seeds or not ov_ok(r.get("ov") or {}):
            continue
        t.setdefault(inv[r["scheme"]], {})[r["seed"]] = r
    return t


def status_of(t, keys, seeds=SEEDS):
    st = {}
    for k in keys:
        rows = t.get(k, {})
        st[k] = {"n_seeds": len(rows), "missing": [s for s in seeds if s not in rows],
                 "truncated": sum(bool(r.get("truncated")) for r in rows.values()),
                 "no_agg": sum("agg" not in r for r in rows.values())}
    return st


# ---------------------------------------------------------------- 부트스트랩
class Boot:
    """씨앗별 값(None = 빠짐, 수, 또는 수 목록 = 씨앗 군집)을 모아 같은 재표본 행렬로 평균·CI.
    목록이면 평균 = 모든 값의 평균(쌍 가중), 재표본은 씨앗 단위(뽑힌 씨앗의 값 전부)."""

    def __init__(self, seeds=SEEDS, key=RNG_KEY):
        self.seeds, self.key = list(seeds), key
        self.vecs, self.res = {}, {}

    def add(self, key, vec):
        assert len(vec) == len(self.seeds)
        self.vecs[key] = vec
        return key

    def run(self):
        n = len(self.seeds)
        rng = random.Random(self.key)
        C = np.zeros((N_BOOT, n))
        for b in range(N_BOOT):
            for _ in range(n):
                C[b, rng.randrange(n)] += 1
        keys = list(self.vecs)
        if not keys:
            return
        S = np.zeros((len(keys), n))
        N = np.zeros((len(keys), n))
        for j, k in enumerate(keys):
            for i, v in enumerate(self.vecs[k]):
                vs = [] if v is None else [float(x) for x in v if x is not None] if isinstance(v, (list, tuple)) else [float(v)]
                vs = [x for x in vs if not math.isnan(x)]
                S[j, i], N[j, i] = sum(vs), len(vs)
        num, den = C @ S.T, C @ N.T
        with np.errstate(invalid="ignore", divide="ignore"):
            B = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
        for j, k in enumerate(keys):
            tot = N[j].sum()
            self.res[k] = {"mean": float(S[j].sum() / tot) if tot else None, "n_used": int((N[j] > 0).sum()),
                           "n_values": int(tot), "boot": B[:, j]}

    def get(self, key):
        r = self.res.get(key)
        if r is None or r["mean"] is None:
            return None
        b = r["boot"][~np.isnan(r["boot"])]
        return {"mean": r["mean"], "ci": ci(b), "n_used": r["n_used"], "n_values": r["n_values"]}

    def diff(self, a, b):
        ra, rb = self.res.get(a), self.res.get(b)
        if ra is None or rb is None or ra["mean"] is None or rb["mean"] is None:
            return None
        d = ra["boot"] - rb["boot"]
        d = d[~np.isnan(d)]
        return {"mean": ra["mean"] - rb["mean"], "ci": ci(d), "n_used": min(ra["n_used"], rb["n_used"])}


def ci(b):
    if len(b) == 0:
        return None
    s = np.sort(b)
    out = []
    for q in (0.025, 0.975):
        k = (len(s) - 1) * q
        i = int(k)
        out.append(float(s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)))
    return out


def vec(t, key, f, seeds=SEEDS):
    rows = t.get(key, {})
    out = []
    for s in seeds:
        r = rows.get(s)
        out.append(None if r is None else f(r))
    return out


def chg(a, c):
    return [None if (x is None or y is None or y == 0) else (x - y) / y * 100 for x, y in zip(a, c)]


def dif(a, c):
    return [None if (x is None or y is None) else x - y for x, y in zip(a, c)]


def quant(s, q):
    s = sorted(s)
    if not s:
        return None
    k = (len(s) - 1) * q
    i = int(math.floor(k))
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


# ---------------------------------------------------------------- 서식
def fpct(c, nd=1, sign=True):
    if c is None:
        return "자료 없음"
    sp = "+" if sign else ""
    m = f"{c['mean']:{sp}.{nd}f}"
    if c.get("ci") is None:
        return m
    return m + f" ({c['ci'][0]:{sp}.{nd}f} ~ {c['ci'][1]:{sp}.{nd}f})"


def fval(c, nd=1):
    return fpct(c, nd, sign=False)


def fnum(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


def has0(c):
    if c is None or c.get("ci") is None:
        return "—"
    return "포함" if c["ci"][0] <= 1e-9 and c["ci"][1] >= -1e-9 else "벗어남"


def jsonable(c):
    return None if c is None else {k: c[k] for k in ("mean", "ci", "n_used", "n_values") if k in c}


def head_status(name, st, expected, exists, bad):
    present = sum(v["n_seeds"] for v in st.values())
    miss = expected - present
    s = f"{name}: " + ("파일 없음" if not exists else f"{present}/{expected}개 실행, 빠짐 {miss}개, 깨진 줄 {bad}개")
    if exists:
        s += " (" + ", ".join(f"{k} {v['n_seeds']}" for k, v in st.items()) + ")"
        tr = sum(v["truncated"] for v in st.values())
        na = sum(v["no_agg"] for v in st.values())
        if tr:
            s += f", 잘린 실행 {tr}개(포함)"
        if na:
            s += f", agg 없는 레코드 {na}개(P1·P3·P5·P7 에서 빠짐)"
    return s, (miss if exists else expected)


# ---------------------------------------------------------------- P1 통계량
def _agg(r, k):
    a = r.get("agg")
    return None if not a else a.get(k)


def zsum(r, bins=None):
    z = _agg(r, "zone")
    if z is None:
        return None
    bins = range(len(z)) if bins is None else bins
    return [sum(z[b][i] for b in bins) for i in range(6)]


def sd_all(r, bins=None):
    s = zsum(r, bins)
    if s is None or s[0] == 0:
        return None
    m = s[1] / s[0]
    return math.sqrt(max(0.0, s[2] / s[0] - m * m)) * KMH


def sd_within(r):
    z = _agg(r, "zone")
    if z is None:
        return None
    n = sum(b[0] for b in z)
    if n == 0:
        return None
    w = sum(max(0.0, b[2] - b[1] * b[1] / b[0]) for b in z if b[0] > 0)   # Σ n_b·var_b
    return math.sqrt(w / n) * KMH


def wc_gap(r, bins=None):
    s = zsum(r, bins)
    if s is None:
        return None
    n, sv, nw, svw = s[0], s[1], s[3], s[4]
    if nw == 0 or n - nw == 0:
        return None
    return (svw / nw - (sv - svw) / (n - nw)) * KMH


def lane_ratio(r, i, j):
    lv = _agg(r, "lanevar")
    if lv is None:
        return None
    d = sum(b[j] for b in lv)
    return None if d == 0 else sum(b[i] for b in lv) / d * KMH


# ---------------------------------------------------------------- P5 VDS
def vds_normal(hours=(7, 8, 9)):
    zones = json.loads((DATA / "gyeongbu_conzones.json").read_text(encoding="utf-8"))
    zs = {z: e for z, e in zones.items() if e["dir"] == "S" and "기흥" in e["name"] and "수원신갈" in e["name"]}
    if not zs:
        return None
    rows = []
    with gzip.open(DATA / "gyeongbu_speed.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["zone"] in zs and int(r["hour"]) in hours:
                v = float(r["speed"])
                if v > 0:
                    rows.append((r["date"].replace("-", ""), int(r["hour"]), v))
    acc_days = set()
    afile = DATA / "accidents" / "accidents_2023_2025.csv"
    lo = min(min(e["from_km"], e["to_km"]) for e in zs.values())
    if afile.exists():
        with open(afile, encoding="cp949") as f:
            for r in csv.DictReader(f):
                try:
                    km = float(r["사고발생이정"])
                except ValueError:
                    continue
                if r["노선명"] == "경부선" and r["방향"] == "부산" and lo <= km <= 394.96:   # 콘존과 바로 위 콘존(신갈JC-수원신갈IC)
                    acc_days.add(r["사고일자"].replace("-", ""))
    wd = lambda d: dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() < 5

    def summ(vals):
        return None if not vals else {"n": len(vals), "median": statistics.median(vals), "q1": quant(vals, 0.25), "q3": quant(vals, 0.75),
                                      "mean": statistics.mean(vals)}
    days = sorted({d for d, _, _ in rows})
    sets = {
        "all": ("전체 날(사고 날 제외 안 함 — replay_obs.py 에 사고 날 제외 규칙이 없어 전체 날)", [v for _, _, v in rows]),
        "weekday": ("평일(월~금)만", [v for d, _, v in rows if wd(d)]),
        "weekday_noacc": ("평일, 2023~2025 중 같은 방향 이정 {:.2f}~394.96 km 사고가 없는 날".format(lo),
                          [v for d, _, v in rows if wd(d) and "2023" <= d[:4] <= "2025" and d not in acc_days]),
    }
    return {"zones": {z: e for z, e in zs.items()}, "hours": list(hours), "days": [days[0], days[-1]] if days else None,
            "n_days": len(days), "n_accident_days": len(acc_days),
            "sets": {k: {"label": lab, **(summ(v) or {"n": 0})} for k, (lab, v) in sets.items()}}


# ---------------------------------------------------------------- 본문
def main():
    from analyze import wil
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default=str(RES / "p_main.jsonl"))
    ap.add_argument("--p8", default=str(RES / "p8_comply.jsonl"))
    ap.add_argument("--out", default=str(RES / "report_p"))
    a = ap.parse_args()

    rm, has_m, bad_m = read_jsonl(a.main)
    r8, has_8, bad_8 = read_jsonl(a.p8)
    tm = table(rm, MAIN + SLACK)
    tn = table(rm, NONE, false=True)
    t8 = table(r8, P8S)
    st_m = status_of({**tm, **tn}, [k for _, k, _ in MAIN + NONE + SLACK])
    st_8 = status_of(t8, [k for _, k, _ in P8S])
    hm, miss_m = head_status(Path(a.main).name, st_m, 24 * 8, has_m, bad_m)
    h8, miss_8 = head_status(Path(a.p8).name, st_8, 24 * 3, has_8, bad_8)
    partial = (miss_m + miss_8) > 0
    MK = [k for _, k, _ in MAIN]
    SK = [k for _, k, _ in SLACK]

    bt = Boot()
    G = bt.get
    # P1
    P1F = {"sd": sd_all, "sdw": sd_within, "gap": wc_gap, "lsd": lambda r: lane_ratio(r, 0, 1), "ladj": lambda r: lane_ratio(r, 2, 3)}
    for k in MK:
        for fk, f in P1F.items():
            bt.add(("p1", k, fk), vec(tm, k, f))
            if k != "base":
                bt.add(("p1d", k, fk), dif(vec(tm, k, f), vec(tm, "base", f)))
        for b in range(12):
            bt.add(("p1z", k, "sd", b), vec(tm, k, lambda r, b=b: sd_all(r, [b])))
            bt.add(("p1z", k, "gap", b), vec(tm, k, lambda r, b=b: wc_gap(r, [b])))
    # P2
    tr = lambda r: r.get("travel")
    none_tr = vec(tn, "none", tr)
    tg = lambda grp: (lambda r: (_agg(r, "travel_grp") or {}).get(grp, [0, None])[1])
    for k in MK + SK:
        ref = "base" if k in MK else "base_s"
        bt.add(("p2raw", k), vec(tm, k, tr))
        if k != ref:
            bt.add(("p2chg", k), chg(vec(tm, k, tr), vec(tm, ref, tr)))
            bt.add(("p2dif", k), dif(vec(tm, k, tr), vec(tm, ref, tr)))
        bt.add(("p2delay", k), dif(vec(tm, k, tr), none_tr))
        bt.add(("p2wc", k), vec(tm, k, tg("warned_comply")))
        bt.add(("p2ot", k), vec(tm, k, tg("other")))
        bt.add(("p2gap", k), dif(vec(tm, k, tg("warned_comply")), vec(tm, k, tg("other"))))
    bt.add(("p2raw", "none"), none_tr)
    # P3
    def brate(key, scale=1000.0):
        def f(r):
            b = _agg(r, "brake")
            return None if not b or not b.get("veh") else b[key] / b["veh"] * scale
        return f
    P3F = [("e25_all", "≥0.25 g 사건/1,000대(전 구간)", brate("e25_all")), ("e25_zone", "≥0.25 g 사건/1,000대(전방 6 km)", brate("e25_zone")),
           ("e35_all", "≥0.35 g 사건/1,000대(전 구간)", brate("e35_all")), ("e35_zone", "≥0.35 g 사건/1,000대(전방 6 km)", brate("e35_zone")),
           ("v25_all", "≥0.25 g 급제동 차 비율 %(전 구간)", brate("v25_all", 100.0)), ("v25_zone", "≥0.25 g 급제동 차 비율 %(전방 6 km)", brate("v25_zone", 100.0))]
    for k in MK + SK:
        ref = "base" if k in MK else "base_s"
        for fk, _, f in P3F:
            bt.add(("p3", k, fk), vec(tm, k, f))
            if k != ref:
                bt.add(("p3chg", k, fk), chg(vec(tm, k, f), vec(tm, ref, f)))
    # P5
    def road_kmh(r, b):
        rd = _agg(r, "road")
        return None if rd is None or b >= len(rd) or rd[b][0] == 0 else rd[b][1] / rd[b][0] * KMH
    nroad = max((len(_agg(r, "road") or []) for r in tn.get("none", {}).values()), default=0)
    for b in range(nroad):
        bt.add(("p5bin", b), vec(tn, "none", lambda r, b=b: road_kmh(r, b)))

    def road_mid(r):
        vs = [road_kmh(r, b) for b in range(ROAD_LO, ROAD_HI + 1)]
        vs = [v for v in vs if v is not None]
        return statistics.mean(vs) if vs else None
    p5_mid = vec(tn, "none", road_mid)
    bt.add(("p5mid",), p5_mid)
    # P6(c)
    for met in METRICS:
        mf = lambda r, met=met: r.get(met)
        for k in SK:
            bt.add(("p6raw", k, met), vec(tm, k, mf))
        for k in ("graded_s", "u80_s"):
            bt.add(("p6c", k, met), chg(vec(tm, k, mf), vec(tm, "base_s", mf)))
        for k in SK:
            bt.add(("p6same", k, met), chg(vec(tm, k, mf), vec(tm, SLACK_OF[k], mf)))
    bt.add(("p6c", "u80_vs_graded", "fast"), chg(vec(tm, "u80_s", lambda r: r.get("fast")), vec(tm, "graded_s", lambda r: r.get("fast"))))
    # P8
    for met in METRICS:
        mf = lambda r, met=met: r.get(met)
        for k in ("base", "graded", "u80"):
            bt.add(("p8raw", k, met), vec(t8, k, mf))
        for k in ("graded", "u80"):
            bt.add(("p8chg", k, met), chg(vec(t8, k, mf), vec(t8, "base", mf)))
        bt.add(("p8ug", met), chg(vec(t8, "u80", mf), vec(t8, "graded", mf)))
    bt.run()

    # ---- P7(합산 비율, 부트스트랩 없음)
    p7 = {}
    for k in MK:
        for blk in (1, 2):
            rows = [r for r in tm.get(k, {}).values() if r.get("cond", {}).get("blocked") == blk and _agg(r, "lanepos")]
            if not rows:
                continue
            nl = len(_agg(rows[0], "lanepos")[0])
            cnt = [[[sum(_agg(r, "lanepos")[b][li][j] for r in rows) for j in (0, 1)] for li in range(nl)] for b in range(6)]
            p7[(k, blk)] = {"n_seeds": len(rows), "lanes": nl, "counts": cnt,
                            "share_wc": [[(c[0] / s if s else None) for c in cnt[b]] for b in range(6) for s in [sum(c[0] for c in cnt[b])]],
                            "share_all": [[(c[1] / s if s else None) for c in cnt[b]] for b in range(6) for s in [sum(c[1] for c in cnt[b])]]}
    # ---- P8 검정
    tab8 = {s: {k: t8[k][s] for k in ("graded", "u80") if s in t8.get(k, {})} for s in SEEDS}
    n8 = sum(1 for d in tab8.values() if len(d) == 2)
    p8_p = wil(tab8, "u80", "graded", "fast") if n8 else None
    ug = G(("p8ug", "fast"))
    if p8_p is None or ug is None or ug["ci"] is None:
        p8_verdict = "자료 없음"
    elif p8_p < 0.05 and ug["ci"][1] < 0:
        p8_verdict = "국내 준수율에서도 지지"
    elif p8_p < 0.05 and ug["ci"][0] > 0:
        p8_verdict = "지지 안 됨(반대 방향: 일률 80 > 단계)"
    else:
        p8_verdict = "지지 안 됨(p ≥ 0.05 또는 CI 가 0 포함)"
    # ---- P5 VDS
    vds = vds_normal()
    mids = [v for v in p5_mid if v is not None]
    p5_sim = None if not mids else {"n": len(mids), "mean": statistics.mean(mids), "q1": quant(mids, 0.25), "q3": quant(mids, 0.75),
                                    "sd": statistics.pstdev(mids), "ci": (G(("p5mid",)) or {}).get("ci")}
    p5_judge = {}
    if vds and p5_sim:
        for sk, s in vds["sets"].items():
            if s.get("n"):
                m = p5_sim["mean"]
                p5_judge[sk] = "부합" if s["q1"] <= m <= s["q3"] else (f"밖(실측 Q3 보다 {m - s['q3']:+.1f} km/h)" if m > s["q3"] else f"밖(실측 Q1 보다 {m - s['q1']:+.1f} km/h)")

    # ---------------------------------------------------------------- JSON
    out = {"note": "탐색(판정 규칙은 P8 만). 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균, 대조 0 씨앗 제외. 짝 차이 = 처리−대조 씨앗 평균. "
                   '95 % CI = 씨앗 1~24 복원 추출 10,000회, random.Random("p"), 모든 칸 같은 재표본, 백분위. 속도 km/h.',
           "inputs": {"main": a.main, "p8": a.p8, "main_exists": has_m, "p8_exists": has_8},
           "status": {"main": st_m, "p8": st_8, "bad_lines": {"main": bad_m, "p8": bad_8}}, "partial": partial,
           "missing": {"main": miss_m, "p8": miss_8}, "n_boot": N_BOOT, "rng": f'random.Random("{RNG_KEY}")',
           "cells": {"|".join(map(str, k)): jsonable(G(k)) for k in bt.vecs},
           "p5": {"sim_mid_bins": [ROAD_LO, ROAD_HI], "sim": p5_sim, "vds": vds, "judge": p5_judge},
           "p7": {f"{k}|{b}": v for (k, b), v in p7.items()},
           "p8": {"wilcoxon_u80_vs_graded_fast_p": p8_p, "n_pairs": n8, "u80_vs_graded_fast": jsonable(ug), "verdict": p8_verdict}}
    stem = Path(a.out)

    # ---------------------------------------------------------------- MD
    L = ["# 검토 뒤 보강 실험 P1·P2·P3·P5·P6(c)·P7·P8 분석 (PC, 탐색)", "",
         "실행: `python -X utf8 analyze_p.py` (server/link/sim 에서; 입력 " + f"`{Path(a.main).name}`, `{Path(a.p8).name}`)", "",
         f"**자료 상태: {hm}; {h8}."
         + (f" 부분 자료 — 확정 결과 아님(빠진 실행 {miss_m + miss_8}개).**" if partial else " 모두 갖춰짐.**"), "",
         "변화율 % = (처리−대조)/대조×100 의 씨앗별 평균(음수 = 감소), 대조 0 인 씨앗 제외. 짝 차이 = 처리−대조의 씨앗별 평균. "
         f"괄호는 부트스트랩 95 % CI(씨앗 1~24 복원 추출 {N_BOOT:,}회, random.Random(\"{RNG_KEY}\"), 모든 칸 같은 재표본, 백분위). "
         "부분 자료에서는 있는 씨앗만 쓴다(칸마다 n 이 다를 수 있음). 속도는 km/h. 판정 규칙은 P8 하나, 나머지는 서술.", ""]
    no_main = not has_m
    nodata = ["자료 없음.", ""]

    # P1
    L += ["## P1 속도 분산(사고 처리 중, 사고 지점 전방 6 km, 10 s 마다)", ""]
    if no_main or not any(G(("p1", k, "sd")) for k in MK):
        L += nodata
    else:
        L += ["(i) 전체 차 속도 표준편차 = 12칸 n 가중 합산 sqrt(Σv²/n − (Σv/n)²)(칸·시점 가중); 칸 안 표준편차 = sqrt(Σ n_b·var_b / Σ n_b). "
              "(ii) 경고 준수 차 평균 − 나머지 차 평균(나머지 = 전체 − 경고 준수). (iii) 차로 간 표준편차 평균 = Σ차로간 sd / Σn. (iv) 인접 차로 최대 차 평균.", "",
              "### 표 P1-1. 방식별 값(씨앗 평균)", "",
              "| 방식 | (i) 전체 sd | 칸 안 sd | (ii) 준수 − 나머지 | (iii) 차로 간 sd | (iv) 인접 차로 최대 차 |", "|---|---|---|---|---|---|"]
        for k in MK:
            L.append(f"| {NM[k]} | " + " | ".join(fval(G(("p1", k, f)), 2) if f != "gap" else fpct(G(("p1", k, f)), 2) for f in P1F) + " |")
        L += ["", "### 표 P1-2. 기준선 대비 짝 차이(km/h)", "",
              "| 방식 | (i) 전체 sd | 칸 안 sd | (ii) 준수 − 나머지 | (iii) 차로 간 sd | (iv) 인접 차로 최대 차 |", "|---|---|---|---|---|---|"]
        for k in MK[1:]:
            L.append(f"| {NM[k]} | " + " | ".join(fpct(G(("p1d", k, f)), 2) for f in P1F) + " |")
        for fk, lab in (("sd", "(i) 칸별 전체 차 속도 표준편차"), ("gap", "(ii) 칸별 경고 준수 − 나머지 평균 속도 차")):
            L += ["", f"### 표 P1-{3 if fk == 'sd' else 4}. {lab}(500 m 칸, 사고 지점에서 상류 거리)", "",
                  "| 칸(m) | " + " | ".join(NM[k] for k in MK) + " |", "|---|" + "---|" * len(MK)]
            for b in range(12):
                L.append(f"| {b * 500}–{(b + 1) * 500} | " + " | ".join(fpct(G(("p1z", k, fk, b)), 1, sign=(fk == "gap")) for k in MK) + " |")
        def order_ok(fk, absval):
            v = {k: (G(("p1", k, fk)) or {}).get("mean") for k in ("graded", "u80", "base")}
            if any(x is None for x in v.values()):
                return "판단 불가(값 없음)", v
            f = (lambda x: abs(x)) if absval else (lambda x: x)
            return ("맞음" if f(v["graded"]) > f(v["u80"]) > f(v["base"]) else "아님"), v
        o1, v1 = order_ok("sd", False)
        o2, v2 = order_ok("gap", True)
        L += ["", f"사전 기대(단계 > 일률 80 > 기준선): (i) 속도 표준편차 {o1} "
              f"({fnum(v1['graded'], 2)} / {fnum(v1['u80'], 2)} / {fnum(v1['base'], 2)}), (ii) 준수–나머지 속도 차의 크기(|값|) {o2} "
              f"({fnum(v2['graded'], 2)} / {fnum(v2['u80'], 2)} / {fnum(v2['base'], 2)}).", ""]
        out["p1_expectation"] = {"sd": o1, "gap_abs": o2}

    # P2
    L += ["## P2 통행 시간·지체", ""]
    if no_main:
        L += nodata
    else:
        L += ["travel = 사고 300 s 전부터 처리 끝까지 출발해 도착한 차의 평균 통행 시간(s). 대조 = 같은 씨앗의 기준선(slack 방식은 official-slack). "
              "지체 = travel − 같은 씨앗 none(사고 없음) travel 의 씨앗 평균.", "",
              "### 표 P2-1. 통행 시간·지체", "",
              "| 방식 | travel(s) | 대조 대비 % | 차이(s) | 지체(s) |", "|---|---|---|---|---|"]
        for k in MK + SK:
            ref = "base" if k in MK else "base_s"
            L.append(f"| {NM[k]} | {fval(G(('p2raw', k)))} | " + ("대조" if k == ref else fpct(G(("p2chg", k)), 2)) + " | "
                     + ("—" if k == ref else fpct(G(("p2dif", k)))) + f" | {fpct(G(('p2delay', k)))} |")
        L.append(f"| {NM['none']} | {fval(G(('p2raw', 'none')))} | — | — | 0 |")
        L += ["", "### 표 P2-2. 경고 준수 차 대 나머지 차 평균 통행 시간(s, 방식별 씨앗 평균)", "",
              "| 방식 | 경고 준수 차 | 나머지 차 | 준수 − 나머지(짝) |", "|---|---|---|---|"]
        for k in MK + SK:
            L.append(f"| {NM[k]} | {fval(G(('p2wc', k)))} | {fval(G(('p2ot', k)))} | {fpct(G(('p2gap', k)))} |")
        L.append("")

    # P3
    L += ["## P3 급제동(사고 뒤, 감속도 상승 에지)", ""]
    if no_main or not any(G(("p3", k, "e25_all")) for k in MK):
        L += nodata
    else:
        L += ["출발 차 1,000대당 사건 수(veh = 출발 차 수), 급제동 차 비율 = 그런 차 수/출발 차 수 ×100. 문헌(표 1, Sakhare 외: 대기열 경고 뒤 급제동 사건 약 80 % 감소)은 "
              "경고 트럭 차량군의 차내 기록, 여기는 전 차량·시뮬레이션이라 정의가 다르다.", "",
              "### 표 P3-1. 방식별 값", "", "| 지표 | " + " | ".join(NM[k] for k in MK + SK) + " |", "|---|" + "---|" * len(MK + SK)]
        for fk, lab, _ in P3F:
            L.append(f"| {lab} | " + " | ".join(fval(G(("p3", k, fk)), 2) for k in MK + SK) + " |")
        L += ["", "### 표 P3-2. 대조 대비 변화율 %(slack 방식은 official-slack 대비)", "",
              "| 지표 | " + " | ".join(NM[k] for k in MK[1:] + SK[1:]) + " |", "|---|" + "---|" * len(MK[1:] + SK[1:])]
        for fk, lab, _ in P3F:
            L.append(f"| {lab} | " + " | ".join(fpct(G(("p3chg", k, fk))) for k in MK[1:] + SK[1:]) + " |")
        L += ["", "참고: 문헌 급제동 사건 변화율 약 −80 %(Sakhare 외) — 위 표 P3-2 의 사건 수 변화율과 같은 단위.", ""]

    # P5
    L += ["## P5 사고 없는 흐름 보정(none, false)", ""]
    if no_main or not nroad:
        L += ["시뮬레이션 자료 없음.", ""]
    else:
        L += [f"1 km 칸 평균 속도(사고 시각 뒤 10 s 마다 n 가중). 칸 {ROAD_LO}~{ROAD_HI}(= {ROAD_LO}~{ROAD_HI + 1} km 지점) 평균 = 칸 평균 속도들의 단순 평균(씨앗별).", "",
              "### 표 P5-1. 칸별 평균 속도(km/h)", "", "| 칸(km) | 씨앗 평균 (CI) | 씨앗 간 표준편차 | n |", "|---|---|---|---|"]
        for b in range(nroad):
            vs = [v for v in vec(tn, "none", lambda r, b=b: road_kmh(r, b)) if v is not None]
            L.append(f"| {b}–{b + 1} | {fval(G(('p5bin', b)))} | {fnum(statistics.pstdev(vs) if len(vs) > 1 else None)} | {len(vs)} |")
        if p5_sim:
            L += ["", f"칸 {ROAD_LO}~{ROAD_HI} 평균(씨앗 {p5_sim['n']}개): 평균 {p5_sim['mean']:.1f} km/h"
                  + (f" (CI {p5_sim['ci'][0]:.1f} ~ {p5_sim['ci'][1]:.1f})" if p5_sim["ci"] else "")
                  + f", Q1~Q3 {p5_sim['q1']:.1f}~{p5_sim['q3']:.1f}, 씨앗 간 표준편차 {p5_sim['sd']:.2f}.", ""]
    if vds:
        zn = ", ".join(f"{z} {e['name']}({e['from_km']}→{e['to_km']} km)" for z, e in vds["zones"].items())
        L += ["### 표 P5-2. VDS 평상시 속도(경부선 하행 = 부산행 = 교통량 '기점' 방향, 07·08·09시, 1시간 구간통행속도)", "",
              f"콘존: {zn}. 자료 기간 {vds['days'][0]}~{vds['days'][1]}({vds['n_days']}일). 0 은 결측(이미 제외). 관측 = 날짜 × 시간 값을 모두 모은 분포.", "",
              "| 표본 | 관측 수 | 중앙값 | Q1~Q3 | 시뮬레이션 판정 |", "|---|---|---|---|---|"]
        for sk, s in vds["sets"].items():
            L.append(f"| {s['label']} | {s['n']} | {fnum(s.get('median'))} | {fnum(s.get('q1'))}~{fnum(s.get('q3'))} | {p5_judge.get(sk, '시뮬레이션 자료 없음')} |")
        L += ["", "판정 기준(사전 등록): 시뮬레이션 씨앗 평균이 실측 Q1~Q3 안이면 '부합'. 주 판정 = 첫 행(replay_obs.py 에 사고 날 제외 규칙이 없어 전체 날); "
              "아래 두 행은 보조(평일·사고 없는 날, 사고 목록 = data/accidents/accidents_2023_2025.csv 경부선 '부산' 방향).", ""]
    else:
        L += ["VDS 자료 없음.", ""]

    # P6(c)
    L += ["## P6(c) 부분 준수(slack: 준수 차가 권고 +10 km/h)", ""]
    if no_main or not any(G(("p6raw", k, "fast")) for k in SK):
        L += nodata
    else:
        L += ["### 표 P6c-1. slack 방식의 지표 평균", "", "| 방식 | " + " | ".join(MNAME[m] for m in METRICS) + " |", "|---|" + "---|" * len(METRICS)]
        for k in SK:
            L.append(f"| {NM[k]} | " + " | ".join(fval(G(("p6raw", k, m))) for m in METRICS) + " |")
        L += ["", "### 표 P6c-2. official-slack 대비 변화율 %", "", "| 방식 | " + " | ".join(MNAME[m] for m in METRICS) + " |", "|---|" + "---|" * len(METRICS)]
        for k in ("graded_s", "u80_s"):
            L.append(f"| {NM[k]} | " + " | ".join(fpct(G(("p6c", k, m))) for m in METRICS) + " |")
        L += ["", f"일률 80-slack 대 단계-slack, 고속 접근 변화율: {fpct(G(('p6c', 'u80_vs_graded', 'fast')))}.", "",
              "### 표 P6c-3. 같은 방식의 원 결과(P1 재실행) 대비 변화율 %", "", "| 비교 | " + " | ".join(MNAME[m] for m in METRICS) + " |", "|---|" + "---|" * len(METRICS)]
        for k in SK:
            L.append(f"| {NM[k]} 대 {NM[SLACK_OF[k]]} | " + " | ".join(fpct(G(("p6same", k, m))) for m in METRICS) + " |")
        L.append("")

    # P7
    L += ["## P7 차로 분포(처리 중, 1 km 칸 × 차로, 24씨앗 합산 비율)", ""]
    if not p7:
        L += nodata
    else:
        L += ["차로 번호 0 = 가장 오른쪽. 차단 차로 = 0 … 차단 수−1, 의도된 '가장 오른쪽 개방 차로' = 차로 번호 = 차단 수. 비율 = 그 칸 안 차로별 수 / 칸 합.", ""]
        verdict = []
        for (k, blk), v in sorted(p7.items(), key=lambda kv: (MK.index(kv[0][0]), kv[0][1])):
            nl = v["lanes"]
            L += [f"### 표 P7. {NM[k]}, 차단 {blk}차로(씨앗 {v['n_seeds']}개)", "",
                  "| 칸(km) | " + " | ".join(f"준수 차로{li}" for li in range(nl)) + " | " + " | ".join(f"전체 차로{li}" for li in range(nl)) + " |",
                  "|---|" + "---|" * (2 * nl)]
            for b in range(6):
                L.append(f"| {b}–{b + 1} | " + " | ".join("—" if x is None else f"{x:.2f}" for x in v["share_wc"][b]) + " | "
                         + " | ".join("—" if x is None else f"{x:.2f}" for x in v["share_all"][b]) + " |")
            L.append("")
            if k == "u80right":
                ok = [b for b in range(6) if all(x is not None for x in v["share_wc"][b]) and max(range(nl), key=lambda li: v["share_wc"][b][li]) == blk]
                have = [b for b in range(6) if all(x is not None for x in v["share_wc"][b])]
                verdict.append(f"차단 {blk}: 준수 차 최다 차로 = 차로{blk} 인 칸 {len(ok)}/{len(have)}({', '.join(f'{b}–{b + 1} km' for b in ok) or '없음'})")
        if verdict:
            L += ["u80right 의도(준수 차가 차로 번호 = 차단 수에 모임) 거리별 성립: " + "; ".join(verdict)
                  + ". 모든 칸에서 성립하지 않으면 사전 등록 규칙대로 구현 오류 후보로 적는다.", ""]
        out["p7_u80right"] = verdict

    # P8
    L += ["## P8 국내 준수율(TAGO_COMPLY=0.64,0.73,0.82)", ""]
    if not has_8 or not t8:
        L += nodata
    else:
        L += ["### 표 P8-1. 지표 평균과 기준선 대비 변화율 %", "",
              "| 방식 | " + " | ".join(f"{MNAME[m]} 평균 | {MNAME[m]} 변화율" for m in METRICS) + " |", "|---|" + "---|---|" * len(METRICS)]
        for k in ("base", "graded", "u80"):
            L.append(f"| {NM[k]} | " + " | ".join(f"{fval(G(('p8raw', k, m)))} | " + ("—" if k == "base" else fpct(G(("p8chg", k, m)))) for m in METRICS) + " |")
        L += ["", "### 표 P8-2. 일률 80 대 단계 변화율 %", "", "| " + " | ".join(MNAME[m] for m in METRICS) + " |", "|" + "---|" * len(METRICS),
              "| " + " | ".join(fpct(G(("p8ug", m))) for m in METRICS) + " |", "",
              f"검정(고속 접근, 일률 80 대 단계, 짝 윌콕슨 양측, 짝 {n8}개): p = {fnum(p8_p, 4)}; 변화율 CI 0 {has0(ug)}. "
              f"**판정: {p8_verdict}**(규칙: p < 0.05 이고 단계 대비 고속 접근 변화율 CI 가 0 을 포함하지 않음; 가설 방향 일률 80 < 단계).", ""]
    stem.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    stem.with_suffix(".md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ {stem.with_suffix('.json')}, {stem.with_suffix('.md')}" + (" (부분 자료)" if partial else ""))


if __name__ == "__main__":
    main()
