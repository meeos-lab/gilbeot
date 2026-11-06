"""논문 보강 그림 4장(fig15–fig18). 결과 JSON 만 읽는다(새 시뮬레이션 없음).

  python -X utf8 figs_extra.py        # server/link/sim 에서 → docs/figures/fig15_grid_heatmap.png …fig18_summary.png

  fig15  5.5절  준수율 × 보급률 격자: 일률 80 대 단계 변화율 열지도(고속 접근 + 심각)   results/report_p6_mac_s1-12.json  grid 'ug|…'
  fig16  4.6절  처리 중·처리 뒤 분해: 일률 80 − 단계 평균 건수 차(Krauss·IDM)          results/report_p10.json           cells '{모형}|u80_vs_graded|{a|bc}'
  fig17  5.4절  공식 지연 실측 분포 추출별 기준선 대비 고속 접근 변화율(숲 그림)       results/report_p4.json            cells 'chg|{u80|graded}|fast|{1..4|all}'
                779초 가정 행 = 본 실험 Krauss(results/report_c.json recs …|fast|krauss; 표 2·그림 6 과 같은 평균)
  fig18  초록 뒤 한눈에 보는 결과 3칸: (a) report_v2.json schemes …vs_official.fast(감소율 → 부호 바꿈) + report_c.json u80
                (b) report_c.json recs {graded|u80}|fast|{krauss|idm}   (c) report_p6_mac_s1-12.json grid 'ug|{cp}|12|fast'
글꼴·색·저장 규약은 viz_p.py(Noto Sans KR, 흰 배경)와 docs/paper-build/figgen/kit.py(보라 = 감소·일률 80·IDM, 코랄 = 증가·단계·Krauss,
검정 글자, 얇은 괘선)를 따른다. 폭 16 cm, 300 dpi. 손으로 적은 수치는 fig18(c) 의 준수율 참고 띠(원고 4.8절 P8 문단) 뿐이다.
"""
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).parent
RES = HERE / "results"
FIGS = HERE.parents[2] / "docs" / "figures"
FONTS = sorted((RES / "_work" / "fonts").glob("NotoSansKR-*.ttf"))
for f in FONTS or [Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/malgunbd.ttf")]:
    if f.exists():
        font_manager.fontManager.addfont(str(f))
plt.rcParams["font.family"] = "Noto Sans KR" if FONTS else "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
# kit.py 의 색(그림 6·fig12 와 같은 표식 색)
VIO, VIO_D, COR, INK, SUB, MUT, GRID = "#6C5CE7", "#4b3bc4", "#E8607A", "#1F2430", "#3F4553", "#6B7180", "#E1E4EB"
SURF = "#ffffff"
DIV = LinearSegmentedColormap.from_list("div", ["#5a49d6", "#8c7cee", "#d6d0fb", "#ffffff", "#f8d3da", "#ef94a6", "#e0466a"])
W_IN = 16 / 2.54               # 본문 폭 16 cm
DPI = 300
FS = 8                         # pt (실제 크기 그대로 인쇄)


def load(name):
    return json.loads((RES / name).read_text(encoding="utf-8"))


def sgn(v, d=1):
    s = f"{abs(v):.{d}f}"
    return ("+" if v > 0 and s.strip("0.") else "−" if v < 0 and s.strip("0.") else "") + s


def excl0(ci):
    return ci[0] > 0 or ci[1] < 0


def style(ax, grid_axis="x"):
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    for s_ in ("left", "bottom"):
        ax.spines[s_].set_color(SUB)
        ax.spines[s_].set_linewidth(0.8)
    ax.tick_params(colors=SUB, labelsize=FS, width=0.8, length=3)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, lw=0.6)
        ax.set_axisbelow(True)


def save(fig, name):
    out = FIGS / name
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, bbox_inches="tight", pad_inches=0.04, facecolor=SURF)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------- fig15
CPS = [0.05, 0.25, 0.45, 0.65, 0.85]
PENS = ["1.5", "12", "50"]


