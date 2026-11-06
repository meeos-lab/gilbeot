"""R7 도로 형태(3차로) 용량 기록(사전 고정 'R7', 보정은 하지 않고 재기만 한다): Krauss tau 0.5, 구경 13 km/h 그대로.

  TAGO_STEP=0.25 TAGO_TINC=900 TAGO_GAWK="1:13,2:13" TAGO_LANES=3 TAGO_DEMAND_SCALE=0.75 python -X utf8 calib_lanes.py → results/calib_lanes3.json
측정은 calib_cf.measure 와 같다(수요 9,000대/시 × 배율, 주시태만 20 %, 화물 15 %). 기본 용량(차로당)과 1·2차로 차단 때 남는 용량을 적는다.
"""
import json
import multiprocessing as mp
import os
from pathlib import Path

from calib_cf import measure

if __name__ == "__main__":
    lanes = int(os.environ.get("TAGO_LANES", "4"))
    grid = [("", 0.5, b) for b in (0, 1, 2)]
    with mp.get_context("spawn").Pool(3) as pool:
        rows = pool.map(measure, grid)
    base = rows[0]["flow"]
    out = {"lanes": lanes, "demand_scale": os.environ.get("TAGO_DEMAND_SCALE"), "rows": rows, "base_per_lane": round(base / lanes),
           "residual": {f"blocked {r['blocked']}": round(r["flow"] / base, 2) for r in rows if r["blocked"]}}
    Path(__file__).with_name("results").joinpath(f"calib_lanes{lanes}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
