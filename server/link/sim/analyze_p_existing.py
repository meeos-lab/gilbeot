"""검토 보강 중 '기존 결과만으로' 되는 다섯 분석(새 시뮬레이션 없음, 탐색·서술).
  python -X utf8 analyze_p_existing.py
  → results/report_p_existing.json, results/report_p_existing.md

1. P2(검토 D-2) 통행 시간: v2_main·fu_pc·e_main·rb_comply·m1_idm_b2·e_delay 의 travel(실행당 평균 통행 시간, s).
   대조 = 같은 씨앗의 기준선 official. 같은 파일의 official 을 쓰되 fu_pc 에는 official 이 없어 v2_main 의
   official 을 쓴다(analyze_fu.py 와 같은 짝, 같은 PC·같은 씨앗). 변화율 % 와 절대 차이(s) 의 씨앗 평균·CI.
2. P6(d)(검토 D-6) 측정 창: results/pairs/e_main_{seed}_{scheme}.json.gz 의 phase 로 (i) a, (ii) a+b, (iii) a+b+c.
3. C-5 선행 × 후행 집단: 같은 쌍 파일의 fast=1 쌍을 (뒤차 집단 × 앞차 집단) 으로 24씨앗 합산, 뒤차 노출 차 1,000대당.
4. D-7 E5 차로 분포: e_main 의 lane_comply·lane_all 을 방식 × 차단 차로 수로 합산한 비율.
5. C-4 문턱 격자(그림 12 용 값): report_r6.json 의 surface 를 그대로 옮겨 적는다(재계산 없음).
관례(analyze_e.py 와 같음): 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균, 대조 0 씨앗 제외. 부트스트랩 = 씨앗 1~24
복원 추출 10,000회, random.Random("p"), 모든 칸 같은 재표본 행렬, 백분위 95 % CI(선형 보간).
"""
import gzip
import json
import random
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
RES = HERE / "results"
SEEDS = list(range(1, 25))
N_BOOT = 10000
RNG_KEY = "p"
O = "official"
P = "official+tago12+relay"
FREE_FLOW_S = 22000 / (110 / 3.6)   # 22 km / 110 km/h = 720 s

NAME = {
    "none": "경고 없음", O: "기준선(공식 안내)", "official_ai": "공식 안내 80초(가상)", "tago12": "길벗 12 % 단독",
    "official+tago12": "기준선 + 12 %", "official+tago1.5+relay": "기준선 + 1.5 % + 연계", P: "단계 90·70·50",
    "tago100": "길벗 100 % 단독", P + "-u80": "일률 80", P + "-near": "꼬리 근처만 70", P + "-none": "권고 없음(주의만)",
    P + "-sham": "가짜 경고(sham)", P + "-u80tail": "일률 80, 정체 소멸까지(u80tail)", P + "-u80right": "일률 80 + 오른쪽 차로(u80right)",
}
E6 = [O, P, P + "-u80", P + "-sham", P + "-u80tail", P + "-u80right"]
TRAVEL_FILES = [  # (파일, 방식들, 대조 파일)
    ("v2_main.jsonl", [O, "none", "official_ai", "tago12", "official+tago12", "official+tago1.5+relay", P, "tago100"], "v2_main.jsonl"),
    ("fu_pc.jsonl", [P + "-near", P + "-none", P + "-u80"], "v2_main.jsonl"),
    ("e_main.jsonl", E6, "e_main.jsonl"),
    ("rb_comply.jsonl", [O, P, P + "-u80"], "rb_comply.jsonl"),
    ("m1_idm_b2.jsonl", [O, P, P + "-u80"], "m1_idm_b2.jsonl"),
    ("e_delay.jsonl", [O, P, P + "-u80"], "e_delay.jsonl"),
]
TRAVEL_NOTE = {"v2_main.jsonl": "v2 본 실험(Krauss, 779 s)", "fu_pc.jsonl": "후속(대조 = v2_main 의 official)",
               "e_main.jsonl": "관점 확장 E(779 s)", "rb_comply.jsonl": "R1 현장 준수율",
               "m1_idm_b2.jsonl": "M1 IDM(b = 2.0)", "e_delay.jsonl": "E1 경험 지연"}
