"""함께 가기 시연 경로: 경부고속도로 서울(양재)→천안 본선과 휴게소 (키 불필요, ODbL: © OpenStreetMap contributors).

사용: python fetch_highway_osm.py <out_raw.json>
본선(motorway, ref 1)은 방향별로 나뉜 일방 도로라 노드 연결(out body + 노드)로 받고, 하행 경로는 build_highway_route.py가 고른다.
"""
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BBOX = "36.78,127.00,37.48,127.25"   # 남,서,북,동

QUERY = f"""
[out:json][timeout:180];
(
  way["highway"="motorway"]["ref"~"(^|;)1(;|$)"]({BBOX});
  nwr["highway"~"^(services|rest_area)$"]({BBOX});
);
out body center;
>;
out skel qt;
"""


def main(out_path):
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    last = None
    for url in ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "Meeos-Tago-contest/1.0"})
            data = urllib.request.urlopen(req, timeout=240).read()
            Path(out_path).write_bytes(data)
            print(f"{url} -> {out_path} {len(data)} bytes")
            return
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"{url} 실패: {e}")
    raise SystemExit(f"수집 실패: {last}")


if __name__ == "__main__":
    main(sys.argv[1])
