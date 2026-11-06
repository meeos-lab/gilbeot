"""queue_sim 시각화: 시공간 속도도(경고 없음 / 공식 6분31초 / Tago 20 %)와 애니메이션용 차 위치(JSON).

사용: python -X utf8 viz.py [씨앗=1]  →  spacetime.png, frames.json
가로 = 시간(분), 세로 = 위치(km, 위로 갈수록 하류), 색 = 평균 속도(진할수록 느림). 같은 씨앗이라 들어오는 차가 같다.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
import numpy as np  # noqa: E402

import queue_sim as q  # noqa: E402

HERE = Path(__file__).parent
for f in ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"):
    if Path(f).exists():
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
# 순차 한 색(파랑): 옅음 = 잘 흐름, 진함 = 느림(데이터 시각화 기준 팔레트의 blue 100→700)
RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
CMAP = LinearSegmentedColormap.from_list("slow", RAMP)
INK, MUTED, SURF = "#1f1f1d", "#6b6b66", "#fcfcfb"

SCEN = [("none", 0.0, "경고 없음"), ("official_full", 0.0, "공식 안내 · 12분 59초 뒤(인지+안내 평균)"), ("tago", 0.2, "Tago · 보급 20%"), ("official_full+tago", 0.2, "공식 12분 59초 + Tago 20%")]


def grid(rec):
    nt, nx = int(q.T_END // 10) + 1, int(q.LEN // 100)
    g = np.full((nx, nt), np.nan)
    for (ti, xi), (sv, n) in rec["grid"].items():
        if xi < nx and ti < nt and n:
            g[xi, ti] = sv / n * 3.6
    return g


def main(seed=1):
    q.build_net()
    recs, stats = [], []
    for sc, p, _ in SCEN:
        rec = {}
        r = q.run(sc, p, seed, record=rec)
        recs.append(rec); stats.append(r)
        print(sc, p, r, flush=True)
    fig, axes = plt.subplots(1, len(SCEN), figsize=(5 * len(SCEN), 5.4), sharey=True, facecolor=SURF)
    t0, t1 = (q.T_INC - 300) / 60, q.T_END / 60
    for ax, rec, r, (sc, p, title) in zip(axes, recs, stats, SCEN):
        g = grid(rec)
        im = ax.imshow(110 - np.clip(g, 0, 110), origin="lower", aspect="auto", cmap=CMAP, vmin=0, vmax=110,
                       extent=[0, q.T_END / 60, 0, q.LEN / 1000], interpolation="nearest")
        ax.set_xlim(t0, t1)
        ax.set_facecolor(SURF)
        ax.axhline(q.INC_POS / 1000, color=INK, lw=1, ls=(0, (3, 3)))
        ax.axvspan(q.T_INC / 60, q.T_CLEAR / 60, ymin=(q.INC_POS - 30) / q.LEN, ymax=(q.INC_POS + 30) / q.LEN, color="#b8261c", lw=0)
        marks = []
        if sc.replace("+tago", "") in q.OFFICIAL:
            marks.append(((q.T_INC + q.OFFICIAL[sc.replace("+tago", "")]) / 60, "공식"))
        if rec.get("tago_at") is not None:
            marks.append((rec["tago_at"] / 60, "Tago"))
        for wt, lab in marks:
            ax.axvline(wt, color=INK, lw=1.5)
            ax.text(wt + 0.3, 0.4 + (0.8 if lab == "공식" and len(marks) > 1 else 0), f"{lab} 경고", color=INK, fontsize=10)
        ax.set_title(title, color=INK, fontsize=13, loc="left")
        ax.text(t0 + 0.5, q.LEN / 1000 - 0.45, f"추돌 위험 상충 {r['conflicts']}건 · 심각 {r['severe']}건", color=INK, fontsize=10,
                bbox=dict(facecolor=SURF, edgecolor="none", pad=3))
        ax.set_xlabel("시간(분)", color=MUTED)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(colors=MUTED)
    axes[0].set_ylabel("위치(km, 위가 하류)", color=MUTED)
    axes[0].text(t0 + 0.5, q.INC_POS / 1000 + 0.12, "사고 지점(바깥 2차로 20분 막힘)", color=INK, fontsize=9)
    cb = fig.colorbar(im, ax=axes, fraction=0.02, pad=0.01)
    cb.set_ticks([0, 30, 60, 90, 110]); cb.set_ticklabels(["110", "80", "50", "20", "0"])
    cb.set_label("평균 속도(km/h)", color=MUTED); cb.outline.set_visible(False); cb.ax.tick_params(colors=MUTED)
    fig.suptitle("경부고속도로 하행 기흥~수원신갈 · 아침 7시대 실측 교통량 6,691대/시 · 편도 4차로 · SUMO 시뮬레이션(씨앗 %d)" % seed, color=INK, fontsize=12, x=0.01, ha="left")
    fig.savefig(HERE / "spacetime.png", dpi=150, bbox_inches="tight", facecolor=SURF)
    out = {"inc": q.INC_POS, "lanes": q.LANES, "t_inc": q.T_INC, "t_clear": q.T_CLEAR, "official": q.OFFICIAL,
           "runs": [{"scenario": sc, "p": p, "title": title, "tago_at": rec.get("tago_at"), "stats": r, "frames": rec.get("frames", [])}
                    for rec, r, (sc, p, title) in zip(recs, stats, SCEN)]}
    (HERE / "frames.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("saved spacetime.png, frames.json", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