MI = {"all": 0, "fast": 1, "severe": 2}
MNAME = {"all": "전체 쌍", "fast": "고속 접근(fast=1)", "severe": "심각(severe=1)"}
WIN = [("a", "(i) a: 처리 중", "a"), ("ab", "(ii) a+b: 정체 소멸까지", "ab"), ("abc", "(iii) a+b+c: 전부", "abc")]
GRP = [("app_c", "앱 준수(a1c1)"), ("app_nc", "앱 비준수(a1c0)"), ("nonapp", "비앱(a0*)"), ("crash", "사고 차")]


def load(name):
    t = {}
    p = RES / name
    for x in p.read_text(encoding="utf-8").splitlines():
        x = x.strip()
        if not x:
            continue
        try:
            r = json.loads(x)
        except json.JSONDecodeError:
            continue
        if r.get("false") or r.get("ov") or r.get("seed") not in SEEDS:
            continue
        t.setdefault(r["scheme"], {})[r["seed"]] = r
    return t


# ---------------------------------------------------------------- 부트스트랩(analyze_e.Boot 와 같은 방식)
class Boot:
    def __init__(self):
        self.vecs, self.res = {}, {}

    def add(self, key, vec):
        self.vecs[key] = vec

    def run(self):
        rng = random.Random(RNG_KEY)
        C = np.zeros((N_BOOT, len(SEEDS)))
        for b in range(N_BOOT):
            for _ in SEEDS:
                C[b, rng.randrange(len(SEEDS))] += 1
        keys = list(self.vecs)
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


def chg(x, y):
    return None if (x is None or y is None or y == 0) else (x - y) / y * 100


def f(c, nd=1, sign=True):
    if c is None:
        return "—"
    sp = "+" if sign else ""
    m = f"{c['mean']:{sp}.{nd}f}"
    return m if c["ci"] is None else m + f" ({c['ci'][0]:{sp}.{nd}f} ~ {c['ci'][1]:{sp}.{nd}f})"


def has0(c):
    if c is None or c["ci"] is None:
        return "—"
    return "포함" if c["ci"][0] <= 0 <= c["ci"][1] else "벗어남"


# ---------------------------------------------------------------- 쌍 파일
def fgrp(app, comply):
    if app is None:
        return "crash"
    return "nonapp" if app == 0 else ("app_c" if comply else "app_nc")


def read_pairs(seed, scheme):
    fn = RES / "pairs" / f"e_main_{seed}_{scheme}.json.gz"
    if not fn.exists():
        return None
    d = json.load(gzip.open(fn, "rt", encoding="utf-8"))
    ci_ = {c: i for i, c in enumerate(d["cols"])}
    ph = {p: [0, 0, 0] for p in "abc"}
    cross = {}                      # (뒤차 집단, 앞차 집단) -> fast 수
    neg_t0 = 0
    for w in d["rows"]:
        inc = [1, w[ci_["fast"]], w[ci_["severe"]]]
        ph[w[ci_["phase"]]] = [a + b for a, b in zip(ph[w[ci_["phase"]]], inc)]
        if w[ci_["fast"]]:
            k = (fgrp(w[ci_["f_app"]], w[ci_["f_comply"]]), fgrp(w[ci_["l_app"]], w[ci_["l_comply"]]))
            cross[k] = cross.get(k, 0) + 1
        neg_t0 += w[ci_["t0_rel"]] < 0
    return {"phase": ph, "cross": cross, "n": len(d["rows"]), "neg_t0": neg_t0}