def fig15():
    d = load("report_p6_mac_s1-12.json")["grid"]
    mats = {}
    for ind in ("fast", "severe"):
        mats[ind] = [[d[f"ug|{cp}|{p}|{ind}"] for p in PENS] for cp in CPS]
    n = {v["n_used"] for ind in mats for row in mats[ind] for v in row}
    vmax = math.ceil(max(abs(v["mean"]) for ind in mats for row in mats[ind] for v in row) / 10) * 10
    fig = plt.figure(figsize=(W_IN, 3.25), facecolor=SURF)
    axA = fig.add_axes([0.10, 0.17, 0.43, 0.70])
    axB = fig.add_axes([0.585, 0.17, 0.275, 0.70])
    cax = fig.add_axes([0.885, 0.17, 0.016, 0.70])
    for ax, ind, title, big in ((axA, "fast", "(a) 고속 접근(주 지표)", True), (axB, "severe", "(b) 심각", False)):
        M = np.array([[c["mean"] for c in row] for row in mats[ind]])
        im = ax.imshow(M, origin="lower", cmap=DIV, vmin=-vmax, vmax=vmax, aspect="auto")
        for i, row in enumerate(mats[ind]):
            for j, c in enumerate(row):
                sig = excl0(c["ci"])
                dark = abs(c["mean"]) > 0.6 * vmax
                ax.text(j, i + (0.12 if big else 0.13), sgn(c["mean"]), ha="center", va="center", color=SURF if dark else INK,
                        fontsize=FS + (1 if big else 0), fontweight="bold" if sig else "normal")
                ax.text(j, i - 0.24, f"{sgn(c['ci'][0])} ~ {sgn(c['ci'][1])}", ha="center", va="center",
                        color=SURF if dark else SUB, fontsize=FS - (1.5 if big else 2.6))
                if sig:
                    ax.add_patch(Rectangle((j - 0.47, i - 0.47), 0.94, 0.94, fill=False, ec=INK, lw=1.3))
        ax.set_xticks(range(3), [f"{p} %" for p in PENS])
        ax.set_yticks(range(5), [f"{round(cp * 100)} %" for cp in CPS] if big else [])
        ax.set_xlabel("길벗 보급률", color=SUB, fontsize=FS)
        if big:
            ax.set_ylabel("준수율", color=SUB, fontsize=FS)
        ax.set_title(title, loc="left", color=INK, fontsize=FS + 1, fontweight="bold", pad=5)
        for s_ in ax.spines.values():
            s_.set_visible(False)
        ax.tick_params(colors=SUB, labelsize=FS, length=0)
        ax.set_xticks(np.arange(-0.5, 3, 1), minor=True)
        ax.set_yticks(np.arange(-0.5, 5, 1), minor=True)
        ax.grid(which="minor", color=SURF, lw=1.5)
        ax.tick_params(which="minor", length=0)
    cb = fig.colorbar(im, cax=cax)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=SUB, labelsize=FS - 1, length=2)
    cb.set_ticks(np.linspace(-vmax, vmax, 5), labels=[sgn(v, 0) for v in np.linspace(-vmax, vmax, 5)])
    cb.set_label("일률 80 대 단계 변화율(%)\n← 일률 80이 적음   일률 80이 많음 →", color=SUB, fontsize=FS - 0.5)
    fig.text(0.10, 0.015, f"칸: 씨앗별 (일률 80 − 단계)/단계 × 100의 평균과 95 % CI(씨앗 {min(n)}개, 부트스트랩 10,000회). "
             "굵은 글자·테두리 = CI가 0을 벗어남.", color=SUB, fontsize=FS - 1)
    save(fig, "fig15_grid_heatmap.png")
    return mats


# ---------------------------------------------------------------- fig16
def fig16():
    c = load("report_p10.json")["cells"]
    phases = [("a", "처리 중"), ("bc", "처리 뒤")]
    models = [("Krauss", COR, -0.14), ("IDM", VIO, 0.14)]
    fig, ax = plt.subplots(figsize=(W_IN, 3.0), facecolor=SURF)
    out = {}
    for m, col, off in models:
        for k, (ph, lab) in enumerate(phases):
            dd = c[f"{m}|u80_vs_graded|{ph}"]["diff"]
            out[(m, ph)] = dd
            x = k + off
            ax.errorbar(x, dd["mean"], yerr=[[dd["mean"] - dd["ci"][0]], [dd["ci"][1] - dd["mean"]]], fmt="o",
                        color=col, ms=5.5, mec=SURF, mew=0.8, elinewidth=1.2, capsize=3, capthick=1.2,
                        label=m if k == 0 else None, zorder=3)
            ax.text(x, dd["ci"][1] + 4, f"{sgn(dd['mean'])}\n({sgn(dd['ci'][0])} ~ {sgn(dd['ci'][1])})",
                    va="bottom", ha="center", color=INK, fontsize=FS - 1, linespacing=1.15,
                    fontweight="bold" if excl0(dd["ci"]) else "normal")
    ax.axhline(0, color=INK, lw=0.9)
    ax.set_xticks(range(2), [lab for _, lab in phases])
    ax.set_xlim(-0.6, 1.6)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: sgn(v, 0)))
    ax.set_ylabel("일률 80 − 단계\n고속 접근 상충(건/실행)", color=SUB, fontsize=FS, linespacing=1.4)
    ax.set_ylim(-180, 125)
    style(ax, "y")
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="x", length=0, labelsize=FS + 0.5, colors=INK)
    n = c["Krauss|u80_vs_graded|a"]["diff"]["n"]
    ax.legend(frameon=False, fontsize=FS, loc="upper right", ncol=2, handletextpad=0.3)
    ax.text(1.0, -0.13, f"점: 씨앗별 차이의 평균, 막대: 95 % CI(씨앗 {n}개, 부트스트랩 10,000회). 굵은 숫자 = CI가 0을 벗어남.",
            transform=ax.transAxes, ha="right", va="top", color=SUB, fontsize=FS - 1)
    save(fig, "fig16_phase_split.png")
    return out


