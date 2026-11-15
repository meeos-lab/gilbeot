"""비컨 차종(ambulance·fire·police, 2026-11-13) — 문구만 바뀌고 진로 양보 판단·우선순위는 같다. 기본·생략·모르는 값은 ambulance 이고 기존 문장 그대로다."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import link_server as L  # noqa: E402

WORD = {"ambulance": ("구급차", "Ambulance"), "fire": ("소방차", "Fire truck"), "police": ("경찰차", "Police car")}


def scenario(vtype, lang, steps=5):
    """내 차 앞쪽 1 km 에서 비컨 차가 다가오는 장면의 마지막 보기(SIREN 위험들)와 전체 보기."""
    L.HUB.reset(False)
    me = L.handle("POST", "/api/road/join", {}, {"name": "A", "t": 1, "lang": lang})[1]["me"]
    body = {"kind": "ev", "token": L.EV_TOKEN, "t": 1, "lang": lang}
    if vtype is not None:
        body["vtype"] = vtype
    code, obj = L.handle("POST", "/api/road/join", {}, body)
    assert code == 200, obj
    ev = obj["me"]
    es, ms = 19000.0, 20000.0
    for k in range(1, steps + 1):
        es += 30; ms += 20
        L.handle("POST", "/api/road/state", {}, {"me": me, "t": 1 + k, "s": ms, "speed": 20})
        L.handle("POST", "/api/road/state", {}, {"me": ev, "t": 1 + k, "s": es, "speed": 30, "on": True, "dest_s": 24000})
    view = L.handle("GET", "/api/road/", {"me": me, "t": str(1 + steps)}, {})[1]
    return [h for h in view["hazards"] if h["type"] == "SIREN"], view


def strip(view):
    """차종과 문구(label·say·vtype)를 뺀 보기 — 판단·우선순위가 같다면 차종과 무관하게 같아야 한다."""
    v = json.loads(json.dumps(view))
    v.pop("me", None)   # 차 id 는 실행마다 무작위
    for h in v["hazards"]:
        for k in ("vtype", "label", "say"):
            h.pop(k, None)
    return v


class Vtype(unittest.TestCase):
    def test_wording_per_type_and_language(self):
        for vt, (ko, en) in WORD.items():
            h = scenario(vt, "ko")[0][0]
            self.assertEqual(h["vtype"], vt); self.assertIn(ko, h["say"]); self.assertEqual(h["label"], f"{ko}(위치 신호)")
            h = scenario(vt, "en")[0][0]
            self.assertTrue(h["say"].startswith(en)); self.assertEqual(h["label"], f"{en} (position beacon)")

    def test_default_missing_and_unknown_are_ambulance_with_the_old_sentence(self):
        old = "후방 1.0km 구급차 접근 중(구급차 위치 신호). 약 2분 후 통과 예상. 진로를 양보하세요."
        for vt in (None, "ambulance", "bogus", "FIRE", ""):
            h = scenario(vt, "ko")[0][0]
            self.assertEqual((h["vtype"], h["say"]), ("ambulance", old), repr(vt))

    def test_non_string_type_is_rejected_by_schema(self):
        L.HUB.reset(False)
        for vt in (5, ["fire"], {"a": 1}, True):
            code, obj = L.handle("POST", "/api/road/join", {}, {"kind": "ev", "token": L.EV_TOKEN, "t": 1, "vtype": vt})
            self.assertEqual((code, obj.get("error"), obj.get("field")), (400, "schema", "vtype"), repr(vt))

    def test_decisions_and_priorities_do_not_depend_on_type(self):
        base = strip(scenario("ambulance", "ko")[1])
        for vt in ("fire", "police"):
            self.assertEqual(strip(scenario(vt, "ko")[1]), base, vt)
        base_en = strip(scenario("ambulance", "en")[1])
        self.assertEqual(strip(scenario("police", "en")[1]), base_en)

    def test_near_sentence_and_level(self):
        h = scenario("police", "ko", steps=5)[0][0]
        self.assertEqual(h["level"], scenario("ambulance", "ko", steps=5)[0][0]["level"])


if __name__ == "__main__":
    unittest.main()