# ---------------------------------------------------------------- 본문
def main():
    bt = Boot()
    out = {"note": "탐색. 변화율 % = (처리−대조)/대조×100 의 씨앗별 평균(음수 = 감소), 대조 0 씨앗 제외. 95 % CI = 씨앗 1~24 "
                   '복원 추출 부트스트랩 10,000회 백분위, random.Random("p"), 모든 칸 같은 재표본. 새 시뮬레이션 없음.',
           "rng": f'random.Random("{RNG_KEY}")', "n_boot": N_BOOT}
    tabs = {fn: load(fn) for fn in {x[0] for x in TRAVEL_FILES} | {x[2] for x in TRAVEL_FILES}}

    # ---- 1. 통행 시간
    for fn, schemes, bf in TRAVEL_FILES:
        t, tb = tabs[fn], tabs[bf]
        for sc in schemes:
            tv = [t.get(sc, {}).get(s, {}).get("travel") for s in SEEDS]
            bv = [tb.get(O, {}).get(s, {}).get("travel") for s in SEEDS]
            bt.add(("tr", fn, sc, "raw"), tv)
            if not (fn == bf and sc == O):
                bt.add(("tr", fn, sc, "pct"), [chg(x, y) for x, y in zip(tv, bv)])
                bt.add(("tr", fn, sc, "ds"), [None if (x is None or y is None) else x - y for x, y in zip(tv, bv)])

    # ---- 2·3. 쌍 파일
    em = tabs["e_main.jsonl"]
    pr, chk = {}, {"pair_files": 0, "missing": [], "phase_vs_record_summary": 0, "abc_vs_record_metric": 0,
                   "mismatch_detail": [], "neg_t0_pairs": 0, "jam_gone_none": {}}
    for sc in E6:
        for s in SEEDS:
            r = em.get(sc, {}).get(s)
            d = read_pairs(s, sc)
            if d is None or r is None:
                chk["missing"].append([sc, s])
                continue
            chk["pair_files"] += 1
            chk["neg_t0_pairs"] += d["neg_t0"]
            pr[(sc, s)] = d
            if r.get("pairs") and d["phase"] != r["pairs"]["phase"]:
                chk["phase_vs_record_summary"] += 1
                chk["mismatch_detail"].append([sc, s, "phase"])
            tot = [sum(d["phase"][p][i] for p in "abc") for i in range(3)]
            if tot != [r["conflicts"], r["fast"], r["severe"]]:
                chk["abc_vs_record_metric"] += 1
                chk["mismatch_detail"].append([sc, s, f"abc {tot} ≠ 레코드 {[r['conflicts'], r['fast'], r['severe']]}"])
        chk["jam_gone_none"][sc] = sum(em.get(sc, {}).get(s, {}).get("jam_gone_at", 0) is None for s in SEEDS)

    def wcount(sc, s, win, met):
        d = pr.get((sc, s))
        return None if d is None else sum(d["phase"][p][MI[met]] for p in win)

    for _, _, win in WIN:
        for met in MI:
            for sc in E6:
                bt.add(("ph", win, sc, met, "raw"), [wcount(sc, s, win, met) for s in SEEDS])
            for sc in E6[1:]:
                bt.add(("ph", win, sc, met, "pct"), [chg(wcount(sc, s, win, met), wcount(O, s, win, met)) for s in SEEDS])
    # 일률 80 대 단계도(본문의 주 대비)
    for _, _, win in WIN:
        for met in MI:
            for sc in (P + "-u80", P + "-u80tail"):
                bt.add(("phg", win, sc, met), [chg(wcount(sc, s, win, met), wcount(P, s, win, met)) for s in SEEDS])

    bt.run()
    G = bt.get

    # ---------------------------------------------------------------- JSON
    J1 = []
    for fn, schemes, bf in TRAVEL_FILES:
        for sc in schemes:
            J1.append({"file": fn, "baseline_file": bf, "scheme": sc, "name": NAME.get(sc, sc),
                       "n": G(("tr", fn, sc, "raw"))["n_used"], "travel_s": G(("tr", fn, sc, "raw")),
                       "pct_vs_official": G(("tr", fn, sc, "pct")), "diff_s_vs_official": G(("tr", fn, sc, "ds"))})
    out["P2_travel"] = {"rows": J1, "free_flow_s": FREE_FLOW_S,
                        "def": "travel = 사고 300 s 전 ~ 처리 끝 사이에 출발해 도착한 차의 평균 통행 시간(tago_sim.py 581행)"}
    out["P6d_window"] = {"check": chk,
                         "raw": {w: {sc: {m: G(("ph", w, sc, m, "raw")) for m in MI} for sc in E6} for _, _, w in WIN},
                         "pct_vs_official": {w: {sc: {m: G(("ph", w, sc, m, "pct")) for m in MI} for sc in E6[1:]} for _, _, w in WIN},
                         "pct_vs_graded": {w: {sc: {m: G(("phg", w, sc, m)) for m in MI} for sc in (P + "-u80", P + "-u80tail")} for _, _, w in WIN}}

    # ---- 3. 선행 × 후행
    C5 = {}
    for sc in (O, P, P + "-u80"):
        cr, ve = {}, {}
        for s in SEEDS:
            d = pr.get((sc, s))
            if d is None:
                continue
            for k, v in d["cross"].items():
                cr["|".join(k)] = cr.get("|".join(k), 0) + v
            vx = em[sc][s]["pairs"]["veh_exp"]
            for g, n in vx.items():
                gg = fgrp(int(g[1]), int(g[3]))
                ve[gg] = ve.get(gg, 0) + n
        C5[sc] = {"fast_counts": cr, "veh_exp": ve,
                  "rate_per_1000_exposed": {fg: {lg: (cr.get(f"{fg}|{lg}", 0) / ve[fg] * 1000 if ve.get(fg) else None)
                                                 for lg, _ in GRP} for fg, _ in GRP[:3]}}
    out["C5_cross"] = {"schemes": C5, "note": "뒤차(후행) 집단 × 앞차(선행) 집단, fast=1 쌍의 24씨앗 합. 비율 분모 = 뒤차 집단의 노출 차 수 합"
                                               "(pairs.veh_exp: 처리 중 사고 앞 6 km 안에 있던 차). 기준선에는 앱 차가 없다(보급 0). "
                                               "차로 변경 횟수는 레코드·쌍 파일에 기록이 없어 계산 불가."}

    # ---- 4. 차로 분포
    L4 = {}
    for sc in E6:
        L4[sc] = {}
        for b in (1, 2):
            rows = [r for r in em.get(sc, {}).values() if r["cond"]["blocked"] == b]
            e = {"n_seeds": len(rows)}
            for fld in ("lane_comply", "lane_all"):
                tot = [sum(r[fld][i] for r in rows) for i in range(4)]
                s_ = sum(tot)
                e[fld] = {"count": tot, "share_pct": [x / s_ * 100 for x in tot] if s_ else None}
            L4[sc][b] = e
    out["D7_lanes"] = {"by_scheme_blocked": L4,
                       "note": "SUMO 차로 0 = 가장 오른쪽. 차단 차로 = 0..blocked−1. u80right 목표 차로 = blocked(가장 오른쪽 개방 차로). "
                               "처리 중(active) 10 s 마다 사고 앞 6 km 안 차를 센 차·10 s 표본(tago_sim.py 540~547행)."}

    # ---- 5. 문턱 격자
    r6 = json.loads((RES / "report_r6.json").read_text(encoding="utf-8"))
    out["C4_grid"] = {"source": "results/report_r6.json surface (R6, 씨앗 101~200, n = 100)", "surface": r6["surface"],
                      "main_cell": "1.5|30"}

    (RES / "report_p_existing.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- MD
    L = ["# 기존 결과만으로 하는 보강 분석 P2·P6(d)·C-5·D-7·C-4 (탐색, 새 시뮬레이션 없음)", "",
         "변화율 % = (처리−대조)/대조×100 의 씨앗별 평균(음수 = 감소), 대조 0 인 씨앗 제외. 괄호는 부트스트랩 95 % CI"
         '(씨앗 1~24 복원 추출 10,000회, random.Random("p"), 모든 칸 같은 재표본, 백분위). 모두 PC 결과 파일.', "",
         "## 1. P2 통행 시간(검토 D-2)", "",
         f"travel = 사고 300 s 전부터 처리 끝까지 출발해 도착한 차의 실행당 평균 통행 시간(s). 대조 = 같은 씨앗의 official "
         f"(fu_pc 는 official 이 없어 v2_main 의 official). 자유류 참고값 22 km / 110 km/h = {FREE_FLOW_S:.0f} s.", "",
         "| 파일 | 방식 | n | travel 평균(초) | 기준선 대비 %(CI) | 차이 초(CI) |", "|---|---|---|---|---|---|"]
    for e in J1:
        base = e["file"] == e["baseline_file"] and e["scheme"] == O
        L.append(f"| {e['file']} | {e['name']} | {e['n']} | {f(e['travel_s'], 1, False)} | "
                 f"{'기준선' if base else f(e['pct_vs_official'], 2)} | {'—' if base else f(e['diff_s_vs_official'], 1)} |")
    L += ["", "## 2. P6(d) 측정 창(검토 D-6): 기준선 대비 변화율", "",
          "단계 a = 처리 중, b = 처리 뒤 정체 소멸(가장 긴 느린 차 줄 < 300 m) 전, c = 소멸 뒤(쌍의 첫 TTC<1.5 s 시각 t0 기준). "
          f"쌍 파일 {chk['pair_files']}개 / 144. 정체 소멸이 없었던 실행(b 가 실행 끝까지): "
          + ", ".join(f"{NAME[k]} {v}" for k, v in chk["jam_gone_none"].items()) + ".", ""]
    L += ["### 표 2-1. 씨앗 평균 쌍 수", "", "| 방식 | " + " | ".join(f"{MNAME[m]} {lab.split(':')[0]}" for m in MI for _, lab, _ in WIN) + " |",
          "|---|" + "---|" * 9]
    for sc in E6:
        L.append(f"| {NAME[sc]} | " + " | ".join(f"{G(('ph', w, sc, m, 'raw'))['mean']:.1f}" for m in MI for _, _, w in WIN) + " |")
    L += ["", "### 표 2-2. 기준선 대비 변화율 %", "", "| 방식 | 지표 | (i) a | (ii) a+b | (iii) a+b+c |", "|---|---|---|---|---|"]
    for sc in E6[1:]:
        for m in MI:
            L.append(f"| {NAME[sc]} | {MNAME[m]} | " + " | ".join(f(G(("ph", w, sc, m, "pct")), 1) for _, _, w in WIN) + " |")
    L += ["", "### 표 2-3. 참고: 단계 대비 변화율 %", "", "| 방식 | 지표 | (i) a | (ii) a+b | (iii) a+b+c |", "|---|---|---|---|---|"]
    for sc in (P + "-u80", P + "-u80tail"):
        for m in MI:
            L.append(f"| {NAME[sc]} | {MNAME[m]} | " + " | ".join(f(G(("phg", w, sc, m)), 1) for _, _, w in WIN) + " |")
    L += ["", f"검산: a+b+c 합 ≠ 레코드 지표(conflicts·fast·severe) {chk['abc_vs_record_metric']}건, 쌍 파일 단계 수 ≠ 레코드 pairs.phase "
              f"{chk['phase_vs_record_summary']}건, t0 가 사고 전(t0_rel < 0)인 쌍 {chk['neg_t0_pairs']}개(단계 a 에 들어감)."
              + (" 불일치: " + "; ".join(map(str, chk["mismatch_detail"][:10])) if chk["mismatch_detail"] else ""), ""]
    L += ["## 3. C-5 선행 × 후행 집단 고속 접근(fast=1) 상충(검토 C-5)", "",
          "행 = 뒤차(후행) 집단, 열 = 앞차(선행) 집단. 24씨앗 합(쌍 수) 과 뒤차 집단 노출 차 1,000대당(괄호). 노출 차 = 처리 중 "
          "사고 앞 6 km 안에 있던 차(레코드 pairs.veh_exp). **기준선에는 앱 차가 없어(보급 0) 비앱 행만 있다.** "
          "차로 변경 횟수는 레코드·쌍 파일 어디에도 기록되지 않아 계산 불가.", ""]
    for sc in (O, P, P + "-u80"):
        c = C5[sc]
        L += [f"### {NAME[sc]}", "", "| 뒤차 \\ 앞차 | " + " | ".join(n for _, n in GRP) + " | 합 | 노출 차 |", "|---|---|---|---|---|---|---|"]
        for fg, fn_ in GRP[:3]:
            if not c["veh_exp"].get(fg):
                continue
            cells = [f"{c['fast_counts'].get(f'{fg}|{lg}', 0)} ({c['rate_per_1000_exposed'][fg][lg]:.1f})" for lg, _ in GRP]
            tot = sum(c["fast_counts"].get(f"{fg}|{lg}", 0) for lg, _ in GRP)
            L.append(f"| {fn_} | " + " | ".join(cells) + f" | {tot} ({tot / c['veh_exp'][fg] * 1000:.1f}) | {c['veh_exp'][fg]} |")
        extra = {k: v for k, v in c["fast_counts"].items() if k.startswith("crash|")}
        if extra:
            L.append(f"| (뒤차 = 사고 차) | {extra} |  |  |  |  |  |")
        L.append("")
    L += ["## 4. D-7 E5 차로 분포(검토 D-7)", "",
          "SUMO 차로 0 = 가장 오른쪽, 차단 차로 = 0..(차단 수−1), u80right 목표 = 차로 번호 = 차단 수(가장 오른쪽 개방 차로). "
          "처리 중 10 s 마다 사고 앞 6 km 안의 차를 센 표본(차·10 s)을 씨앗 합산한 비율 %. lane_comply = 경고받은 준수 차, lane_all = 모든 차.", "",
          "| 방식 | 차단 | 씨앗 | 준수 차 0 | 1 | 2 | 3 | 표본 | 전체 차 0 | 1 | 2 | 3 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sc in E6:
        for b in (1, 2):
            e = L4[sc][b]
            lc, la = e["lane_comply"], e["lane_all"]
            sc_ = " | ".join(f"{x:.1f}" for x in lc["share_pct"]) if lc["share_pct"] else "— | — | — | —"
            sa_ = " | ".join(f"{x:.1f}" for x in la["share_pct"]) if la["share_pct"] else "— | — | — | —"
            L.append(f"| {NAME[sc]} | {b} | {e['n_seeds']} | {sc_} | {sum(lc['count'])} | {sa_} |")
    L += ["", "## 5. C-4 문턱 격자(그림 12 값, report_r6.json 그대로)", ""]
    for key in ("u80_vs_baseline", "u80_vs_graded"):
        L += [f"### {key} (R6 씨앗 101~200, 씨앗별 변화율 평균 %)", "", "| TTC \\ 속도 차 | ≥0 | ≥10 | ≥20 | ≥30 | ≥40 |", "|---|---|---|---|---|---|"]
        for tt in ("0.75", "1.0", "1.5", "2.0", "3.0"):
            L.append(f"| < {tt} s | " + " | ".join(f"{r6['surface'][key][f'{tt}|{d}']:+.1f}" for d in (0, 10, 20, 30, 40)) + " |")
        L.append("")
    (RES / "report_p_existing.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
