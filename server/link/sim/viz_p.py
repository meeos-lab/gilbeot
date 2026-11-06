"""검토 C-3 그림: v2 대표 씨앗(23)의 시공간도 3장 + 고속 접근 상충 위치 + 꼬리로부터 거리별 상충 분포.

  python -X utf8 viz_p.py        # results/p_spacetime.jsonl 만 읽는다(새 시뮬레이션 없음) → docs/figures/fig13_spacetime_v2.png
문법은 viz2.py(v1 시공간도)와 같다: 가로 = 사고 뒤 시간(분), 세로 = 사고 지점까지 거리(km, 음수 = 상류), 색 = 평균 속도(진할수록 느림).
(d) 의 꼬리는 그림용 근사다: 10 s 열마다 사고 지점 칸(xi=199)부터 상류로 내려가며 평균 속도 < 30 km/h 인 칸을 잇고,
빠른(또는 빈) 칸이 300 m(3칸) 넘게 이어지면 멈춘 뒤 그 줄의 가장 상류 칸을 꼬리로 둔다. 길벗의 꼬리(앱 차 기준)와 다르다.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE.parents[2] / "docs" / "figures" / "fig13_spacetime_v2.png"
FONTS = sorted((HERE / "results" / "_work" / "fonts").glob("NotoSansKR-*.ttf"))
for f in FONTS or [Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/malgunbd.ttf")]:
    if f.exists():
        font_manager.fontManager.addfont(str(f))
plt.rcParams["font.family"] = "Noto Sans KR" if FONTS else "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
RAMP = ["#f1effe", "#d6d0fb", "#b3a8f5", "#8c7cee", "#6c5ce7", "#4b3bc4", "#2e2185"]
CMAP = LinearSegmentedColormap.from_list("slow", RAMP)
INK, MUTED, SURF, CRASH, GREY, PURP = "#1f2430", "#3f4553", "#ffffff", "#e8607a", "#9aa0ab", "#4b3bc4"

INC_POS, LEN, T_INC = 20000.0, 22000.0, 900.0      # v2 환경(p_spacetime 실행 조건)
SLOW, GAP = 30 / 3.6, 3                             # 꼬리: < 30 km/h, 끊김 3칸(300 m)까지 허용
SCEN = [("official", "(a) 기준선", GREY), ("official+tago12+relay", "(b) 단계 90·70·50", CRASH),
        ("official+tago12+relay-u80", "(c) 일률 80", PURP)]
BINS = np.arange(-2000, 6001, 500)                  # d 칸 경계(m); 밖은 양 끝 칸에 모은다
FS = 16                                             # figsize 11 in → A4 본문 폭 16 cm 에서 약 9.2 pt


def load():
    rows = {}
    for line in (HERE / "results" / "p_spacetime.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        r["record"].pop("frames", None)
        rows[r["scheme"]] = r
    return [rows[sc] for sc, _, _ in SCEN]


def grid_of(rec):
    nt, nx = int((rec["t_clear"] + 900) // 10) + 2, int(LEN // 100) + 1
    g = np.full((nx, nt), np.nan)
    for ti, xi, v in rec["grid"]:
        if ti < nt and xi < nx:
            g[int(xi), int(ti)] = v
    return g


def tail_series(g, t_clear):
    """열 ti → 꼬리 위치(m). 처리 중(T_INC ≤ t < t_clear) 열만."""
    xi0 = int(INC_POS // 100) - 1                   # 199: 사고 지점 바로 상류 칸
    tail = {}
    for ti in range(int(T_INC // 10), int(np.ceil(t_clear / 10))):
        col, last, gap = g[:, ti], None, 0
        for xi in range(xi0, -1, -1):
            if col[xi] < SLOW:                      # NaN 은 느리지 않음
                last, gap = xi, 0
            else:
                gap += 1
                if gap > GAP:
                    break
        tail[ti] = last * 100.0 if last is not None else INC_POS
    return tail


def dist(r):
    rec = r["record"]
    tail = tail_series(grid_of(rec), rec["t_clear"])
    d, after, before = [], 0, 0
    for t, x, _lane in rec["events"]:
        if t >= rec["t_clear"]:
            after += 1
        elif t < T_INC:
            before += 1
        else:
            d.append(tail[int(t // 10)] - x)
    return np.array(d), after, before, tail


def main():
    res = load()
    t_clear = res[0]["record"]["t_clear"]
    qmax = max(r["queue_km"] for r in res)
    fig = plt.figure(figsize=(11, 10.2), facecolor=SURF)
    gs = fig.add_gridspec(2, 3, width_ratios=[1, 1, 0.045], wspace=0.28, hspace=0.42)
    axes = np.array([[fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])],
                     [fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1])]])
    cax = fig.add_subplot(gs[0, 2])
    ax_st = [axes[0, 0], axes[0, 1], axes[1, 0]]
    t0, t1 = -5, (t_clear - T_INC) / 60 + 10
    ylo = -(qmax + 1.5)
    stats = []
    for ax, r, (sc, title, _c) in zip(ax_st, res, SCEN):
        rec = r["record"]
        g = grid_of(rec) * 3.6
        nx, nt = g.shape
        ext = [(0 - T_INC) / 60, (nt * 10 - T_INC) / 60, (0 - INC_POS) / 1000, (nx * 100 - INC_POS) / 1000]
        im = ax.imshow(110 - np.clip(g, 0, 110), origin="lower", aspect="auto", cmap=CMAP, vmin=0, vmax=110,
                       extent=ext, interpolation="nearest")
        ax.set_xlim(t0, t1); ax.set_ylim(ylo, 1.0); ax.set_facecolor(SURF)
        ax.axhline(0, color=INK, lw=0.8, ls=(0, (3, 3)))
        ax.plot([0, (t_clear - T_INC) / 60], [0, 0], color=CRASH, lw=3.5, solid_capstyle="butt")
        ev = np.array(rec["events"])
        ax.scatter((ev[:, 0] - T_INC) / 60, (ev[:, 1] - INC_POS) / 1000, s=9, c=INK, edgecolors=CRASH, linewidths=0.5,
                   alpha=0.6, zorder=3)
        marks = [((rec["official_at"] - T_INC) / 60, "공식")]
        if rec["relay_at"] is not None:
            marks.insert(0, ((rec["relay_at"] - T_INC) / 60, "길벗 연계"))
        for i, (wt, lab) in enumerate(marks):
            ax.axvline(wt, color=INK, lw=1.0)
            ax.text(wt + 0.4, ylo + 0.3, lab, color=INK, fontsize=FS,
                    bbox=dict(facecolor=SURF, edgecolor="none", pad=1, alpha=0.85))
        ax.set_title(title, color=INK, fontsize=FS + 2, loc="left", fontweight="bold", pad=26)
        ax.text(0, 1.015, f"고속 접근 {r['fast']}건 · 정체 {r['queue_km']:.1f} km", color=INK, fontsize=FS,
                transform=ax.transAxes, va="bottom")
        for s_ in ax.spines.values():
            s_.set_visible(False)
        ax.tick_params(colors=MUTED, labelsize=FS)
        stats.append(dist(r))
    for ax in (axes[0, 0], axes[1, 0]):
        ax.set_ylabel("사고 지점까지 거리(km)", color=MUTED, fontsize=FS)
    for ax in (axes[0, 1], axes[1, 0]):
        ax.set_xlabel("사고 후 시간(분)", color=MUTED, fontsize=FS)
    cb = fig.colorbar(im, cax=cax)
    cb.set_ticks([0, 30, 60, 90, 110]); cb.set_ticklabels(["110", "80", "50", "20", "0"])
    cb.set_label("평균 속도(km/h)", color=MUTED, fontsize=FS); cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, labelsize=FS)

    # (d) 꼬리로부터 거리별 상충 비율(%) — 마지막 칸 = 처리 뒤
    ax = axes[1, 1]
    nb = len(BINS) - 1
    xs = np.arange(nb + 1)
    w = 0.28
    for k, ((d, after, before, _), (sc, title, colr)) in enumerate(zip(stats, SCEN)):
        h, _ = np.histogram(np.clip(d, BINS[0], BINS[-1] - 1), bins=BINS)
        tot = len(d) + after + before
        vals = np.append(h, after) / tot * 100
        ax.bar(xs + (k - 1) * w, vals, width=w, color=colr, label=title[4:], lw=0)
    ax.axvline(3.5, color=INK, lw=0.8, ls=(0, (3, 3)))           # 칸 4 = d 0~0.5 km 의 왼쪽 경계 = 꼬리
    ax.axvline(nb - 0.5, color=MUTED, lw=0.8)
    labs = [f"{BINS[i] / 1000:g}" for i in range(nb)]
    ax.set_xticks([i - 0.5 for i in range(0, nb, 2)] + [nb])     # 눈금 = 칸 경계
    ax.set_xticklabels([labs[i] for i in range(0, nb, 2)] + ["처리\n뒤"])
    ax.set_xlabel("꼬리로부터 거리(km, + = 꼬리 상류)", color=MUTED, fontsize=FS)
    ax.set_ylabel("고속 접근 상충 비율(%)", color=MUTED, fontsize=FS)
    ax.set_title("(d) 꼬리로부터 거리별 상충", color=INK, fontsize=FS + 2, loc="left", fontweight="bold", pad=26)
    ax.legend(frameon=False, fontsize=FS, loc="upper left", bbox_to_anchor=(0.27, 0.9))
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    for s_ in ("left", "bottom"):
        ax.spines[s_].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=FS)
    ax.text(3.65, ax.get_ylim()[1] * 0.97, "꼬리", color=INK, fontsize=FS, va="top")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=200, bbox_inches="tight", facecolor=SURF)

    for (d, after, before, tail), (sc, title, _), r in zip(stats, SCEN, res):
        tot = len(d) + after + before
        near = ((d >= 0) & (d < 2000)).sum()
        inside = (d < 0).sum()
        far = (d >= 2000).sum()
        tv = np.array(list(tail.values()))
        print(f"{title}: n={tot} (rec fast {r['fast']}) 꼬리상류0~2km {near} ({near / tot:.1%}) "
              f"꼬리안쪽(<0) {inside} ({inside / tot:.1%}) 2km+ {far} ({far / tot:.1%}) "
              f"처리뒤 {after} ({after / tot:.1%}) 처리전 {before}; 꼬리 최대 {(INC_POS - tv.min()) / 1000:.2f} km")
    print("cond", res[0]["cond"], "inc_at", [r["inc_at"] for r in res])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
