"""긴급차량 예상 경로 — 넓힌 안내(새 기능 I, 2026-11-13). 응급실 나들목은 시험용 가짜 한 곳(실제 기관 아님, 이 파일 안에서만).
물결 지속 시간·이탈·응급실 없음·비컨 목적지 우선·가까운 범위 불변을 본다. 앱 허브 LinkHubFarTest 와 짝."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import link_server as L  # noqa: E402

FAKE_EXIT = [{"name": "시험IC", "nameEn": "Test IC", "s": 40000.0}]   # 시험용 가짜(실제 응급실 자료가 아니다)


class Far(unittest.TestCase):
    def setUp(self):
        self._saved = L.ER_EXITS
        L.ER_EXITS = list(FAKE_EXIT)
        L.HUB.reset(False)
        self.ids = {}
        for name, s0 in (("Y1", 30000.0), ("Y2", 30300.0), ("Y3", 30600.0), ("Y4", 30900.0), ("Y5", 31200.0), ("Y6", 31500.0),
                         ("FAR", 36000.0), ("NEAR", 32300.0), ("PAST", 40500.0)):
            me = L.handle("POST", "/api/road/join", {}, {"name": name, "t": 1000, "lang": "ko"})[1]["me"]
            L.handle("POST", "/api/road/state", {}, {"me": me, "t": 1000, "s": s0 - 20, "speed": 20})
            L.handle("POST", "/api/road/state", {}, {"me": me, "t": 1001, "s": s0, "speed": 20})
            self.ids[name] = me

    def tearDown(self):
        L.ER_EXITS = self._saved

    def yield_(self, name, t, s):
        L.handle("POST", "/api/road/event", {}, {"me": self.ids[name], "t": t, "s": s, "speed": 12, "type": "YIELD", "value": "right"})

    def siren(self, name, t):
        v = L.handle("GET", "/api/road", {"me": self.ids[name], "t": str(t)}, {})[1]
        return next((h for h in v["hazards"] if h["type"] == "SIREN"), None)

    def wave(self, upto=6):
        """3 s 마다 300 m 앞에서 비킴(물결 100 m/s, 시연 축척). 비킬 때마다 FAR 차가 보기를 받는다(방향 지속 시간은 보기에서 잰다)"""
        out = []
        for k in range(upto):
            t = 1001 + 3 * k
            self.yield_(f"Y{k + 1}", t, 30000 + 300 * k)
            out.append((t, self.siren("FAR", t)))
        return out

    def test_far_only_after_the_wave_persists(self):
        seen = self.wave(6)                                     # t 1001 ~ 1016
        self.assertTrue(all(h is None or "far" not in h for _, h in seen))   # 20 s 전에는 넓히지 않는다
        h = self.siren("FAR", 1030)                             # 물결 방향이 이어진 지 20 s 넘음(마지막 비킴 뒤 15 s 까지는 속도로 민다)
        self.assertIsNotNone(h); self.assertIn("far", h)
        self.assertEqual("er", h["far"]["kind"]); self.assertEqual("시험IC", h["far"]["exit"])
        self.assertIn("추정", h["far"]["text"]); self.assertNotIn("say", h)   # 화면에만, 말하지 않는다

    def test_near_range_is_unchanged(self):
        self.wave(6)
        h = self.siren("NEAR", 1016)
        self.assertIsNotNone(h); self.assertIn("say", h); self.assertNotIn("far", h)

    def test_car_past_the_exit_gets_nothing(self):
        self.wave(6)
        h = self.siren("PAST", 1030)
        self.assertTrue(h is None or "far" not in h)

    def test_no_er_exit_means_no_far(self):
        L.ER_EXITS = []
        self.wave(6)
        h = self.siren("FAR", 1030)
        self.assertTrue(h is None or "far" not in h)

    def test_wave_that_stops_withdraws_the_far_notice(self):
        self.wave(6)
        self.assertIn("far", self.siren("FAR", 1030))
        h = self.siren("FAR", 1100)                             # 60 s 창이 지나 물결이 사라짐 → 거둔다
        self.assertTrue(h is None or "far" not in h)

    def test_beacon_destination_wins_and_needs_no_wait(self):
        L.HUB.reset(False)
        me = L.handle("POST", "/api/road/join", {}, {"name": "A", "t": 1000, "lang": "ko"})[1]["me"]
        L.handle("POST", "/api/road/state", {}, {"me": me, "t": 1000, "s": 27000, "speed": 20})
        past = L.handle("POST", "/api/road/join", {}, {"name": "B", "t": 1000, "lang": "ko"})[1]["me"]
        L.handle("POST", "/api/road/state", {}, {"me": past, "t": 1000, "s": 31000, "speed": 20})
        ev = L.handle("POST", "/api/road/join", {}, {"kind": "ev", "token": L.EV_TOKEN, "t": 1000, "lang": "ko"})[1]["me"]
        es = 20000.0
        h = None
        for k in range(1, 7):
            es += 30
            L.handle("POST", "/api/road/state", {}, {"me": ev, "t": 1000 + k, "s": es, "speed": 30, "on": True, "dest_s": 30000})
            h = next((x for x in L.handle("GET", "/api/road", {"me": me, "t": str(1000 + k)}, {})[1]["hazards"] if x["type"] == "SIREN"), None)
        self.assertIsNotNone(h); self.assertEqual("dest", h["far"]["kind"]); self.assertNotIn("say", h)   # 뒤 7 km(> 5 km): 목적지 방향 약한 안내
        hb = next((x for x in L.handle("GET", "/api/road", {"me": past, "t": "1006"}, {})[1]["hazards"] if x["type"] == "SIREN"), None)
        self.assertTrue(hb is None or "far" not in hb)            # 목적지(30 km)를 지난 차에는 없다

    def test_beacon_without_destination_does_not_guess(self):
        L.HUB.reset(False)
        me = L.handle("POST", "/api/road/join", {}, {"name": "A", "t": 1000, "lang": "ko"})[1]["me"]
        L.handle("POST", "/api/road/state", {}, {"me": me, "t": 1000, "s": 27000, "speed": 20})
        ev = L.handle("POST", "/api/road/join", {}, {"kind": "ev", "token": L.EV_TOKEN, "t": 1000, "lang": "ko"})[1]["me"]
        es = 20000.0
        for k in range(1, 30):
            es += 30
            L.handle("POST", "/api/road/state", {}, {"me": ev, "t": 1000 + k, "s": es, "speed": 30, "on": True})
            h = next((x for x in L.handle("GET", "/api/road", {"me": me, "t": str(1000 + k)}, {})[1]["hazards"] if x["type"] == "SIREN"), None)
            self.assertTrue(h is None or "far" not in h)


if __name__ == "__main__":
    unittest.main()