# ---------------------------------------------------------------- fig17
def fig17():
    c = load("report_p4.json")["cells"]
    rc = load("report_c.json")["recs"]
    rows = [(f"추출 {i}", str(i)) for i in range(1, 5)] + [("추출 1–4 합산", "all")]
    schemes = [("일률 80", "u80", VIO, -0.15), ("단계 90·70·50", "graded", COR, 0.15)]
    ys = [6, 5, 4, 3, 2]            # 위에서 아래로; 779초 행은 y = 0.6
    fig, ax = plt.subplots(figsize=(W_IN, 3.4), facecolor=SURF)
    out = {}
    for name, key, col, off in schemes:
        for (lab, r), y in zip(rows, ys):
            v = c[f"chg|{key}|fast|{r}"]
            out[(key, r)] = v
            ax.plot(v["ci"], [y + off] * 2, color=col, lw=1.3, solid_capstyle="butt")
            ax.plot(v["mean"], y + off, "o", color=col, ms=5 if r != "all" else 6.5, mec=SURF, mew=0.8, zorder=3,
                    label=name if r == "1" else None)
        v = rc[key]["fast"]["krauss"]          # 본 실험(779초), 표 2·그림 6 과 같은 평균
        out[(key, "779")] = v
        y = 0.6
        ax.plot(v["ci"], [y + off] * 2, color=col, lw=1.3, ls=(0, (2, 1.2)))
        ax.plot(v["mean"], y + off, "D", color=col, ms=5, mec=SURF, mew=0.8, zorder=3)
    ax.axhline(1.45, color=GRID, lw=0.8)
    ax.axhline(2.55, color=GRID, lw=0.6, ls=(0, (2, 2)))
    ax.axvline(0, color=INK, lw=0.9)
    ax.set_yticks(ys + [0.6], [lab for lab, _ in rows] + ["779초 가정(본 실험)"])
    for t_ in ax.get_yticklabels()[4:]:
        t_.set_fontweight("bold")
    lo = min(v["ci"][0] for v in out.values())
    hi = max(v["ci"][1] for v in out.values())
    xl = (math.floor(lo / 10) * 10, math.ceil(hi / 10) * 10)
    ax.set_xlim(xl[0], xl[1] + 32)
    ax.set_ylim(-0.1, 6.6)
    tx = xl[1] + 3
    ax.text(tx, 6.45, "일률 80", color=VIO_D, fontsize=FS - 0.5, fontweight="bold", va="bottom")
    ax.text(tx + 15, 6.45, "단계", color=COR, fontsize=FS - 0.5, fontweight="bold", va="bottom")
    for (lab, r), y in list(zip(rows, ys)) + [(("779", "779"), 0.6)]:
        for k, (_, key, _, _) in enumerate(schemes):
            v = out[(key, r)]
            ax.text(tx + 15 * k, y, sgn(v["mean"]), va="center", color=INK, fontsize=FS)
    ax.set_xticks([t for t in range(xl[0], xl[1] + 1, 10)],
                  [sgn(t, 0) for t in range(xl[0], xl[1] + 1, 10)])
    ax.set_xlabel("기준선 대비 고속 접근 상충 변화율(%, 음수 = 감소)", color=SUB, fontsize=FS)
    style(ax, "x")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0, colors=INK)
    ax.spines["bottom"].set_bounds(*xl)
    ax.legend(frameon=False, fontsize=FS, loc="lower left", bbox_to_anchor=(0.0, 0.99), ncol=2, handletextpad=0.2)
    n4 = c["chg|u80|fast|all"]
    n779 = rc["u80"]["fast"]["krauss"]["n_used"]
    ax.text(0.0, -0.19, f"추출: 실측 등록 지연에서 씨앗마다 추출(추출당 씨앗 {c['chg|u80|fast|1']['n_used']}개, 합산 {n4['n_values']}쌍)."
            f"  ◆ 점선: 공식 지연 779초(씨앗 {n779}개).  선 = 95 % CI.",
            transform=ax.transAxes, ha="left", va="top", color=SUB, fontsize=FS - 1)
    save(fig, "fig17_delay_draws.png")
    return out


