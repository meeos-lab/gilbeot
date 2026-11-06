"""관점 확장 E1(모형 연결)·E2~E6 분석(탐색, 판정 규칙은 E3 만) — 사전 고정 docs/sim-preregistration.md
'## 관점 확장 E1~E8' 과 그 아래 'E2~E5 구현 기록'.
  python -X utf8 analyze_e.py [--main results/e_main.jsonl] [--delay results/e_delay.jsonl] [--out results/report_e]
  → results/report_e.json, results/report_e.md

입력
- e_main.jsonl: 씨앗 1~24 × 여섯 방식(기준선 official, 단계, -u80, -sham, -u80tail, -u80right), 공식 지연 779 s.
- e_delay.jsonl: 씨앗 1~24 × 세 방식(기준선·단계·u80), 공식 지연 = ITS–DB 경험 분포에서 씨앗마다 하나(E1).
- 레코드의 쌍 요약 pairs(또는 pairs_e): by_f[집단] = [전체, 고속, 심각](뒤차 기준), phase[a|b|c], ke_MJ, veh_exp[집단].
  쌍 파일 results/pairs/*.json.gz 는 요약 검산(뒤차 집단별 수·단계별 수·KE)에만 쓴다.
관례(analyze_c.py·analyze_c_pairs.py 와 같음)
- 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균, 대조 0 인 씨앗은 제외. 비율·상충률도 씨앗별 값의 평균.
- 부트스트랩: 씨앗 1~24 복원 추출 10,000회, random.Random("e"), 같은 재표본(같은 추출 행렬)을 모든 칸에 적용,
  백분위 95 % CI(선형 보간 = analyze_c.pct). 재표본에 쓸 수 있는 씨앗이 하나도 없으면 그 재표본은 그 칸에서 뺀다.
- 두 평균의 차이(E1 의 '경험 지연 효과 − 779 s 효과')는 재표본마다 두 평균을 다시 계산해 뺀 분포로 CI.
- 잘린 실행(truncated)은 수를 보고하고 포함. 줄이 덜 써진 마지막 줄은 건너뛴다(생성 중인 파일).
부분 자료(빠진 씨앗이 있으면)는 있는 씨앗으로 계산하고 머리에 '부분 자료 — 확정 결과 아님'을 적는다.
"""
import argparse
import gzip
import json
import math
import random
import statistics
from itertools import combinations
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
RES = HERE / "results"
SEEDS = list(range(1, 25))
N_BOOT = 10000
RNG_KEY = "e"
METRICS = ("fast", "severe", "conflicts")
MNAME = {"fast": "고속 접근", "severe": "심각", "conflicts": "전체 상충"}
MI = {"conflicts": 0, "fast": 1, "severe": 2}          # by_f·phase 리스트 안 위치 [전체, 고속, 심각]
BASE = "official"
P = "official+tago12+relay"
SCH = [  # (스킴, 키, 이름)
    (BASE, "base", "기준선(공식 안내)"),
    (P, "graded", "단계 90·70·50"),
    (P + "-u80", "u80", "일률 80"),
    (P + "-sham", "sham", "가짜 경고(sham)"),
    (P + "-u80tail", "u80tail", "일률 80, 정체 소멸까지(u80tail)"),
    (P + "-u80right", "u80right", "일률 80 + 오른쪽 차로(u80right)"),
]
KEYS = [k for _, k, _ in SCH]
SC = {k: s for s, k, _ in SCH}
NM = {k: n for _, k, n in SCH}
DELAY_KEYS = ["base", "graded", "u80"]
GROUPS = [("app_c", "앱 준수(a1c1)", ("a1c1",)), ("app_nc", "앱 비준수(a1c0)", ("a1c0",)),
          ("nonapp", "비앱(a0*)", ("a0c0", "a0c1")), ("all", "전체", ("a0c0", "a0c1", "a1c0", "a1c1"))]
# 집단 상충률의 기준선 대조: 기준선에는 앱 차량이 없다(보급 0). 앱 여부는 출발 때 준수 성향과 독립으로 뽑히고
# 두 성향은 방식과 무관하게 같은 난수 순서로 뽑히므로(tago_sim.py 272~273행), 각 집단의 반사실 대조는
# 기준선에서 같은 준수 성향을 가진 차 전체: 앱 준수 → 기준선 a0c1, 앱 비준수 → 기준선 a0c0, 비앱·전체 → 기준선 전체.
GROUP_BASE = {"app_c": ("a0c1",), "app_nc": ("a0c0",), "nonapp": ("a0c0", "a0c1"), "all": ("a0c0", "a0c1", "a1c0", "a1c1")}
SHARES = [("nonapp", "뒤차 비앱(a0*)", lambda g: g.startswith("a0")),
          ("noncomply", "뒤차 비준수(*c0)", lambda g: g.endswith("c0")),
          ("nonapp_noncomply", "뒤차 비앱·비준수(a0c0)", lambda g: g == "a0c0")]


