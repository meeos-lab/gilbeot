"""본 실험 엔진(tago_sim) 그림: 시공간 속도도 spacetime.png + 애니메이션 데이터 page/anim.json.

  python -X utf8 viz2.py            # 대표 씨앗 = 기준선 주 지표가 본 실험 씨앗들 중 중앙값인 씨앗(결과로 고르지 않는 규칙)
  python -X utf8 viz2.py 7          # 씨앗을 직접 지정
가로 = 사고 뒤 시간(분), 세로 = 사고 지점까지 거리(km), 색 = 평균 속도(진할수록 느림). 같은 씨앗이라 차 흐름·사고가 같다.
"""
import json
import multiprocessing as mp
import pickle
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
import numpy as np  # noqa: E402

import tago_sim as S  # noqa: E402

HERE = Path(__file__).parent
# 논문 그림·본문과 같은 Noto Sans KR. 가변 글꼴은 matplotlib 에서 Thin 으로 나와 정적 Regular/Bold 를 쓴다
# (results/_work/fonts, NotoSansKR-VF.ttf 에서 fontTools instancer 로 만든 것). 없으면 맑은 고딕.
FONTS = sorted((HERE / "results" / "_work" / "fonts").glob("NotoSansKR-*.ttf"))
for f in FONTS or [Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/malgunbd.ttf")]:
    if f.exists():
        font_manager.fontManager.addfont(str(f))
plt.rcParams["font.family"] = "Noto Sans KR" if FONTS else "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
RAMP = ["#f1effe", "#d6d0fb", "#b3a8f5", "#8c7cee", "#6c5ce7", "#4b3bc4", "#2e2185"]   # 순차 한 색(논문 그림의 보라): 옅음 = 잘 흐름
CMAP = LinearSegmentedColormap.from_list("slow", RAMP)
INK, MUTED, SURF, CRASH = "#1f2430", "#3f4553", "#ffffff", "#e8607a"
SCEN = [("none", "(a) 경고 없음"), ("official", "(b) 기준선: 공식 안내 12분 59초"),
        ("official+tago12+relay", "(c) 기준선 + 길벗 12% + 연계"), ("tago100", "(d) 길벗 100%(상한)")]
BEFORE, AFTER, EVERY = 1500, 300, 2


def pick_seed():
    rows = [json.loads(x) for x in (S.RES / "main.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    base = sorted((r["fast"], r["seed"]) for r in rows if r["scheme"] == "official")
    return base[(len(base) - 1) // 2][1]


def run(args):
    c, sc = args
    return S.run_one((c, sc, False, True))


def main(seed):
    c = S.cond_for(seed)
    cache = S.RES / "_work" / f"viz2_seed{seed}.pkl"      # 그림만 다시 그릴 때 시뮬레이션을 건너뛴다
    if cache.exists():
        res = pickle.loads(cache.read_bytes())
    else:
        with mp.get_context("spawn").Pool(len(SCEN)) as pool:
            res = pool.map(run, [(c, sc) for sc, _ in SCEN])
        cache.parent.mkdir(exist_ok=True)
        cache.write_bytes(pickle.dumps(res))
    t_inc, t_clear = S.T_INC, res[0]["record"]["t_clear"]
    qmax = max(r["queue_km"] for r in res)
    ylo = max(0.0, S.INC_POS / 1000 - qmax - 1.5)
    fig, axes = plt.subplots(2, 2, figsize=(13, 10.4), sharex=True, sharey=True, facecolor=SURF)   # 2×2: 논문 한 단 폭에서도 읽히게
    axes = axes.flat
    t0, t1 = -5, (t_clear - t_inc) / 60 + 10
    for ax, r, (sc, title) in zip(axes, res, SCEN):
        nt, nx = int(r["record"]["t_clear"] // 10) + 100, int(S.LEN // 100) + 1
        g = np.full((nx, nt), np.nan)
        for ti, xi, v in r["record"]["grid"]:
            if ti < nt and xi < nx:
                g[xi, ti] = v * 3.6
        ext = [(0 - t_inc) / 60, (nt * 10 - t_inc) / 60, (0 - S.INC_POS) / 1000, (nx * 100 - S.INC_POS) / 1000]
        im = ax.imshow(110 - np.clip(g, 0, 110), origin="lower", aspect="auto", cmap=CMAP, vmin=0, vmax=110, extent=ext, interpolation="nearest")
        ax.set_xlim(t0, t1); ax.set_ylim(-(qmax + 1.5), 1.0)
        ax.set_facecolor(SURF)
        ax.axhline(0, color=INK, lw=1, ls=(0, (3, 3)))
        ax.plot([0, (t_clear - t_inc) / 60], [0, 0], color=CRASH, lw=3, solid_capstyle="butt")
        marks = []
        if r["record"]["official_at"] is not None:
            marks.append(((r["record"]["official_at"] - t_inc) / 60, "공식"))
        if r["inc_at"] is not None and sc != "none" and "tago" in sc:
            marks.append((r["inc_at"] / 60, "길벗 확정"))
        for i, (wt, lab) in enumerate(marks):
            ax.axvline(wt, color=INK, lw=1.2)
            ax.text(wt + 0.4, -(qmax + 1.5) + 0.3 + 0.9 * i, lab, color=INK, fontsize=17)
        ax.set_title(title, color=INK, fontsize=21, loc="left", fontweight="bold")
        ax.text(t0 + 0.6, 0.45, f"고속 접근 {r['fast']}건 · 정체 {r['queue_km']:.1f} km", color=INK, fontsize=17,
                bbox=dict(facecolor=SURF, edgecolor="none", pad=2))
        if sc in ("official+tago12+relay", "tago100"):
            ax.set_xlabel("사고 후 시간(분)", color=MUTED, fontsize=17)
        for s_ in ax.spines.values():
            s_.set_visible(False)
        ax.tick_params(colors=MUTED, labelsize=16)
    for k in (0, 2):
        fig.axes[k].set_ylabel("사고 지점까지 거리(km)", color=MUTED, fontsize=17)
    cb = fig.colorbar(im, ax=list(fig.axes[:4]), fraction=0.025, pad=0.015)
    cb.set_ticks([0, 30, 60, 90, 110]); cb.set_ticklabels(["110", "80", "50", "20", "0"])
    cb.set_label("평균 속도(km/h)", color=MUTED, fontsize=17); cb.outline.set_visible(False); cb.ax.tick_params(colors=MUTED, labelsize=16)
    # 씨앗 조건(교통량·차단·주시태만·준수·강우)은 그림 캡션에 쓴다 — 판 안 글씨는 A4 한 단에서 9 pt 이상
    fig.savefig(HERE / "page" / "spacetime.png", dpi=200, bbox_inches="tight", facecolor=SURF)
    out = {"seed": seed, "cond": c, "window": BEFORE + AFTER, "inc": BEFORE, "lanes": S.LANES, "every": EVERY, "blocked": c["blocked"], "runs": []}
    for r, (sc, title) in zip(res, SCEN):
        frames = []
        for t, cars in r["record"]["frames"]:
            rel = t - t_inc
            if int(round(t)) % EVERY or rel < 40:      # 예열이 짧아 첫 차가 사고 지점에 약 1분 뒤 닿는다 — 차가 닿은 뒤부터 보인다
                continue
            row = [int(rel)]
            for x, lane, v, warned, eq, truck in cars:
                row += [int(x - (S.INC_POS - BEFORE)), lane, int(round(v * 3.6)), warned + 2 * eq + 4 * truck]
            frames.append(row)
        out["runs"].append({"key": sc, "title": title, "tagoAt": r["inc_at"] if "tago" in sc else None,
                            "stats": {k: r[k] for k in ("fast", "fast1", "conflicts", "severe", "queue_km")}, "frames": frames})
    p = HERE / "page" / "anim.json"
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("seed", seed, c, [(r["scheme"], r["fast"], r["queue_km"]) for r in res], p.stat().st_size // 1024, "KB", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else pick_seed())
