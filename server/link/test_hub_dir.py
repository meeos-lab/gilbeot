"""방향 구분(11-14): 차의 방향 = 경로 위 s 의 증감(또는 방위), 고속도로 구간의 맞은편 위험은 보기에서 빼고,
일반 도로 구간은 낮은 단계("맞은편"), 방향이 애매하면 낮은 단계("방향 불확실"). 스위치(DIR_AWARE)를 끄면 예전 그대로.
앱 허브 LinkHubDirTest 와 짝(같은 장면·같은 기대).

실행(저장소 루트 pleos-meeos 에서):  python -X utf8 server/link/test_hub_dir.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import link_server as L  # noqa: E402


def post(act, body):
    return L.handle("POST", f"/api/road/{act}", {}, body)[1]


def view(me):
    return L.handle("GET", "/api/road", {"me": me}, {})[1]


def world(me):
    return L.handle("GET", "/api/road/world", {"me": me}, {})[1]


def car(name, a, b, t0, speed=25.0):
    """차 하나: t0 에 a, t0+1 에 b 자리 — 30 m 움직여 방향이 정해진다"""
    me = post("join", {"name": name, "t": t0})["me"]
    post("state", {"me": me, "s": a, "speed": speed, "t": t0})
    post("state", {"me": me, "s": b, "speed": speed, "t": t0 + 1})
    return me


def brake(me, s, t):
    post("event", {"me": me, "type": "HARD_BRAKE", "value": "25.0->8.0", "s": s, "speed": 8.0, "t": t})


def scene(opposite):
    """내 차는 10 km 자리에서 경로 방향으로, 3 km 앞에서 두 대가 급제동 — 그 두 대의 방향만 다르다"""
    me = car("나", 9970.0, 10000.0, 100.0)
    a0, a1 = (13030.0, 13000.0) if opposite else (12970.0, 13000.0)
    x = car("X", a0, a1, 100.0)
    y = car("Y", a0 + 40, a1 + 40, 100.0)
    brake(x, 13000.0, 102.0)
    brake(y, 13040.0, 102.0)
    post("state", {"me": me, "s": 10030.0, "speed": 25.0, "t": 102.0})
    return me


def stopped(name, s, t, hdg=None):
    """한 번도 안 움직인 차(방위는 선택)"""
    c = post("join", {"name": name, "t": 100.0})["me"]
    b = {"me": c, "s": s, "speed": 0.0, "t": t}
    if hdg is not None:
        b["hdg"] = hdg
    post("state", b)
    return c


class Dir(unittest.TestCase):
    def setUp(self):
        self._saved = (L.DIR_AWARE, L.CLASSES)
        L.DIR_AWARE = True
        L.CLASSES = []                                   # 기본 경로 파일 = 전 구간 고속도로
        L.HUB.reset(False)

    def tearDown(self):
        L.DIR_AWARE, L.CLASSES = self._saved
        L.HUB.reset(False)

    def test_same_direction_hazard_ahead_is_announced_as_before(self):
        me = scene(opposite=False)
        hz = [h for h in view(me)["hazards"] if h["type"] == "HARD_BRAKE"]
        self.assertEqual(1, len(hz))
        self.assertIn("say", hz[0])                      # 같은 방향 앞 위험은 말한다
        self.assertNotIn("side", hz[0])
        self.assertEqual(1, len(world(me)["hazards"]))
        self.assertEqual(2, len(world(me)["pulses"]))

    def test_oncoming_hazard_on_motorway_is_not_shown_at_all(self):   # 하행 주행 중 상행 사고 = 경고 0
        me = scene(opposite=True)
        v = view(me)
        self.assertEqual(0, len(v["hazards"]))           # 고속도로 맞은편 위험은 보기에 없다
        self.assertTrue(v["risk"] is None or v["risk"].get("level", 0) == 0)   # 위험도 계산에도 없다
        self.assertEqual(0, len(world(me)["hazards"]))   # 지도 표지도 없다
        self.assertEqual(0, len(world(me)["pulses"]))    # 고리도 없다
        self.assertEqual(0, v["nearby"])                 # 맞은편 차는 주변 차 수에 세지 않는다

    def test_switch_off_keeps_the_old_behaviour(self):
        L.DIR_AWARE = False
        me = scene(opposite=True)
        hz = view(me)["hazards"]
        self.assertEqual(1, len(hz))
        self.assertIn("say", hz[0])                      # 스위치를 끄면 예전처럼 말한다
        self.assertNotIn("side", hz[0])
        self.assertEqual(2, view(me)["nearby"])

    def test_oncoming_hazard_on_ordinary_road_is_low_tier(self):     # 일반 도로 맞은편 = 낮은 단계
        L.CLASSES = [{"s0": 0.0, "s1": 1e9, "cls": "road"}]   # 같은 노선을 전 구간 '일반 도로'로
        me = scene(opposite=True)
        hz = view(me)["hazards"]
        self.assertEqual(1, len(hz))
        self.assertEqual("oncoming", hz[0]["side"])
        self.assertNotIn("say", hz[0])                   # 낮은 단계는 말하지 않는다
        self.assertEqual(0, hz[0]["level"])
        self.assertTrue(hz[0]["note"].startswith("맞은편 · 급제동"))
        wh = world(me)["hazards"]
        self.assertEqual(1, len(wh))
        self.assertEqual("oncoming", wh[0]["side"])
        self.assertEqual(0, len(world(me)["pulses"]))    # 낮은 단계 보고는 고리를 그리지 않는다

    def test_heading_decides_for_stopped_cars(self):
        me = car("나", 9970.0, 10000.0, 100.0)
        bearing = L.bearing_at(13000.0)
        for n, s in (("X", 13000.0), ("Y", 13040.0)):  # 방위가 맞은편(180°) → 고속도로라 안 보임
            brake(stopped(n, s, 101.0, (bearing + 180.0) % 360.0), s, 102.0)
        self.assertEqual(0, len(view(me)["hazards"]))
        for n, s in (("P", 15000.0), ("Q", 15040.0)):  # 방위가 90° 어긋난 두 대(교차로·램프): 애매 → 낮은 단계 '방향 불확실'
            brake(stopped(n, s, 101.0, (bearing + 90.0) % 360.0), s, 102.0)
        hz = view(me)["hazards"]
        self.assertEqual(1, len(hz))
        self.assertEqual("unsure", hz[0]["side"])
        self.assertNotIn("say", hz[0])
        self.assertTrue(hz[0]["note"].startswith("방향 불확실"))

    def test_unknown_direction_is_treated_as_before(self):            # 한 번도 안 움직이고 방위도 없는 차: 근거가 없으니 지금 그대로
        me = car("나", 9970.0, 10000.0, 100.0)
        for n, s in (("X", 13000.0), ("Y", 13040.0)):
            brake(stopped(n, s, 101.0), s, 102.0)
        hz = view(me)["hazards"]
        self.assertEqual(1, len(hz))
        self.assertIn("say", hz[0])
        self.assertNotIn("side", hz[0])

    def test_reports_of_different_directions_are_not_merged(self):
        me = car("나", 9970.0, 10000.0, 100.0)
        same = car("S", 12970.0, 13000.0, 100.0)
        opp = car("O", 13230.0, 13200.0, 100.0)
        brake(same, 13000.0, 102.0)
        brake(opp, 13200.0, 102.0)                       # 200 m 떨어진 두 보고(합치는 거리 1 km 안)
        wh = world(me)["hazards"]
        self.assertEqual(1, len(wh))                     # 내 방향 것만 보인다
        self.assertEqual(1, wh[0]["cars"])               # 맞은편 보고가 내 쪽 위험의 차 수에 더해지지 않는다
        wo = world(opp)["hazards"]                       # 맞은편을 달리는 차에게는 그쪽(자기 방향) 것만
        self.assertEqual(1, len(wo))
        self.assertEqual(1, wo[0]["cars"])

    def test_weather_and_turnback_stay_direction_free(self):         # 비·되돌아감은 양쪽 모두의 일 — 방향으로 거르지 않는다
        me = car("나", 9970.0, 10000.0, 100.0)
        x = car("X", 13030.0, 13000.0, 100.0)
        y = car("Y", 13070.0, 13040.0, 100.0)
        for c in (x, y):
            post("event", {"me": c, "type": "TURNBACK", "value": "u", "s": 13000.0, "speed": 3.0, "t": 102.0})
        hz = [h for h in view(me)["hazards"] if h["type"] == "BLOCKED"]
        self.assertEqual(1, len(hz))
        self.assertIsNone(hz[0].get("side"))


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=2).result
    n, bad = r.testsRun, len(r.failures) + len(r.errors)
    print(f"방향 구분 시험: {n - bad}/{n} 통과" + ("" if not bad else f", {bad}개 실패"))
    sys.exit(1 if bad else 0)
