"""주차 기둥 사진 우편함(새 기능 H, 2026-11-13) — 가족 휴대폰이 올리고 Pleos 차가 한 번 가져간다. 검증·권한·한 번뿐·5분 만료."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import link_server as L  # noqa: E402


def setup():
    L.HUB.reset(False)
    car = L.handle("POST", "/api/road/join", {}, {"name": "A", "t": 100, "lang": "ko"})[1]["me"]
    g = L.handle("POST", "/api/link/group", {}, {"me": car, "t": 100, "name": "A"})[1]
    ph = L.handle("POST", "/api/link/join", {}, {"code": g["code"], "name": "폰", "kind": "web", "t": 100})[1]["me"]
    stranger = L.handle("POST", "/api/road/join", {}, {"name": "X", "t": 100})[1]["me"]
    return g["group"], car, ph, stranger


class ParkPhoto(unittest.TestCase):
    def put(self, gid, body): return L.handle("POST", f"/api/link/{gid}/parkphoto", {}, body)
    def take(self, gid, me, t=100): return L.handle("POST", f"/api/link/{gid}/parkphoto/take", {}, {"me": me, "t": t})

    def test_roundtrip_once(self):
        gid, car, ph, _ = setup()
        self.assertEqual(self.put(gid, {"me": ph, "img": "QUJD"})[0], 200)
        code, obj = self.take(gid, car)
        self.assertEqual((code, obj["photo"]), (200, {"img": "QUJD"}))
        self.assertIsNone(self.take(gid, car)[1]["photo"])            # 한 번뿐

    def test_only_cars_may_take_and_only_members(self):
        gid, car, ph, stranger = setup()
        self.put(gid, {"me": ph, "img": "QUJD"})
        self.assertEqual(self.take(gid, ph)[0], 403)                  # 휴대폰은 못 가져간다
        self.assertEqual(self.take(gid, stranger)[0], 404)            # 그룹 밖
        self.assertEqual(self.put(gid, {"me": stranger, "img": "QUJD"})[0], 404)
        self.assertEqual(self.take(gid, car)[1]["photo"], {"img": "QUJD"})   # 거부들이 사진을 지우지 않았다

    def test_validation(self):
        gid, car, ph, _ = setup()
        for body in ({"me": ph}, {"me": ph, "img": 5}, {"me": ph, "img": ""}, {"me": ph, "img": "@@@@"}, {"me": ph, "img": "A" * 60001},
                     {"me": ph, "img": "data:image/jpeg;base64,AAAA"}, {"me": ph, "img": "AAAA\n"}):
            self.assertEqual(self.put(gid, body)[0], 400, body)
        self.assertIsNone(self.take(gid, car)[1]["photo"])            # 거절된 것은 상자에 없다
        self.assertEqual(self.put(gid, {"me": ph, "img": "A" * 60000})[0], 200)   # 상한 딱 맞는 크기는 받는다

    def test_latest_wins_and_expiry(self):
        gid, car, ph, _ = setup()
        self.put(gid, {"me": ph, "img": "QUJD"}); self.put(gid, {"me": ph, "img": "REVG"})
        self.assertEqual(self.take(gid, car)[1]["photo"], {"img": "REVG"})
        self.put(gid, {"me": ph, "img": "QUJD"})
        self.assertIsNone(self.take(gid, car, t=100 + 301)[1]["photo"])   # 5분 지나면 없는 것
        self.put(gid, {"me": ph, "img": "QUJD", "t": 500})
        self.assertEqual(self.take(gid, car, t=500 + 299)[1]["photo"], {"img": "QUJD"})

    def test_view_never_carries_the_photo(self):
        gid, car, ph, _ = setup()
        self.put(gid, {"me": ph, "img": "QUJD"})
        for me in (car, ph):
            v = L.handle("GET", f"/api/link/{gid}", {"me": me}, {})[1]
            self.assertNotIn("QUJD", str(v))


class ParkText(unittest.TestCase):
    """차가 1 s 상태에 실은 주차 글이 그룹 화면(휴대폰)에 보이고, null 이면 지워진다. 좌표는 받지도 싣지도 않는다"""
    def state(self, me, body): return L.handle("POST", "/api/road/state", {}, {"me": me, "t": 101, **body})

    def member(self, gid, viewer, cid_name="A"):
        v = L.handle("GET", f"/api/link/{gid}", {"me": viewer}, {})[1]
        return next(m for m in v["group"]["members"] if m["name"] == cid_name)

    def test_shown_to_family_then_cleared(self):
        gid, car, ph, _ = setup()
        self.state(car, {"s": 1000, "park": "B2 · D-14"})
        self.assertEqual(self.member(gid, ph)["park"], "B2 · D-14")
        self.state(car, {"s": 1000, "park": None})
        self.assertIsNone(self.member(gid, ph)["park"])

    def test_sanitized_and_capped(self):
        gid, car, ph, _ = setup()
        self.state(car, {"s": 1000, "park": "  B2~B3 <b>x</b> 37.5,127.1 " + "가" * 60})
        p = self.member(gid, ph)["park"]
        self.assertLessEqual(len(p), L.PARK_TEXT_MAX)
        self.assertNotIn("<", p); self.assertNotIn(",", p)
        for bad in (5, "", "   ", {"lat": 1}):
            self.state(car, {"s": 1000, "park": bad})
            self.assertIsNone(self.member(gid, ph)["park"], bad)

    def test_absent_key_keeps_value(self):
        gid, car, ph, _ = setup()
        self.state(car, {"s": 1000, "park": "B1"})
        self.state(car, {"s": 1000})
        self.assertEqual(self.member(gid, ph)["park"], "B1")


if __name__ == "__main__":
    unittest.main()
