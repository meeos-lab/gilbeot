"""심사 요구: 같은 씨앗(23, 맥)의 꼬리 접근 장면에서 Krauss 와 IDM 이 무엇이 다른가.

  python -X utf8 analyze_scenes.py   # results/mac/p_spacetime_{krauss,idm}.jsonl 만 읽는다(새 시뮬레이션 없음)
  → results/report_scenes.md·json, docs/figures/fig14_cf_scenes.png
맥 안에서만 비교한다(PC 본 실험 값과 섞지 않는다).

기록 구조(tago_sim.run_one, TAGO_REC_ID=1): frames = [t, [[x, lane, v m/s, warned, equipped, truck, id, 권고, comply], …]]
(사고 뒤 2 s 마다, 사고 지점 −6000~+300 m), events = [t, x_f, lane, x_l, Δv km/h, v_f km/h](고속 접근 상충이 처음 성립),
tail = [t, 앱 꼬리 x 또는 None](앱이 꼬리를 모를 때·기준선은 None), pairs = 상충 쌍(TTC<1.5 s)별 [최소 TTC, 문턱별 최대 Δv km/h].
꼬리까지 거리 = 꼬리 x − 차 x (+ = 꼬리 상류), viz_p.py 와 같은 규약.

꼬리 두 가지:
  물리 꼬리(주): 프레임마다 tago_sim 의 max_back 규칙 그대로 — 30 km/h(8.3 m/s) 미만 차가 사고 지점 500 m 안에서 시작해
               300 m 미만 간격으로 이어진 줄의 가장 상류 차. 처리 전(900 ≤ t < t_clear)만. 세 방식에 같은 기준.
  앱 꼬리(민감도): rec["tail"](장착 차 기반 길벗 꼬리). 기준선에는 없다.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).parent
RES = HERE / "results"
OUT = HERE.parents[2] / "docs" / "figures" / "fig14_cf_scenes.png"
FONTS = sorted((RES / "_work" / "fonts").glob("NotoSansKR-*.ttf"))
for f in FONTS or [Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/malgunbd.ttf")]:
    if f.exists():
        font_manager.fontManager.addfont(str(f))
plt.rcParams["font.family"] = "Noto Sans KR" if FONTS else "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
INK, MUTED, SURF, CRASH, GREY, PURP = "#1f2430", "#3f4553", "#ffffff", "#e8607a", "#9aa0ab", "#4b3bc4"

INC_POS, T_INC = 20000.0, 900.0
SLOW_MS, CHAIN_GAP, HEAD = 8.3, 300.0, 500.0          # tago_sim max_back 규칙
V_APP_MIN = 60 / 3.6                                  # 접근 속도가 이 아래면 '자유 접근'이 아님 → 제외
ENTER_X = INC_POS - 5500                              # 창(−6000 m) 들머리 500 m 안에서 처음 보인 차만(이미 정체 안에 있던 차 제외)
DECEL_A = 0.5                                         # m/s², 2 s(프레임 한 칸) 평균
MODELS = [("krauss", "Krauss"), ("idm", "IDM")]
SCEN = [("official", "기준선", GREY), ("official+tago12+relay", "단계 90·70·50", CRASH),
        ("official+tago12+relay-u80", "일률 80", PURP)]
FS = 16


def phys_tail(vehs):
    slow = sorted((v[0] for v in vehs if v[2] < SLOW_MS and 0 < v[0] <= INC_POS), reverse=True)
    if not slow or INC_POS - slow[0] >= HEAD:
        return None
    back = slow[0]
    for x in slow[1:]:
        if back - x >= CHAIN_GAP:
            break
        back = x
    return back


def q(a, ps=(25, 50, 75)):
    a = np.asarray(a, float)
    return [None] * len(ps) if a.size == 0 else [round(float(np.percentile(a, p)), 1) for p in ps]


def analyse(r):
    rec = r["record"]
    t_clear = rec["t_clear"]
    app_tail = {t: x for t, x in rec["tail"]}
    traj, ptail, frames_t = {}, {}, []
    for t, vehs in rec["frames"]:
        frames_t.append(t)
        ptail[t] = phys_tail(vehs) if T_INC <= t < t_clear else None
        for v in vehs:
            traj.setdefault(v[6], []).append((t, v[0], v[1], v[2], v[3], v[8], v[4]))
    # 1. 감속 시작
    onset = {"phys": {"v90": {"c": [], "o": []}, "a05": {"c": [], "o": []}},
             "app": {"v90": {"c": [], "o": []}, "a05": {"c": [], "o": []}}}
    n_cand = {"c": 0, "o": 0}
    lead_v90 = []                                     # 두 정의가 다 잡힌 차: a05 시각 − v90 시각
    prof = {"c": {"v_app": [], "v500": [], "amax": []}, "o": {"v_app": [], "v500": [], "amax": []}}   # 접근 속도, 꼬리 500 m 앞 속도, 줄 합류 전 최대 2 s 감속도
    for vid, tr in traj.items():
        t0, x0, _, v0 = tr[0][:4]
        if not (T_INC < t0 < t_clear and x0 < ENTER_X) or len(tr) < 4:
            continue
        v_app = float(np.median([p[3] for p in tr[:3]]))
        if v_app < V_APP_MIN:
            continue
        k90 = next((k for k in range(3, len(tr)) if tr[k][3] < 0.9 * v_app), None)
        ka = next((k for k in range(3, len(tr)) if tr[k][0] - tr[k - 1][0] == 2.0 and (tr[k - 1][3] - tr[k][3]) / 2.0 >= DECEL_A), None)
        if k90 is not None and ka is not None:
            lead_v90.append(tr[ka][0] - tr[k90][0])
        grp_any = None
        for name, k in (("v90", k90), ("a05", ka)):
            if k is None:
                continue
            t, x, _, _, w, c, _ = tr[k]
            g = "c" if (w and c) else "o"
            if name == "v90":
                grp_any = g
            for tk, tl in (("phys", ptail.get(t)), ("app", app_tail.get(t))):
                if tl is not None:
                    onset[tk][name][g].append(tl - x)
        if grp_any:
            n_cand[grp_any] += 1
            pg = prof[grp_any]
            pg["v_app"].append(v_app * 3.6)
            kq = next((k for k in range(len(tr)) if tr[k][3] < SLOW_MS), len(tr))
            dec = [(tr[k - 1][3] - tr[k][3]) / 2.0 for k in range(1, kq + 1 if kq < len(tr) else kq) if tr[k][0] - tr[k - 1][0] == 2.0]
            if dec:
                pg["amax"].append(max(dec))
            v5 = next((p[3] for p in tr if ptail.get(p[0]) is not None and ptail[p[0]] - p[1] <= 500), None)
            if v5 is not None:
                pg["v500"].append(v5 * 3.6)
    # 2. 상충 사건 ↔ 프레임 연결(가장 가까운 프레임 시각, 같은 차로, 위치를 속도로 옮겨 15 m 안)
    by_t = {}
    for vid, tr in traj.items():
        for p in tr:
            by_t.setdefault(p[0], []).append((vid,) + p[1:])
    ft = np.array(frames_t)
    ev_out = []
    for e in rec["events"]:
        t, xf, lane, xl, dv, vf = e
        tf = float(ft[np.argmin(np.abs(ft - t))])
        best, bd = None, 15.0
        for vid, x, ln, v, w, c, eq in by_t.get(tf, []):
            d = abs(x - (xf + vf / 3.6 * (tf - t)))
            if ln == lane and d < bd:
                best, bd = (w, c, eq), d
        tl = ptail.get(tf)
        ev_out.append({"t": t, "dv": dv, "vf": vf, "d_tail": None if tl is None else round(tl - xf, 1),
                       "d_app": None if app_tail.get(tf) is None else round(app_tail[tf] - xf, 1),
                       "match": best is not None, "comply": bool(best and best[0] and best[1]), "warned": bool(best and best[0]),
                       "pre": t < T_INC, "post": t >= t_clear})
    # 3. 최소 TTC
    ttc_all = np.array([p[0] for p in r["pairs"]])
    ttc_fast = np.array([p[0] for p in r["pairs"] if p[3] >= 30])
    return {"onset": onset, "prof": prof, "n_cand": n_cand, "lead_a05_minus_v90": lead_v90, "events": ev_out,
            "ttc_all": ttc_all, "ttc_fast": ttc_fast, "fast": r["fast"], "severe": r["severe"], "conflicts": r["conflicts"]}


def summ(a):
    return {"n": len(a), "q25_med_q75": q(a)}


def main():
    res = {}
    for m, _ in MODELS:
        for line in (RES / "mac" / f"p_spacetime_{m}.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            if r["seed"] == 23:
                res[(m, r["scheme"])] = analyse(r)
                print("done", m, r["scheme"], flush=True)
            del r
    out = {}
    for (m, sc), a in res.items():
        ev = a["events"]
        evin = [e for e in ev if e["d_tail"] is not None]
        mt = [e for e in ev if e["match"]]
        o = {"fast": a["fast"], "severe": a["severe"], "conflicts": a["conflicts"], "n_approach": a["n_cand"],
             "onset": {tk: {d: {g: summ(v) for g, v in dd.items()} for d, dd in td.items()} for tk, td in a["onset"].items()},
             "a05_minus_v90_s": summ(a["lead_a05_minus_v90"]),
             "profile": {g: {k: summ(v) for k, v in d.items()} for g, d in a["prof"].items()},
             "events": {"n": len(ev), "n_pre": sum(e["pre"] for e in ev), "n_post": sum(e["post"] for e in ev),
                        "vf": summ([e["vf"] for e in ev]), "dv": summ([e["dv"] for e in ev]),
                        "d_tail": summ([e["d_tail"] for e in evin]), "d_tail_upstream_share": round(float(np.mean([e["d_tail"] > 0 for e in evin])), 3) if evin else None,
                        "matched": len(mt), "comply_share": round(sum(e["comply"] for e in mt) / len(mt), 3) if mt else None,
                        "warned_share": round(sum(e["warned"] for e in mt) / len(mt), 3) if mt else None,
                        "comply": {g: {"n": len(s), "vf": q([e["vf"] for e in s], (50,))[0], "dv": q([e["dv"] for e in s], (50,))[0],
                                       "d_tail": q([e["d_tail"] for e in s if e["d_tail"] is not None], (50,))[0]}
                                   for g, s in (("c", [e for e in mt if e["comply"]]), ("o", [e for e in mt if not e["comply"]]))}},
             "ttc": {"n": len(a["ttc_all"]), "med": round(float(np.median(a["ttc_all"])), 3), "p10": round(float(np.percentile(a["ttc_all"], 10)), 3),
                     "lt075": round(float(np.mean(a["ttc_all"] < 0.75)), 3),
                     "fast_n": len(a["ttc_fast"]), "fast_med": round(float(np.median(a["ttc_fast"])), 3) if len(a["ttc_fast"]) else None,
                     "fast_p10": round(float(np.percentile(a["ttc_fast"], 10)), 3) if len(a["ttc_fast"]) else None,
                     "fast_lt075": round(float(np.mean(a["ttc_fast"] < 0.75)), 3) if len(a["ttc_fast"]) else None}}
        out[f"{m}|{sc}"] = o
    (RES / "report_scenes.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    figure(res)
    report(out)


def figure(res):
    fig, axes = plt.subplots(2, 3, figsize=(11.7, 8.6), facecolor=SURF, gridspec_kw={"wspace": 0.42, "hspace": 0.62})
    for i, (m, mname) in enumerate(MODELS):
        ax = axes[i, 0]
        data = [np.asarray(res[(m, sc)]["onset"]["phys"]["v90"]["c"]) / 1000 for sc, _, _ in SCEN]
        bp = ax.boxplot(data, orientation="horizontal", widths=0.55, showfliers=False, patch_artist=True,
                        medianprops=dict(color=INK, lw=1.6), whiskerprops=dict(color=MUTED), capprops=dict(color=MUTED))
        for patch, (_, _, c) in zip(bp["boxes"], SCEN):
            patch.set_facecolor(c); patch.set_edgecolor(MUTED); patch.set_alpha(0.85)
        ax.set_yticks(range(1, 4)); ax.set_yticklabels([f"{t}\n(n={len(d)})" for (_, t, _), d in zip(SCEN, data)])
        ax.axvline(0, color=INK, lw=0.8, ls=(0, (3, 3)))
        ax.set_xlabel("감속 시작 때 꼬리까지 거리(km)", color=MUTED, fontsize=FS - 3)
        ax.set_title(f"({'ad'[i]}) {mname}: 준수 차 감속 시작", color=INK, fontsize=FS - 1, loc="left", fontweight="bold")
        ax = axes[i, 1]
        for sc, t, c in SCEN:
            ev = [e for e in res[(m, sc)]["events"] if e["d_tail"] is not None]
            ax.scatter([e["d_tail"] / 1000 for e in ev], [e["dv"] for e in ev], s=7, color=c, alpha=0.55, lw=0, label=f"{t} ({len(ev)})")
        ax.axvline(0, color=INK, lw=0.8, ls=(0, (3, 3)))
        ax.set_xlabel("꼬리까지 거리(km, + = 상류)", color=MUTED, fontsize=FS - 3); ax.set_ylabel("속도 차(km/h)", color=MUTED, fontsize=FS - 3)
        ax.set_title(f"({'be'[i]}) {mname}: 고속 접근 상충", color=INK, fontsize=FS - 1, loc="left", fontweight="bold")
        ax = axes[i, 2]
        for sc, t, c in SCEN:                         # 고속(Δv≥30 km/h) 쌍만: 전체 상충 쌍은 방식 차가 거의 없다(보고서 3절)
            x = np.sort(res[(m, sc)]["ttc_fast"])
            ax.plot(x, np.arange(1, len(x) + 1) / len(x), color=c, lw=1.8, label=f"{t} ({len(x)})")
        ax.axvline(0.75, color=INK, lw=0.8, ls=(0, (3, 3)))
        ax.text(0.68, 0.93, "0.75 s", ha="right", color=INK, fontsize=FS - 6)
        ax.set_xlim(0, 1.5); ax.set_ylim(0, 1)
        ax.set_xlabel("고속 접근 쌍의 최소 TTC(s)", color=MUTED, fontsize=FS - 3); ax.set_ylabel("누적 비율", color=MUTED, fontsize=FS - 3)
        ax.set_title(f"({'cf'[i]}) {mname}: 최소 TTC 누적분포", color=INK, fontsize=FS - 1, loc="left", fontweight="bold")
        ax.legend(frameon=False, fontsize=FS - 6, loc="lower right", handlelength=1.2)
    for ax in axes.flat:
        ax.set_facecolor(SURF)
        for s_ in ("top", "right"):
            ax.spines[s_].set_visible(False)
        for s_ in ("left", "bottom"):
            ax.spines[s_].set_color(MUTED)
        ax.tick_params(colors=MUTED, labelsize=FS - 5)
    for a in axes[:, 1]:
        a.set_xlim(-2.5, 1.5); a.set_ylim(28, 66)    # 이 범위 밖 점은 보고서 2절 표에 수치로(그림은 잘라 보임)
        a.legend(frameon=False, fontsize=FS - 6, loc="upper left", markerscale=2, handletextpad=0.2)
    for a in axes[:, 0]:
        a.set_xlim(-2, 4)
    fig.savefig(OUT, dpi=100, bbox_inches="tight", facecolor=SURF)   # 11 in × 100 px/in ≈ 1100 px 폭
    from PIL import Image                             # 픽셀은 그대로 두고 인쇄 해상도 표기만 300 dpi
    im = Image.open(OUT); im.load(); im.save(OUT, dpi=(300, 300))
    print("saved", OUT)


def f(x, k="{:.1f}"):
    return "—" if x is None else k.format(x)


def iqr(s):
    a, b, c = s["q25_med_q75"]
    return f"{f(b)} ({f(a)}~{f(c)}), n={s['n']}"


def report(out):
    L = ["# 같은 씨앗(23)의 꼬리 접근 장면: Krauss 와 IDM (맥 기록만)", "",
         "입력: `results/mac/p_spacetime_{krauss,idm}.jsonl`(씨앗 23, 방식 3 × 모형 2). `analyze_scenes.py` 가 계산. PC 본 실험 값과 섞지 않는다.", "",
         "정의", "- 꼬리(주) = 프레임마다 30 km/h 미만 차가 사고 지점 500 m 안에서 300 m 미만 간격으로 이어진 줄의 가장 상류 차(tago_sim max_back 규칙), 처리 전만. 앱 꼬리(`record.tail`)는 기준선에 없어 민감도로만.",
         "- 꼬리까지 거리 = 꼬리 x − 차 x(+ = 꼬리 상류). 감속 시작 거리는 사고 뒤 처리 전에 창 들머리(사고 지점 −5.5 km 바깥)로 들어온, 접근 속도(처음 3프레임 중앙값) ≥ 60 km/h 인 차만.",
         "- 감속 시작(주) = 속도가 접근 속도의 90 % 아래로 처음 내려간 프레임. 보조 = 2 s 평균 감속도 ≥ 0.5 m/s² 가 처음 나온 프레임. 준수 = 그 프레임에서 warned=1 ∧ comply=1.",
         "- 상충 = events(TTC<1.5 s ∧ Δv ≥ 30 km/h 가 처음 성립), 후행 차는 가장 가까운 프레임에서 같은 차로·위치(속도로 옮긴 위치 15 m 안)로 연결. 최소 TTC = pairs(TTC<1.5 s 쌍) 첫 값.", ""]
    L += ["## 1. 감속 시작 때 꼬리까지 거리(m, 중앙값 (사분위), n) — 물리 꼬리", "",
          "| 모형 | 방식 | 준수 차 90 % | 그 밖 90 % | 준수 차 0.5 m/s² | 그 밖 0.5 m/s² |", "|---|---|---|---|---|---|"]
    for m, mn in MODELS:
        for sc, t, _ in SCEN:
            o = out[f"{m}|{sc}"]["onset"]["phys"]
            L.append(f"| {mn} | {t} | {iqr(o['v90']['c'])} | {iqr(o['v90']['o'])} | {iqr(o['a05']['c'])} | {iqr(o['a05']['o'])} |")
    L += ["", "앱 꼬리 기준(민감도, 기준선 없음): 준수 차 90 % 정의", "", "| 모형 | 방식 | 준수 차 | 그 밖 |", "|---|---|---|---|"]
    for m, mn in MODELS:
        for sc, t, _ in SCEN[1:]:
            o = out[f"{m}|{sc}"]["onset"]["app"]["v90"]
            L.append(f"| {mn} | {t} | {iqr(o['c'])} | {iqr(o['o'])} |")
    L += ["", "두 정의가 다 잡힌 차의 (0.5 m/s² 시각 − 90 % 시각, s) 중앙값 (사분위): " +
          "; ".join(f"{mn} {t} {iqr(out[f'{m}|{sc}']['a05_minus_v90_s'])}" for m, mn in MODELS for sc, t, _ in SCEN), ""]
    L += ["접근 모양(90 % 정의로 감속이 잡힌 차; 준수 차 / 그 밖): 접근 속도 km/h, 물리 꼬리 500 m 앞을 처음 지날 때 속도 km/h, 줄(30 km/h 미만) 합류 전 최대 2 s 평균 감속도 m/s²", "",
          "| 모형 | 방식 | 접근 속도 준수 / 그 밖 | 꼬리 500 m 앞 속도 준수 / 그 밖 | 최대 감속도 준수 / 그 밖 |", "|---|---|---|---|---|"]
    for m, mn in MODELS:
        for sc, t, _ in SCEN:
            pr = out[f"{m}|{sc}"]["profile"]
            L.append(f"| {mn} | {t} | " + " | ".join(f"{iqr(pr['c'][k])} / {iqr(pr['o'][k])}" for k in ("v_app", "v500", "amax")) + " |")
    L += ["", "## 2. 고속 접근 상충(events)", "",
          "| 모형 | 방식 | 건수(처리 뒤) | 후행 속도 km/h | 속도 차 km/h | 꼬리까지 거리 m | 꼬리 상류 비율 | 연결 | 후행=준수 차 | 후행=경고 받음 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m, mn in MODELS:
        for sc, t, _ in SCEN:
            e = out[f"{m}|{sc}"]["events"]
            L.append(f"| {mn} | {t} | {e['n']} ({e['n_post']}) | {iqr(e['vf'])} | {iqr(e['dv'])} | {iqr(e['d_tail'])} | {f(e['d_tail_upstream_share'], '{:.0%}')} | {e['matched']} | {f(e['comply_share'], '{:.0%}')} | {f(e['warned_share'], '{:.0%}')} |")
    L += ["", "후행 차 집단별 중앙값(준수 / 그 밖): Δv km/h · 꼬리까지 거리 m", ""]
    for m, mn in MODELS:
        for sc, t, _ in SCEN:
            c = out[f"{m}|{sc}"]["events"]["comply"]
            L.append(f"- {mn} {t}: 준수 n={c['c']['n']} Δv {f(c['c']['dv'])} · {f(c['c']['d_tail'])} m / 그 밖 n={c['o']['n']} Δv {f(c['o']['dv'])} · {f(c['o']['d_tail'])} m")
    L += ["", "## 3. 쌍별 최소 TTC(TTC<1.5 s 쌍)", "",
          "| 모형 | 방식 | 쌍 | 중앙값 s | 10 % 분위 s | <0.75 s | 고속(Δv≥30) 쌍 | 고속 중앙값 | 고속 10 % | 고속 <0.75 s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m, mn in MODELS:
        for sc, t, _ in SCEN:
            x = out[f"{m}|{sc}"]["ttc"]
            L.append(f"| {mn} | {t} | {x['n']} | {x['med']:.2f} | {x['p10']:.2f} | {x['lt075']:.0%} | {x['fast_n']} | {f(x['fast_med'], '{:.2f}')} | {f(x['fast_p10'], '{:.2f}')} | {f(x['fast_lt075'], '{:.0%}')} |")
    L += ["", "## 해석", "", "(INTERP)", "", "그림: `docs/figures/fig14_cf_scenes.png`"]
    p = RES / "report_scenes.md"
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    interp = old.split("## 해석", 1)[1].split("그림:", 1)[0].strip() if "## 해석" in old else "(INTERP)"
    p.write_text("\n".join(L).replace("(INTERP)", interp) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
