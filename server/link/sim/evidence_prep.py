"""실측 근거 자료 준비: 경부선 콘존 이정표 + 경부선 1시간 구간 속도(2022-12 ~ 2026-01)

  python -X utf8 evidence_prep.py <VDS 월별 파일 폴더(기본: ~/Downloads)>
출력:
- data/gyeongbu_conzones.json  콘존 ID → 이름, 방향(S 하행 = 부산방향, E 상행 = 서울방향), 시작·끝 이정(km, 부산 기점)
- data/gyeongbu_speed.csv.gz   날짜, 시, 콘존 ID, 평균 속도(일반 차로, 0 = 결측 제외)
이정: 위키백과 '경부고속도로' 나들목 표의 누적거리(data/gyeongbu_wiki.txt, 원문 wikitext). 콘존 이름 양 끝의 IC·JC·TG 를 표에 맞추고,
표에 없는 끝이 있는 콘존은 빼고(추정 안 함), 그 안의 사고도 분석에서 뺀다.
"""
import csv
import gzip
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
MONTHS = [f"{y}{m:02d}" for y in range(2022, 2027) for m in range(1, 13) if "202212" <= f"{y}{m:02d}" <= "202601"]


def norm(s):
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"(나들목|분기점|요금소|휴게소|IC|JC|TG|Hi|하이패스|기점|종점|\s|-)", "", s)
    return s


def wiki_km():
    t = (DATA / "gyeongbu_wiki.txt").read_text(encoding="utf-8")
    start = t.index("! 누적<br />거리")
    table = t[start:t.index("|}", start)]
    out = {}
    for row in table.split("|-")[1:]:
        names = re.findall(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", row)
        rights = re.findall(r'style="text-align: right;" \| *([\d.\-]+)', row)
        if len(rights) < 2 or rights[1] == "-":
            continue
        km = float(rights[1])
        head =row[:row.index('style="text-align: right;"')] if 'style="text-align: right;"' in row else row
        m = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", head)
        if m:
            name, full = (m.group(2) or m.group(1)), m.group(1)
        else:
            cells = [l.strip().lstrip("|!").strip() for l in head.splitlines() if l.strip().startswith("|")]
            if not cells:
                continue
            name = full = cells[0].split("|")[-1].strip()
        kind = "JC" if "분기점" in full else "TG" if "요금소" in full else "SA" if "휴게소" in full else "IC"
        out.setdefault((norm(name), kind), km)
    out.setdefault(("서울", "TG"), 402.6)   # 표에 이정 없음: OSM 요금소를 경로에 투영(신갈JC 위 7.7 km, 판교IC 로 검산 0.1 km 안)
    return out


def conzone_names(sample_csv):
    names = {}
    with gzip.open(sample_csv, "rt", encoding="cp949") as f:
        for r in csv.DictReader(f):
            if r["콘존ID"].startswith("0010CZ"):
                names[r["콘존ID"]] = r["콘존명"]
            elif names and not r["콘존ID"].startswith("0010"):
                break
    return names


def endpoint_km(label, table):
    kind = "JC" if label.endswith("JC") else "TG" if label.endswith("TG") else "IC"
    k = norm(label)
    if (k, kind) in table:
        return table[(k, kind)]
    for kk in ("IC", "JC", "TG"):
        if (k, kk) in table:
            return table[(k, kk)]
    return None


def build_zones(names, table):
    zones = {}
    for d in ("S", "E"):
        ids = sorted(z for z in names if z[6] == d)
        rows = []
        for z in ids:
            parts = names[z].split("-")
            a, b = (endpoint_km(parts[0], table), endpoint_km(parts[-1], table)) if len(parts) >= 2 else (None, None)
            rows.append([z, names[z], a, b])
        # 표에 없는 끝(하이패스 IC·신설 IC 등)이 있는 콘존은 추정하지 않고 뺀다
        for z, name, a, b in rows:
            if a is not None and b is not None and a != b:
                zones[z] = {"name": name, "dir": d, "from_km": a, "to_km": b}
    return zones


def main(src):
    src = Path(src)
    files = {m: src / f"VDS_노선별방향별일별1시간구간통행속도_1시간_1개월_{m}.zip" for m in MONTHS}
    missing = [m for m, p in files.items() if not p.exists()]
    print("없는 달:", missing)
    table = wiki_km()
    print("위키 표 지점", len(table))
    names = conzone_names(next(p for p in files.values() if p.exists()))
    zones = build_zones(names, table)
    print("콘존", len(names), "이정 붙음", len(zones))
    (DATA / "gyeongbu_conzones.json").write_text(json.dumps(zones, ensure_ascii=False, indent=1), encoding="utf-8")
    n = 0
    with gzip.open(DATA / "gyeongbu_speed.csv.gz", "wt", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(["date", "hour", "zone", "speed"])
        for m, p in files.items():
            if not p.exists():
                continue
            with gzip.open(p, "rt", encoding="cp949") as f:
                for r in csv.DictReader(f):
                    z = r["콘존ID"]
                    if z.startswith("0010CZ") and r["차로유형구분코드"] == "1":
                        v = float(r["평균속도"])
                        if v > 0:
                            w.writerow([r["집계일자"], int(r["집계시"]), z, v]); n += 1
            print(" ", m, n, flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / "Downloads"))