# ---------------------------------------------------------------- fig18
BAND_CP = (29, 44)       # 국내 실측 위험구간 경고 준수율(김윤미 외 2023 광주 29 %, 김탁영 외 2022 서울 44 %; 원고 4.8절 P8 문단)
MEAN_CP = 41             # 본 실험 준수율 분포의 평균(원고 4.8절 P8 문단·5.5절)


def fig18():
    v2 = load("report_v2.json")["schemes"]
    rc = load("report_c.json")["recs"]
    grid = load("report_p6_mac_s1-12.json")["grid"]

    def v2fast(k):     # report_v2 는 감소율(양수 = 감소)로 저장 → 변화율로 부호 바꿈
        f = v2[k]["vs_official"]["fast"]
        return {"mean": -f["mean"] * 100, "ci": sorted([-f["ci"][0] * 100, -f["ci"][1] * 100]), "n": f["n"]}

    # 표 2 의 다섯 행(같은 평균): 경고 없음, 길벗 12 % 단독, 기준선 + 길벗 12 %, + 연계 단계, + 연계 일률 80(report_c, Krauss)
    bars = [("공식 안내 없음", v2fast("none")), ("앱 단독(대체)", v2fast("tago12")),
            ("기존 안내 + 길벗", v2fast("official+tago12")),
            ("연계 · 단계 권고", v2fast("official+tago12+relay")),
            ("연계 · 일률 80", dict(rc["u80"]["fast"]["krauss"]))]
    fig = plt.figure(figsize=(W_IN, 2.75), facecolor=SURF)
    axA = fig.add_axes([0.155, 0.20, 0.165, 0.62])
    axB = fig.add_axes([0.47, 0.20, 0.165, 0.62])
    axC = fig.add_axes([0.745, 0.20, 0.245, 0.62])
    heads = [(0.0, "권고 방식별 고속 접근 상충"), (0.395, "추종 모형에 따른 순위 역전"),
             (0.665, "준수율별 일률 80 대 단계")]
    for i, (x, h) in enumerate(heads):
        fig.text(x, 0.965, f"({'abc'[i]}) {h}", fontsize=FS - 0.3, fontweight="bold", color=INK, va="top")
    # (a) 가로 막대 + 얇은 CI, 수치는 오른쪽 열
    ys = np.arange(len(bars))[::-1]
    for (lab, v), y in zip(bars, ys):
        axA.barh(y, v["mean"], height=0.62, color=COR if v["mean"] > 0 else VIO_D, lw=0)
        axA.plot(v["ci"], [y, y], color=INK, lw=0.7)
        axA.text(1.04, y, sgn(v["mean"]), transform=axA.get_yaxis_transform(), ha="left", va="center",
                 fontsize=FS - 0.5, color=COR if v["mean"] > 0 else VIO_D, fontweight="bold")
    axA.set_yticks(ys, [b[0] for b in bars])
    axA.axvline(0, color=INK, lw=0.9)
    axA.set_xlim(-30, 46)
    axA.set_xticks([-20, 0, 20, 40], ["−20", "0", "+20", "+40"])
    axA.set_xlabel("기준선 대비 고속 접근(%)", color=SUB, fontsize=FS - 0.5)
    style(axA, "x")
    axA.spines["left"].set_visible(False)
    axA.tick_params(axis="y", length=0, colors=INK, labelsize=FS - 0.5)
    axA.tick_params(axis="x", labelsize=FS - 1)
    # (b) 경사 그림: 단계 → 일률 80, 모형별 선
    for m, lab, col in (("krauss", "Krauss", COR), ("idm", "IDM", VIO)):
        pts = [rc[k]["fast"][m] for k in ("graded", "u80")]
        axB.plot([0, 1], [p["mean"] for p in pts], color=col, lw=1.4, zorder=2)
        for x, p in zip([0, 1], pts):
            axB.errorbar(x, p["mean"], yerr=[[p["mean"] - p["ci"][0]], [p["ci"][1] - p["mean"]]], fmt="o", color=col,
                         ms=4.5, mec=SURF, mew=0.7, elinewidth=0.9, capsize=2.2, zorder=3)
        axB.text(-0.12, pts[0]["mean"], sgn(pts[0]["mean"]), ha="right", va="center", fontsize=FS - 1.2, color=INK)
        axB.text(1.12, pts[1]["mean"], sgn(pts[1]["mean"]), ha="left", va="center", fontsize=FS - 1.2, color=INK)
        axB.text(0.55 if m == "krauss" else 0.5, 17 if m == "krauss" else -40, lab, ha="center", va="bottom" if m == "krauss" else "top",
                 fontsize=FS - 1, color=col, fontweight="bold")
    axB.axhline(0, color=INK, lw=0.9)
    axB.set_xlim(-0.95, 1.85)
    axB.set_ylim(-45, 30)
    axB.set_xticks([0, 1], ["단계", "일률 80"])
    axB.set_yticks([-40, -20, 0, 20], ["−40", "−20", "0", "+20"])
    axB.set_ylabel("기준선 대비 고속 접근(%)", color=SUB, fontsize=FS - 0.5)
    style(axB, "y")
    axB.spines["bottom"].set_bounds(-0.5, 1.5)
    axB.tick_params(axis="x", length=0, colors=INK, labelsize=FS - 0.5)
    axB.tick_params(axis="y", labelsize=FS - 1)
    # (c) 보급 12 % 에서 준수율별 일률 80 대 단계
    xs = [round(cp * 100) for cp in CPS]
    cells = [grid[f"ug|{cp}|12|fast"] for cp in CPS]
    axC.axvspan(*BAND_CP, ymin=0.1, ymax=0.83, color=GRID, alpha=0.9, lw=0, zorder=0)
    axC.axvline(MEAN_CP, ymin=0.1, ymax=0.83, color=SUB, lw=0.8, ls=(0, (2, 1.5)), zorder=1)
    axC.fill_between(xs, [c_["ci"][0] for c_ in cells], [c_["ci"][1] for c_ in cells], color=VIO, alpha=0.18, lw=0)
    axC.plot(xs, [c_["mean"] for c_ in cells], color=VIO_D, lw=1.4, marker="o", ms=3.5, mec=SURF, mew=0.6)
    axC.axhline(0, color=INK, lw=0.9)
    axC.set_xticks(xs, [f"{x}" for x in xs])
    axC.set_xlim(0, 90)
    axC.set_ylim(-46, 28)
    axC.set_yticks([-40, -20, 0, 20], ["−40", "−20", "0", "+20"])
    axC.set_xlabel("준수율(%)", color=SUB, fontsize=FS - 0.5)
    axC.set_ylabel("일률 80 대 단계(%)", color=SUB, fontsize=FS - 0.5)
    style(axC, None)
    axC.tick_params(labelsize=FS - 1)
    axC.text(BAND_CP[1] + 2.5, 27, f"띠 = 국내 실측 {BAND_CP[0]}–{BAND_CP[1]} %\n점선 = 본 실험 평균 {MEAN_CP} %", ha="left",
             va="top", fontsize=FS - 2, color=SUB, linespacing=1.25)
    axC.text(89, -45, "음수 = 일률 80이 적음", ha="right", va="bottom", fontsize=FS - 2, color=SUB)
    fig.text(0.0, 0.0, f"(a) Krauss, 앱 조건은 길벗 보급 12 %(표 2). (b) 같은 씨앗, IDM b = 2 m/s², T = 0.4 s. "
             f"(a)·(b) 씨앗 {bars[0][1]['n']}개, 선 = 95 % CI. (c) 보급 12 %, 씨앗 {cells[0]['n_used']}개(Mac), 띠 = 95 % CI.",
             fontsize=FS - 1.5, color=SUB, va="bottom")
    save(fig, "fig18_summary.png")
    return bars, {m: [rc[k]["fast"][m] for k in ("graded", "u80")] for m in ("krauss", "idm")}, cells


if __name__ == "__main__":
    mats = fig15()
    p10 = fig16()
    p4 = fig17()
    bars, cf, cells = fig18()
    print("fig15 fast 12%:", [(cp, round(r[1]["mean"], 1), [round(x, 1) for x in r[1]["ci"]]) for cp, r in zip(CPS, mats["fast"])])
    print("fig16:", {k: (round(v["mean"], 1), [round(x, 1) for x in v["ci"]]) for k, v in p10.items()})
    print("fig17:", {k: (round(v["mean"], 1), [round(x, 1) for x in v["ci"]]) for k, v in p4.items()})
    print("fig18a:", [(b, round(v["mean"], 1), [round(x, 1) for x in v["ci"]]) for b, v in bars])
    print("fig18b:", {k: [round(p["mean"], 1) for p in v] for k, v in cf.items()})