# ---------------------------------------------------------------- 자료
def load(path):
    t = {}  # 키 -> 씨앗 -> 레코드(같은 씨앗·스킴이 두 번 있으면 마지막 것)
    inv = {s: k for s, k, _ in SCH}
    p = Path(path)
    if not p.exists():
        return t, False
    for x in p.read_text(encoding="utf-8").splitlines():
        x = x.strip()
        if not x:
            continue
        try:
            r = json.loads(x)
        except json.JSONDecodeError:
            continue
        if r.get("false") or r.get("ov") or r.get("scheme") not in inv or r.get("seed") not in SEEDS:
            continue
        t.setdefault(inv[r["scheme"]], {})[r["seed"]] = r
    return t, True


def psum(r):
    for k in ("pairs_e", "pairs"):
        v = r.get(k)
        if isinstance(v, dict) and "by_f" in v:
            return v
    return None


def by_f(r, groups, met):
    s = psum(r)
    return None if s is None else sum(s["by_f"].get(g, [0, 0, 0])[MI[met]] for g in groups)


def veh_exp(r, groups):
    s = psum(r)
    return None if s is None else sum(s["veh_exp"].get(g, 0) for g in groups)


def check_pairs(r):
    """쌍 파일로 요약 검산. 반환: None(파일 없음) 또는 불일치 목록."""
    s = psum(r)
    if s is None or not s.get("file"):
        return None
    fn = RES / s["file"]
    if not fn.exists():
        return None
    d = json.load(gzip.open(fn, "rt", encoding="utf-8"))
    ci = {c: i for i, c in enumerate(d["cols"])}
    bf, ph, ke = {}, {"a": [0, 0, 0], "b": [0, 0, 0], "c": [0, 0, 0]}, 0.0
    for w in d["rows"]:
        g = "crash" if w[ci["f_app"]] is None else f"a{w[ci['f_app']]}c{w[ci['f_comply']]}"
        inc = [1, w[ci["fast"]], w[ci["severe"]]]
        bf[g] = [a + b for a, b in zip(bf.get(g, [0, 0, 0]), inc)]
        ph[w[ci["phase"]]] = [a + b for a, b in zip(ph[w[ci["phase"]]], inc)]
        ke += 0.5 * (15000.0 if w[ci["f_truck"]] else 1500.0) * w[ci["dv_max_ms"]] ** 2 / 1e6
    bad = []
    if {k: v for k, v in bf.items()} != {k: v for k, v in s["by_f"].items()}:
        bad.append("by_f")
    if ph != s["phase"]:
        bad.append("phase")
    if abs(ke - s["ke_MJ"]["all"]) > 0.05 + 1e-4 * abs(ke):   # 파일의 dv 는 3자리 반올림
        bad.append(f"ke({ke:.2f}≠{s['ke_MJ']['all']:.2f})")
    tot = [sum(v[i] for v in s["by_f"].values()) for i in range(3)]
    if tot != [r["conflicts"], r["fast"], r["severe"]]:
        bad.append("by_f 합≠지표")
    return bad


# ---------------------------------------------------------------- 부트스트랩
class Boot:
    """씨앗별 벡터(길이 24, None = 빠짐)를 모아 같은 재표본으로 한 번에 평균·CI."""

    def __init__(self):
        self.vecs = {}
        self.res = {}

    def add(self, key, vec):
        self.vecs[key] = vec
        return key

    def run(self):
        rng = random.Random(RNG_KEY)
        C = np.zeros((N_BOOT, len(SEEDS)))
        for b in range(N_BOOT):
            for _ in SEEDS:
                C[b, rng.randrange(len(SEEDS))] += 1
        keys = list(self.vecs)
        if not keys:
            return
        V = np.array([[np.nan if v is None else float(v) for v in self.vecs[k]] for k in keys])
        M = ~np.isnan(V)
        num = C @ np.where(M, V, 0.0).T
        den = C @ M.T.astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            B = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
        for j, k in enumerate(keys):
            vals = [v for v in self.vecs[k] if v is not None]
            self.res[k] = {"mean": (sum(vals) / len(vals)) if vals else None, "n_used": len(vals), "boot": B[:, j]}

    def get(self, key):
        r = self.res.get(key)
        if r is None or r["mean"] is None:
            return None
        b = r["boot"][~np.isnan(r["boot"])]
        return {"mean": r["mean"], "ci": ci(b), "n_used": r["n_used"]}

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


def vec(t, key, f):
    rows = t.get(key, {})
    out = []
    for s in SEEDS:
        r = rows.get(s)
        v = None if r is None else f(r)
        out.append(v)
    return out


def chg_vec(tt, kt, tc, kc, f):
    """씨앗별 변화율(처리 tt[kt] 대 대조 tc[kc]), 대조 0·빠짐은 None."""
    a, c = vec(tt, kt, f), vec(tc, kc, f)
    return [None if (x is None or y is None or y == 0) else (x - y) / y * 100 for x, y in zip(a, c)]


def quant(s, q):
    s = sorted(s)
    k = (len(s) - 1) * q
    i = int(math.floor(k))
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


