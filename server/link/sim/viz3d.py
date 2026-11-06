"""3D 재생 데이터 page/anim3d.b64.txt + anim3d.json(page/replay3d.html 이 읽는다): v2 모형, 같은 씨앗에서 기준선·단계 권고·일률 80.

  python -X utf8 viz3d.py        # 대표 씨앗 = v2 본 실험 기준선 주 지표가 중앙값인 씨앗(결과로 고르지 않는 규칙)
  python -X utf8 viz3d.py 23     # 씨앗 직접 지정
창 = 사고 지점 상류 6.5 km ~ 하류 0.3 km, 사고 뒤 20분, 3 s 간격. 차 한 대 = uint16 네 개(차 번호, 위치 m, 속도 0.1 km/h, 비트: 차로 0-3·경고 4·장착 5·트럭 6·따름 7·권고 8-11 = 없음/50/70/80/90).
프레임 = [사고 뒤 s, 시작, 대수, Tago 가 아는 꼬리 위치 m 또는 null], 상충 = [s, 뒤차 m, 차로, 앞차 m, 속도 차 km/h, 뒤차 km/h]. gzip 뒤 base64 글(아티팩트는 바이너리 파일을 싣지 않는다), 브라우저에서 푼다. 용량이 커 git 에는 넣지 않는다.
고속 접근 상충(TTC < 1.5 s, 속도 차 ≥ 30 km/h)이 처음 성립한 때·곳을 events 로 함께 낸다(개수 = 지표 fast).
"""
import base64
import gzip
import json
import multiprocessing as mp
import os
import struct
import sys
from pathlib import Path

V2 = {"TAGO_STEP": "0.25", "TAGO_TAU": "0.5", "TAGO_TINC": "900", "TAGO_GAWK": "1:13,2:13", "TAGO_ATTN_P": "0.65",
      "TAGO_REC_WIN": "-6500,300,1200,3", "TAGO_REC_ID": "1"}
os.environ.update(V2)          # 스폰 자식도 같은 값을 물려받는다

import tago_sim as S  # noqa: E402

HERE = Path(__file__).parent
SCEN = [("official", "기준선: 공식 안내 12분 59초"), ("official+tago12+relay", "단계 권고 90·70·50"),
        ("official+tago12+relay-u80", "일률 80 권고(채택)")]


def pick_seed():
    rows = [json.loads(x) for x in (S.RES / "v2_main.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    base = sorted((r["fast"], r["seed"]) for r in rows if r["scheme"] == "official")
    return base[(len(base) - 1) // 2][1]


def run(args):
    c, sc = args
    return S.run_one((c, sc, False, True))


def main(seed):
    c = S.cond_for(seed)
    with mp.get_context("spawn").Pool(len(SCEN)) as pool:
        res = pool.map(run, [(c, sc) for sc, _ in SCEN])
    x0 = S.INC_POS - 6500
    blob, meta = bytearray(), {"seed": seed, "cond": c, "incAt": 6500, "len": 6800, "lanes": S.LANES, "blocked": c["blocked"],
                               "clear": res[0]["record"]["t_clear"] - S.T_INC, "runs": []}
    for r, (sc, title) in zip(res, SCEN):
        frames = []
        for t, cars in r["record"]["frames"]:
            off = len(blob)
            for x, lane, v, warned, eq, truck, vid, adv, comply in cars:
                code = {0: 0, 50: 1, 70: 2, 80: 3, 90: 4}.get(adv, 5)
                blob += struct.pack("<HHHH", vid, max(0, min(65535, int(round(x - x0)))), min(65535, int(round(v * 36))),
                                    lane | warned << 4 | eq << 5 | truck << 6 | comply << 7 | code << 8)
            frames.append([round(t - S.T_INC), off // 8, len(cars)])
        tails = {round(t - S.T_INC): (None if x is None else round(x - x0)) for t, x in r["record"]["tail"]}
        for f in frames:
            f.append(tails.get(f[0]))
        ev = [[round(t - S.T_INC, 1), round(x - x0), lane, round(xl - x0), dv, vf] for t, x, lane, xl, dv, vf in r["record"]["events"]]
        rr = r["record"]
        meta["runs"].append({"key": sc, "title": title, "frames": frames, "events": ev,
                             "officialAt": None if rr["official_at"] is None else rr["official_at"] - S.T_INC,
                             "relayAt": None if rr["relay_at"] is None else rr["relay_at"] - S.T_INC, "tagoAt": r["inc_at"],
                             "stats": {k: r[k] for k in ("fast", "conflicts", "severe", "queue_km")}})
        assert len(ev) == r["fast"], (sc, len(ev), r["fast"])
    (HERE / "page" / "anim3d.b64.txt").write_text(base64.b64encode(gzip.compress(bytes(blob), 9)).decode(), encoding="ascii")
    (HERE / "page" / "anim3d.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("seed", seed, [(r["scheme"], r["fast"], r["inc_at"], r["queue_km"]) for r in res], len(blob) // 1024, "KB", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else pick_seed())
