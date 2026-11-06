"""ITS(국가교통정보센터) 돌발상황 이력에서 경부선 교통사고의 차단 차로·처리 시간을 뽑는다(검증 V3 준비).

  python -X utf8 its_events.py            → data/its_gyeongbu_accidents.csv, results/its_events_summary.md
입력: data/its_event/YYYYMMDD.zip(일별, 안의 CSV 열: 돌발일시, 관리기관, 도로타입, 도로번호, 도로명, 방향, 돌발구분, 돌발상세구분, 돌발내용, X, Y, 링크아이디, 돌발종료일시).
한 사고는 여러 날 파일에 '처리중' 으로 되풀이될 수 있고, 끝나면 '돌발종료일시' 가 채워지거나 '처리완료' 로 바뀐다.
사고 키 = (돌발일시, 링크아이디). 차단 차로는 돌발내용의 괄호 "(1,2차로)" 에서 읽는다(갓길·진출로는 차로 수 0).
"""
import csv
import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "data" / "its_event"
OUT = HERE / "data" / "its_gyeongbu_accidents.csv"
SUM = HERE / "results" / "its_events_summary.md"
FMT = "%Y-%m-%d %H:%M:%S"


def lanes_from(msg):
    """'(1,2차로)추돌사고처리중' → (막힌 본선 차로 번호 목록, 갓길 여부, 진출입로 여부, 전차로 여부)"""
    m = re.search(r"\(([^)]*)\)", msg)
    if not m:
        return [], False, False, False
    inside = m.group(1)
    shoulder = "갓길" in inside
    ramp = "진출" in inside or "진입" in inside or "램프" in inside
    allb = "전차로" in inside or "전면" in inside
    nums = [int(x) for x in re.findall(r"(\d)(?=\s*(?:,|차로|~|-))", inside.replace("차로", "차로 "))] if "차로" in inside else []
    if "~" in inside or "-" in inside:   # "1~3차로"
        r = re.findall(r"(\d)\s*[~-]\s*(\d)", inside)
        for a, b in r:
            nums += list(range(int(a), int(b) + 1))
    return sorted(set(nums)), shoulder, ramp, allb


def main():
    rows = defaultdict(list)          # key → [(file_day, row)]
    files = sorted(SRC.glob("*.zip"))
    for f in files:
        try:
            z = zipfile.ZipFile(f)
        except zipfile.BadZipFile:
            continue
        for n in z.namelist():
            text = z.read(n).decode("utf-8-sig", errors="replace")
            for r in csv.DictReader(io.StringIO(text)):
                if r.get("도로명") != "경부선" or r.get("돌발구분") != "교통사고":
                    continue
                key = (r["돌발일시"], r["링크아이디"])
                rows[key].append((f.stem, r))
    out = []
    for (start, link), recs in rows.items():
        recs.sort(key=lambda x: x[0])
        last = recs[-1][1]
        ends = [x[1]["돌발종료일시"] for x in recs if x[1]["돌발종료일시"] not in ("-", "", None)]
        end = ends[-1] if ends else ""
        msgs = [x[1]["돌발내용"] for x in recs]
        done = any("완료" in m for m in msgs)
        lanes, shoulder, ramp, allb = lanes_from(last["돌발내용"])
        try:
            dur_min = round((datetime.strptime(end, FMT) - datetime.strptime(start, FMT)).total_seconds() / 60, 1) if end else ""
        except ValueError:
            dur_min = ""
        out.append({"start": start, "end": end, "dur_min": dur_min, "done_flag": int(done), "n_records": len(recs), "days_seen": ",".join(sorted({x[0] for x in recs})),
                    "direction": last["방향"], "lanes": ",".join(map(str, lanes)), "n_lanes": len(lanes), "shoulder": int(shoulder), "ramp": int(ramp), "all_lanes": int(allb),
                    "detail": last["돌발상세구분"], "message": last["돌발내용"], "x": last["X"], "y": last["Y"], "link_id": link})
    out.sort(key=lambda r: r["start"])
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()) if out else ["start"])
        w.writeheader(); w.writerows(out)
    n_end = sum(1 for r in out if r["end"]); n_lane = sum(1 for r in out if r["n_lanes"] > 0)
    both = [r for r in out if r["end"] and r["n_lanes"] > 0 and not r["ramp"]]
    durs = sorted(float(r["dur_min"]) for r in both if r["dur_min"] != "")
    med = durs[len(durs) // 2] if durs else None
    L = [f"# ITS 돌발 이력: 경부선 교통사고 ({files[0].stem}~{files[-1].stem}, 파일 {len(files)}개)", "",
         f"- 사고(돌발일시+링크 기준) {len(out)}건, 종료 시각 있음 {n_end}건, 본선 차단 차로 읽힘 {n_lane}건, 둘 다 있고 진출입로 아님 {len(both)}건",
         f"- 둘 다 있는 사고의 처리 시간 중앙값 {med}분, 차단 차로 수 분포 " + str({k: sum(1 for r in both if r['n_lanes'] == k) for k in (1, 2, 3, 4)}),
         f"- 방향 분포 " + str({d: sum(1 for r in both if r['direction'] == d) for d in sorted({r['direction'] for r in both})}), ""]
    SUM.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