# ---------------------------------------------------------------- 서식
def fpct(c, nd=1, sign=True):
    if c is None:
        return "자료 없음"
    sp = "+" if sign else ""
    m = f"{c['mean']:{sp}.{nd}f}"
    if c["ci"] is None:
        return m
    return m + f" ({c['ci'][0]:{sp}.{nd}f} ~ {c['ci'][1]:{sp}.{nd}f})"


def fval(c, nd=1):
    return fpct(c, nd, sign=False)


def fnum(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


def has0(c):
    if c is None or c["ci"] is None:
        return "—"
    return "포함" if c["ci"][0] <= 1e-9 and c["ci"][1] >= -1e-9 else "벗어남"


def jsonable(c):
    return None if c is None else {"mean": c["mean"], "ci": c["ci"], "n_used": c["n_used"]}


# ---------------------------------------------------------------- 본문
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default=str(RES / "e_main.jsonl"))
    ap.add_argument("--delay", default=str(RES / "e_delay.jsonl"))
    ap.add_argument("--out", default=str(RES / "report_e"))
    a = ap.parse_args()
    tm, has_m = load(a.main)
    td, has_d = load(a.delay)
    bt = Boot()
    out = {"note": "탐색. 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균(음수 = 감소), 대조 0 씨앗 제외. "
                   "비율·상충률은 씨앗별 값의 평균. 95 % CI = 씨앗 1~24 복원 추출 부트스트랩 10,000회 백분위, "
                   'random.Random("e"), 모든 칸 같은 재표본.',
           "inputs": {"main": a.main, "delay": a.delay, "delay_exists": has_d}, "n_boot": N_BOOT,
           "rng": f'random.Random("{RNG_KEY}")'}

    # ---- 자료 상태
    status = {}
    for fname, t, keys in (("main", tm, KEYS), ("delay", td, DELAY_KEYS)):
        st = {}
        for k in keys:
            rows = t.get(k, {})
            chk = [check_pairs(r) for r in rows.values()]
            st[k] = {"n_seeds": len(rows), "missing": [s for s in SEEDS if s not in rows],
                     "truncated": sum(bool(r.get("truncated")) for r in rows.values()),
                     "jam_gone_none": sum(r.get("jam_gone_at") is None for r in rows.values()),
                     "no_pair_summary": sum(psum(r) is None for r in rows.values()),
                     "pair_files_checked": sum(c is not None for c in chk),
                     "pair_file_mismatch": sum(bool(c) for c in chk if c is not None),
                     "mismatch_detail": sorted({x for c in chk if c for x in c})}
        status[fname] = st
    out["status"] = status
    miss_m = sum(len(v["missing"]) for v in status["main"].values())
    miss_d = sum(len(v["missing"]) for v in status["delay"].values())
    partial = miss_m + miss_d > 0
    out["partial"] = partial

    # ---- E0: 여섯 방식의 지표 평균과 기준선 대비 건수 변화율(표 G1 용; E1 의 'm' 열과 같은 통계량을 여섯 방식 모두에)
    for met in METRICS:
        for k in KEYS:
            bt.add(("e0raw", k, met), vec(tm, k, lambda r, met=met: r[met]))
        for k in KEYS[1:]:
            bt.add(("e0chg", k, met), chg_vec(tm, k, tm, "base", lambda r, met=met: r[met]))

    # ---- E1: 경험 지연
    e1 = {}
    for met in METRICS:
        for k in DELAY_KEYS:
            bt.add(("e1raw", "d", k, met), vec(td, k, lambda r: r[met]))
            bt.add(("e1raw", "m", k, met), vec(tm, k, lambda r: r[met]))
        for k in ("graded", "u80"):
            bt.add(("e1chg", "d", k, met), chg_vec(td, k, td, "base", lambda r: r[met]))
            bt.add(("e1chg", "m", k, met), chg_vec(tm, k, tm, "base", lambda r: r[met]))
        for k in DELAY_KEYS:   # 같은 방식, 경험 지연 대 779 s
            bt.add(("e1same", k, met), chg_vec(td, k, tm, k, lambda r: r[met]))
    dl = [r.get("official_delay") for r in td.get("base", {}).values()]
    dl = [x for x in dl if x is not None]
    incons = 0
    for s in SEEDS:
        vs = {td.get(k, {}).get(s, {}).get("official_delay") for k in DELAY_KEYS if s in td.get(k, {})}
        incons += len(vs) > 1
    e1["official_delay"] = None if not dl else {
        "n": len(dl), "median": statistics.median(dl), "q1": quant(dl, 0.25), "q3": quant(dl, 0.75),
        "min": min(dl), "max": max(dl), "n_zero": sum(x == 0 for x in dl), "n_over_779": sum(x > 779 for x in dl),
        "seeds_inconsistent_across_schemes": incons,
        "by_seed": {s: td["base"][s].get("official_delay") for s in sorted(td.get("base", {}))}}

    # ---- E2: 위험의 분배
    for k in KEYS:
        for sk, _, pred in SHARES:
            def share(r, pred=pred):
                s = psum(r)
                if s is None:
                    return None
                tot = sum(v[MI["fast"]] for v in s["by_f"].values())
                return None if tot == 0 else 100.0 * sum(v[MI["fast"]] for g, v in s["by_f"].items() if pred(g)) / tot
            bt.add(("e2share", k, sk), vec(tm, k, share))
        for gk, _, gs in GROUPS:
            for met in METRICS:
                def rate(r, gs=gs, met=met):
                    n, e = by_f(r, gs, met), veh_exp(r, gs)
                    return None if (n is None or not e) else n / e * 1000
                bt.add(("e2rate", k, gk, met), vec(tm, k, rate))
    for k in KEYS[1:]:
        for gk, _, gs in GROUPS:
            for met in METRICS:
                def rate_t(r, gs=gs, met=met):
                    n, e = by_f(r, gs, met), veh_exp(r, gs)
                    return None if (n is None or not e) else n / e * 1000
                def rate_c(r, gs=GROUP_BASE[gk], met=met):
                    n, e = by_f(r, gs, met), veh_exp(r, gs)
                    return None if (n is None or not e) else n / e * 1000
                a_, c_ = vec(tm, k, rate_t), vec(tm, "base", rate_c)
                bt.add(("e2chg", k, gk, met),
                       [None if (x is None or y is None or y == 0) else (x - y) / y * 100 for x, y in zip(a_, c_)])
    for k1, k2 in combinations(KEYS, 2):
        for sk, _, _ in SHARES:
            v1, v2 = bt.vecs[("e2share", k1, sk)], bt.vecs[("e2share", k2, sk)]
            bt.add(("e2sdiff", k1, k2, sk), [None if (x is None or y is None) else x - y for x, y in zip(v1, v2)])

    # ---- E3: sham
    for met in METRICS:
        for k in ("sham", "u80"):
            bt.add(("chg", k, "base", met), chg_vec(tm, k, tm, "base", lambda r: r[met]))

    # ---- E4: 단계
    for k in KEYS:
        for ph in "abc":
            for met in METRICS:
                def phc(r, ph=ph, met=met):
                    s = psum(r)
                    return None if s is None else s["phase"][ph][MI[met]]
                def phs(r, ph=ph, met=met):
                    s = psum(r)
                    if s is None:
                        return None
                    tot = sum(s["phase"][p][MI[met]] for p in "abc")
                    return None if tot == 0 else 100.0 * s["phase"][ph][MI[met]] / tot
                bt.add(("e4n", k, ph, met), vec(tm, k, phc))
                bt.add(("e4s", k, ph, met), vec(tm, k, phs))
    for met in METRICS:
        bt.add(("chg", "u80tail", "u80", met), chg_vec(tm, "u80tail", tm, "u80", lambda r: r[met]))
        bt.add(("e4chg_b", met), chg_vec(tm, "u80tail", tm, "u80",
                                         lambda r, met=met: None if psum(r) is None else psum(r)["phase"]["b"][MI[met]]))

    # ---- E5: 오른쪽 차로
    for met in METRICS:
        for c in ("u80", "graded"):
            bt.add(("chg", "u80right", c, met), chg_vec(tm, "u80right", tm, c, lambda r: r[met]))

    # ---- E6: KE
    for k in KEYS:
        for kk in ("all", "fast", "severe"):
            f = lambda r, kk=kk: None if psum(r) is None else psum(r)["ke_MJ"][kk]
            bt.add(("e6raw", k, kk), vec(tm, k, f))
            if k != "base":
                bt.add(("e6chg", k, kk), chg_vec(tm, k, tm, "base", f))
    for k in KEYS[1:]:
        for met in METRICS:
            bt.add(("chg", k, "base", met), chg_vec(tm, k, tm, "base", lambda r: r[met]))

    bt.run()
    G = bt.get

    # ---------------------------------------------------------------- JSON
    e1["raw"] = {src: {k: {met: jsonable(G(("e1raw", src, k, met))) for met in METRICS} for k in DELAY_KEYS} for src in ("d", "m")}
    e1["chg_vs_base"] = {src: {k: {met: jsonable(G(("e1chg", src, k, met))) for met in METRICS} for k in ("graded", "u80")} for src in ("d", "m")}
    e1["effect_delay_minus_779"] = {k: {met: jsonable(bt.diff(("e1chg", "d", k, met), ("e1chg", "m", k, met))) for met in METRICS}
                                    for k in ("graded", "u80")}
    e1["same_scheme_delay_vs_779"] = {k: {met: jsonable(G(("e1same", k, met))) for met in METRICS} for k in DELAY_KEYS}
    out["E0"] = {"raw": {k: {met: jsonable(G(("e0raw", k, met))) for met in METRICS} for k in KEYS},
                 "chg_vs_base": {k: {met: jsonable(G(("e0chg", k, met))) for met in METRICS} for k in KEYS[1:]}}
    out["E1"] = e1
    out["E2"] = {"share_fast_follower": {k: {sk: jsonable(G(("e2share", k, sk))) for sk, _, _ in SHARES} for k in KEYS},
                 "share_diff": [{"a": k1, "b": k2, **{sk: jsonable(G(("e2sdiff", k1, k2, sk))) for sk, _, _ in SHARES}}
                                for k1, k2 in combinations(KEYS, 2)],
                 "rate_per_1000_exposed": {k: {gk: {met: jsonable(G(("e2rate", k, gk, met))) for met in METRICS} for gk, _, _ in GROUPS} for k in KEYS},
                 "rate_chg_vs_base": {k: {gk: {met: jsonable(G(("e2chg", k, gk, met))) for met in METRICS} for gk, _, _ in GROUPS} for k in KEYS[1:]},
                 "group_base_comparator": {gk: list(v) for gk, v in GROUP_BASE.items()}}
    e3 = {}
    for met in METRICS:
        s_, u_ = G(("chg", "sham", "base", met)), G(("chg", "u80", "base", met))
        rule = None if (s_ is None or u_ is None) else abs(s_["mean"]) >= 0.5 * abs(u_["mean"])
        bs, bu = bt.res[("chg", "sham", "base", met)]["boot"], bt.res[("chg", "u80", "base", met)]["boot"]
        ok = ~np.isnan(bs) & ~np.isnan(bu)
        frac = float(np.mean(np.abs(bs[ok]) >= 0.5 * np.abs(bu[ok]))) if ok.any() else None
        e3[met] = {"sham": jsonable(s_), "u80": jsonable(u_),
                   "ratio_abs": None if (rule is None or u_["mean"] == 0) else abs(s_["mean"]) / abs(u_["mean"]),
                   "rule_holds": rule, "boot_frac_rule_holds": frac,
                   "verdict": None if rule is None else ("효과의 상당 부분이 교란 자체에서 온다" if rule else "교란 효과로는 설명되지 않는다")}
    sh = list(tm.get("sham", {}).values())
    e3["sham_timing"] = None if not sh else {
        "sham_at": [min(r["sham_at"] for r in sh), statistics.median(r["sham_at"] for r in sh), max(r["sham_at"] for r in sh)],
        "dur": [min(r["sham_end"] - r["sham_at"] for r in sh), statistics.median(r["sham_end"] - r["sham_at"] for r in sh),
                max(r["sham_end"] - r["sham_at"] for r in sh)]}
    out["E3"] = e3
    out["E4"] = {"phase_n": {k: {ph: {met: jsonable(G(("e4n", k, ph, met))) for met in METRICS} for ph in "abc"} for k in KEYS},
                 "phase_share": {k: {ph: {met: jsonable(G(("e4s", k, ph, met))) for met in METRICS} for ph in "abc"} for k in KEYS},
                 "u80tail_vs_u80": {met: jsonable(G(("chg", "u80tail", "u80", met))) for met in METRICS},
                 "u80tail_vs_u80_phase_b": {met: jsonable(G(("e4chg_b", met))) for met in METRICS},
                 "jam_gone_none": {k: [status["main"][k]["jam_gone_none"], status["main"][k]["n_seeds"]] for k in KEYS}}
    lanes = {}
    for k in KEYS:
        rows = list(tm.get(k, {}).values())
        lk = {}
        for fld in ("lane_comply", "lane_all"):
            sh_ = [[x / sum(r[fld]) * 100 for x in r[fld]] for r in rows if r.get(fld) and sum(r[fld]) > 0]
            lk[fld] = None if not sh_ else {"mean_share_pct": [sum(c) / len(sh_) for c in zip(*sh_)], "n": len(sh_)}
        lanes[k] = lk
    out["E5"] = {"u80right_vs_u80": {met: jsonable(G(("chg", "u80right", "u80", met))) for met in METRICS},
                 "u80right_vs_graded": {met: jsonable(G(("chg", "u80right", "graded", met))) for met in METRICS},
                 "lane_share": lanes, "lane_note": "SUMO 차로 번호 0 = 가장 오른쪽. 앞 6 km 안 10 s 마다 표본(차·10 s)."}

    def order(vals):
        ks = [k for k in KEYS if vals.get(k) is not None]
        return sorted(ks, key=lambda k: vals[k])
    fast_v = {k: (0.0 if k == "base" else (G(("chg", k, "base", "fast")) or {}).get("mean")) for k in KEYS}
    if not tm.get("base"):
        fast_v = {k: None for k in KEYS}
    ke_ord = {}
    for kk in ("all", "fast", "severe"):
        v = {k: (0.0 if k == "base" else (G(("e6chg", k, kk)) or {}).get("mean")) for k in KEYS}
        if not tm.get("base"):
            v = {k: None for k in KEYS}
        ke_ord[kk] = order(v)
    out["E6"] = {"ke_mean_MJ": {k: {kk: jsonable(G(("e6raw", k, kk))) for kk in ("all", "fast", "severe")} for k in KEYS},
                 "ke_chg_vs_base": {k: {kk: jsonable(G(("e6chg", k, kk))) for kk in ("all", "fast", "severe")} for k in KEYS[1:]},
                 "order_by_fast_count_chg": order(fast_v), "order_by_ke_chg": ke_ord,
                 "same_order_fast_vs_ke_all": order(fast_v) == ke_ord["all"],
                 "same_order_fast_vs_ke_fast": order(fast_v) == ke_ord["fast"],
                 "mass_kg": {"car": 1500, "truck": 15000}}
    stem = Path(a.out)
    stem.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- MD
    L = ["# 관점 확장 E1(모형 연결)·E2~E6 분석 (탐색)", "",
         f"**자료 상태: 빠진 실행 {Path(a.main).name} {miss_m}개 / 144, {Path(a.delay).name} {miss_d}개 / 72"
         + ("" if has_d else "(파일 없음)") + "."
         + (" 부분 자료 — 확정 결과 아님.**" if partial else " 모두 갖춰짐.**"), "",
         "변화율 % = (처리−대조)/대조×100 의 씨앗별 평균(음수 = 상충 감소), 대조 0 인 씨앗은 제외. 비율·1,000대당 상충률도 씨앗별 값의 평균. "
         f"괄호는 부트스트랩 95 % CI(씨앗 1~24 복원 추출 {N_BOOT:,}회, random.Random(\"{RNG_KEY}\"), 모든 칸 같은 재표본, 백분위). "
         "부분 자료에서는 있는 씨앗만 쓴다(칸마다 n 이 다를 수 있음). 모두 PC·Krauss v2. 판정 규칙은 E3 하나, 나머지는 서술.", ""]

    # E0
    L += ["## E0 여섯 방식의 지표 평균과 기준선 대비 변화율(779 s, e_main)", "",
          "| 방식 | " + " | ".join(f"{MNAME[m]} 평균 | {MNAME[m]} 변화율" for m in METRICS) + " |", "|---|" + "---|---|" * len(METRICS)]
    for k in KEYS:
        L.append(f"| {NM[k]} | " + " | ".join(f"{fval(G(('e0raw', k, m)))} | " + ("—" if k == "base" else fpct(G(("e0chg", k, m)))) for m in METRICS) + " |")
    L.append("")

    # E1
    L += ["## E1 공식 안내 지연: 경험 분포 대 779 s", ""]
    od = e1["official_delay"]
    if od is None:
        L += ["e_delay 자료 없음 — 실행 뒤 다시 돌린다.", ""]
    else:
        L += [f"사용된 official_delay(기준선 레코드, 씨앗 {od['n']}개): 중앙값 {od['median']:.1f} s, Q1~Q3 {od['q1']:.1f}~{od['q3']:.1f} s, "
              f"범위 {od['min']:.1f}~{od['max']:.1f} s, 0 s(음수→0) {od['n_zero']}개, 779 s 초과 {od['n_over_779']}개"
              + (f"; 씨앗 안에서 방식마다 지연이 다른 씨앗 {od['seeds_inconsistent_across_schemes']}개(0 이어야 함)." if True else ""), ""]
    L += ["### 표 E1-1. 지표 평균(씨앗 평균 수)", "", "| 방식 | " + " | ".join(f"{MNAME[m]} 경험 지연 | {MNAME[m]} 779 s" for m in METRICS) + " |",
          "|---|" + "---|---|" * len(METRICS)]
    for k in DELAY_KEYS:
        L.append(f"| {NM[k]} | " + " | ".join(f"{fval(G(('e1raw', 'd', k, m)))} | {fval(G(('e1raw', 'm', k, m)))}" for m in METRICS) + " |")
    L += ["", "### 표 E1-2. 기준선 대비 변화율(같은 지연 조건 안)과 차이", "",
          "차이 = (경험 지연에서의 변화율) − (779 s 에서의 변화율), %p; 재표본마다 두 평균을 다시 계산해 뺀 분포의 CI. 양수 = 경험 지연에서 효과가 작아짐(덜 음수).", "",
          "| 방식 | 지표 | 경험 지연 | 779 s | 차이(%p) | 0 |", "|---|---|---|---|---|---|"]
    for k in ("graded", "u80"):
        for m in METRICS:
            d = bt.diff(("e1chg", "d", k, m), ("e1chg", "m", k, m))
            L.append(f"| {NM[k]} | {MNAME[m]} | {fpct(G(('e1chg', 'd', k, m)))} | {fpct(G(('e1chg', 'm', k, m)))} | {fpct(d)} | {has0(d)} |")
    L += ["", "### 표 E1-3. 같은 방식, 경험 지연 대 779 s (씨앗 짝 변화율)", "", "| 방식 | " + " | ".join(MNAME[m] for m in METRICS) + " |",
          "|---|" + "---|" * len(METRICS)]
    for k in DELAY_KEYS:
        L.append(f"| {NM[k]} | " + " | ".join(fpct(G(("e1same", k, m))) for m in METRICS) + " |")
    L.append("")

    # E2
    L += ["## E2 위험의 분배", "", "### 표 E2-1. 고속 접근 상충 중 뒤차 종류 비율(%, 씨앗 평균)", "",
          "| 방식 | " + " | ".join(n for _, n, _ in SHARES) + " |", "|---|" + "---|" * len(SHARES)]
    for k in KEYS:
        L.append(f"| {NM[k]} | " + " | ".join(fval(G(("e2share", k, sk))) for sk, _, _ in SHARES) + " |")
    L += ["", "기준선·sham 은 보급 0 이라 비앱 비율이 정의상 100 %.", "",
          "### 표 E2-2. 방식 간 비율 차이(A − B, %p, 씨앗 짝)", "",
          "| A | B | 비앱 차이 | 0 | 비준수 차이 | 0 |", "|---|---|---|---|---|---|"]
    for k1, k2 in combinations(KEYS, 2):
        a_, b_ = G(("e2sdiff", k1, k2, "nonapp")), G(("e2sdiff", k1, k2, "noncomply"))
        L.append(f"| {NM[k1]} | {NM[k2]} | {fpct(a_)} | {has0(a_)} | {fpct(b_)} | {has0(b_)} |")
    L += ["", "### 표 E2-3. 집단별 뒤차 상충률(노출 차량 1,000대당, 씨앗 평균)", "",
          "분모 = 처리 중 앞 6 km 에 있던 그 집단 차 수(veh_exp). 집단은 출발 때 뽑은 성향(준수 = 경고를 받으면 따를 차).", ""]
    for m in METRICS:
        L += [f"**{MNAME[m]}**", "", "| 방식 | " + " | ".join(n for _, n, _ in GROUPS) + " |", "|---|" + "---|" * len(GROUPS)]
        for k in KEYS:
            L.append(f"| {NM[k]} | " + " | ".join(fval(G(("e2rate", k, gk, m)), 0) for gk, _, _ in GROUPS) + " |")
        L.append("")
    L += ["### 표 E2-4. 집단별 상충률의 기준선 대비 변화율(%)", "",
          "대조 = 기준선에서 같은 준수 성향의 차 전체(앱 준수 ↔ 기준선 a0c1, 앱 비준수 ↔ 기준선 a0c0, 비앱·전체 ↔ 기준선 전체). "
          "기준선에는 앱 차가 없고 앱 여부는 준수 성향과 독립으로 뽑히므로 이것이 각 집단의 반사실 대조다.", ""]
    for m in METRICS:
        L += [f"**{MNAME[m]}**", "", "| 방식 | " + " | ".join(n for _, n, _ in GROUPS) + " |", "|---|" + "---|" * len(GROUPS)]
        for k in KEYS[1:]:
            L.append(f"| {NM[k]} | " + " | ".join(fpct(G(("e2chg", k, gk, m)))
                                                    if not (k == "sham" and gk in ("app_c", "app_nc")) else "—" for gk, _, _ in GROUPS) + " |")
        L.append("")

    # E3
    L += ["## E3 가짜 경고 대조", "", "| 지표 | sham 대 기준선 | 일률 80 대 기준선 | \\|sham\\|/\\|u80\\| | 규칙 성립 재표본 비율 | 판정 |", "|---|---|---|---|---|---|"]
    for m in METRICS:
        x = e3[m]
        L.append(f"| {MNAME[m]} | {fpct(G(('chg', 'sham', 'base', m)))} | {fpct(G(('chg', 'u80', 'base', m)))} | "
                 f"{fnum(x['ratio_abs'], 2)} | {fnum(None if x['boot_frac_rule_holds'] is None else x['boot_frac_rule_holds'] * 100, 1)}"
                 f"{'' if x['boot_frac_rule_holds'] is None else ' %'} | {x['verdict'] or '자료 없음'} |")
    L += ["", "규칙(등록): |sham 효과| ≥ 0.5·|일률 80 효과| (점 추정)이면 \"효과의 상당 부분이 교란 자체에서 온다\", 아니면 \"교란 효과로는 설명되지 않는다\". "
          "'규칙 성립 재표본 비율'은 같은 재표본에서 규칙이 성립한 비율(참고, 등록 밖)."]
    if e3["sham_timing"]:
        st_ = e3["sham_timing"]
        L.append(f"sham 시작(사고 기준 s) 최소·중앙·최대 {st_['sham_at'][0]:.0f} / {st_['sham_at'][1]:.0f} / {st_['sham_at'][2]:.0f}, "
                 f"유지 {st_['dur'][0]:.0f} / {st_['dur'][1]:.0f} / {st_['dur'][2]:.0f} s. sham 은 예열 차량 때문에 기준선과 궤적이 같은 짝이 아니다(구현 기록 (1)).")
    L.append("")

    # E4
    L += ["## E4 처리 뒤의 꼬리", "", "단계 a = 처리 중, b = 처리 뒤 정체 소멸(가장 긴 느린 차 줄 < 300 m) 전, c = 소멸 뒤. 쌍의 단계는 첫 기록 시각 기준.", ""]
    for m in METRICS:
        L += [f"### 표 E4-{METRICS.index(m) + 1}. {MNAME[m]} — 단계별 수(씨앗 평균)와 비율(%)", "",
              "| 방식 | a 수 | b 수 | c 수 | a % | b % | c % |", "|---|---|---|---|---|---|---|"]
        for k in KEYS:
            L.append(f"| {NM[k]} | " + " | ".join(fval(G(("e4n", k, ph, m))) for ph in "abc") + " | "
                     + " | ".join(fval(G(("e4s", k, ph, m))) for ph in "abc") + " |")
        L.append("")
    L += ["### 표 E4-4. u80tail 대 일률 80(씨앗 짝 변화율)", "", "| 지표 | 전체 기간 | 단계 b 만 |", "|---|---|---|"]
    for m in METRICS:
        L.append(f"| {MNAME[m]} | {fpct(G(('chg', 'u80tail', 'u80', m)))} | {fpct(G(('e4chg_b', m)))} |")
    L += ["", "jam_gone_at 이 None(실행 끝까지 정체 소멸 못 봄 → 단계 c 없음)인 실행: "
          + ", ".join(f"{NM[k]} {status['main'][k]['jam_gone_none']}/{status['main'][k]['n_seeds']}" for k in KEYS) + ".", ""]

    # E5
    L += ["## E5 차로 분리", "", "| 지표 | u80right 대 일률 80 | 0 | u80right 대 단계 | 0 |", "|---|---|---|---|---|"]
    for m in METRICS:
        a_, b_ = G(("chg", "u80right", "u80", m)), G(("chg", "u80right", "graded", m))
        L.append(f"| {MNAME[m]} | {fpct(a_)} | {has0(a_)} | {fpct(b_)} | {has0(b_)} |")
    L += ["", "### 표 E5-2. 차로 분포(%, 씨앗 평균; 0 = 가장 오른쪽). 앞 6 km 안 10 s 표본, 처리 중", "",
          "| 방식 | 경고받은 따르는 차 0 / 1 / 2 / 3 | 모든 차 0 / 1 / 2 / 3 |", "|---|---|---|"]
    for k in KEYS:
        lc, la = lanes[k]["lane_comply"], lanes[k]["lane_all"]
        f_ = lambda x: "—" if x is None else " / ".join(f"{v:.1f}" for v in x["mean_share_pct"])
        L.append(f"| {NM[k]} | {f_(lc)} | {f_(la)} |")
    L += ["", "u80right 는 기존 차로 권고 장치(60 s 유지)를 재사용해 효과가 작을 수 있다(구현 기록 (3)).", ""]

    # E6
    L += ["## E6 에너지 가중 지표", "", "KE = ½·m_f·Δv_max², 승용 1,500 kg·화물 15,000 kg(가정값, SUMO 기본값 아님), 등록 쌍(TTC < 1.5 s) 합계, MJ.", "",
          "| 방식 | KE 전체 | KE 고속 | KE 심각 | 변화율 전체 | 변화율 고속 | 변화율 심각 |", "|---|---|---|---|---|---|---|"]
    for k in KEYS:
        raws = " | ".join(fval(G(("e6raw", k, kk)), 1) for kk in ("all", "fast", "severe"))
        chs = " | ".join("—" if k == "base" else fpct(G(("e6chg", k, kk))) for kk in ("all", "fast", "severe"))
        L.append(f"| {NM[k]} | {raws} | {chs} |")
    of = out["E6"]["order_by_fast_count_chg"]
    L += ["", "방식 순서(기준선 대비 변화율 평균이 작은 = 좋은 쪽부터, 기준선 = 0):", "",
          f"- 고속 접근 건수: {' < '.join(NM[k] for k in of) or '자료 없음'}",
          f"- KE 전체: {' < '.join(NM[k] for k in ke_ord['all']) or '자료 없음'}",
          f"- KE 고속: {' < '.join(NM[k] for k in ke_ord['fast']) or '자료 없음'}",
          f"- KE 심각: {' < '.join(NM[k] for k in ke_ord['severe']) or '자료 없음'}", "",
          f"고속 접근 건수 순서와 KE 전체 순서가 {'같다' if out['E6']['same_order_fast_vs_ke_all'] else '다르다'}"
          f"(KE 고속 순서와는 {'같다' if out['E6']['same_order_fast_vs_ke_fast'] else '다르다'}). 점 추정 순서이며 CI 겹침은 위 표로 본다.", ""]

    # 상태
    L += ["## 자료 상태", "", "| 파일 | 방식 | 씨앗 수 | 빠진 씨앗 | 잘린 실행 | 정체 소멸 못 봄 | 쌍 요약 없음 | 쌍 파일 검산(불일치/확인) |",
          "|---|---|---|---|---|---|---|---|"]
    for fname, sk, keys in ((Path(a.main).name, "main", KEYS), (Path(a.delay).name, "delay", DELAY_KEYS)):
        st = status[sk]
        for k in keys:
            s = st[k]
            miss = "—" if not s["missing"] else (f"{len(s['missing'])}개" if len(s["missing"]) > 6 else ", ".join(map(str, s["missing"])))
            det = f" ({', '.join(s['mismatch_detail'])})" if s["mismatch_detail"] else ""
            L.append(f"| {fname} | {NM[k]} | {s['n_seeds']} | {miss} | {s['truncated']} | {s['jam_gone_none']} | {s['no_pair_summary']} | "
                     f"{s['pair_file_mismatch']}/{s['pair_files_checked']}{det} |")
    L += ["", "잘린 실행(정체가 도로 끝까지 참)은 분석에 포함했다."]
    stem.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
