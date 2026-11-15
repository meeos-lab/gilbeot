"""도로 링크 허브(link_server.py)의 경계 시험 — 데이터가 오가는 자리를 이상한 값·순서·중복·동시 접속으로 두드린다(2026-11-13, docs/dev/95).

실행(저장소 루트 pleos-meeos 에서):  python -X utf8 -m unittest server.link.test_hub_boundaries -v   또는   python -X utf8 server/link/test_hub_boundaries.py
기존 대조(check_link_parity.py)는 '두 엔진이 같은 답을 내나'를 보고, 이 파일은 '이상한 입력에서도 허브가 멈추거나 다른 차의 보기를 깨지 않나'를 본다.
HTTP 시험은 임시 포트(0)에 허브를 띄워 실제 소켓으로 보낸다. 허브 전역(HUB)을 쓰므로 시험마다 reset 한다.
"""
import http.client
import json
import random
import socket
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import link_server as L  # noqa: E402


def _reject(name):
    raise ValueError(name)


def post(path, body, me=None):
    b = dict(body)
    if me is not None:
        b["me"] = me
    return L.handle("POST", path, {}, b)


def view(me):
    code, v = L.handle("GET", "/api/road/", {"me": me}, {})
    json.dumps(v, allow_nan=False)        # 허브가 JSON 규격 밖 값(NaN·Infinity)을 내보내지 않는다
    json.dumps(v, ensure_ascii=False).encode()   # 실제 서버(_send)와 같은 방식 — 짝 없는 서로게이트가 응답에 섞이면 여기서 UnicodeEncodeError
    return code, v


class HubCase(unittest.TestCase):
    def setUp(self):
        L.HUB.reset(False)                # 논리 시각을 건너뛰는 시험이라 시계 오차 가드는 끈다(check_link_parity 와 같다)
        self.ids = [L.HUB.join_road({"t": 1, "name": n})["id"] for n in "ABC"]
        for i, c in enumerate(self.ids):
            L.HUB.state({"t": 2, "me": c, "s": 1000 * (i + 1), "speed": 25})


class OddValues(HubCase):
    def test_chargerstatus_needs_list_regression(self):
        """전에는 stations 가 숫자·참거짓·객체이면 TypeError/KeyError → HTTP 500 이었다. 이제 무시(앱 LinkHub 와 같다)."""
        for bad in (1, 2.5, True, {"a": 1}, "abc", None, [1, "x", None, {"statId": 5, "chargers": "no"}], [{"statId": "s1", "chargers": [1, {"id": "1", "stat": "zz"}]}]):
            code, _ = post("/api/road/chargerstatus", {"t": 3, "stations": bad}, self.ids[0])
            self.assertEqual(code, 200, bad)
        view(self.ids[1])

    def test_schema_rejects_non_finite_and_wrong_types_without_touching_state(self):
        before = json.dumps(view(self.ids[1])[1], sort_keys=True)
        for text in ('{"t":3,"s":1e999,"speed":10}', '{"t":3,"s":"abc","speed":10}', '{"t":3,"s":100,"speed":1e308}', '{"t":3,"lat":"x","lon":1}'):
            code, _ = post("/api/road/state", json.loads(text), self.ids[0])
            self.assertEqual(code, 400, text)
        self.assertEqual(before, json.dumps(view(self.ids[1])[1], sort_keys=True))   # 거절된 요청은 다른 차의 보기를 바꾸지 않는다

    def test_unknown_or_missing_car_id_never_raises(self):
        for me in (None, "", "c000000000000", "x" * 500, 5, ["c"], {"a": 1}):
            for path in ("/api/road/state", "/api/road/event", "/api/road/respond"):
                body = {"t": 3, "s": 100, "speed": 5, "type": "HARD_BRAKE", "value": "x", "ok": True}
                if me is not None:
                    body["me"] = me
                code, _ = L.handle("POST", path, {}, body)
                self.assertIn(code, (200, 400), (path, me))
            self.assertIn(view(me if isinstance(me, str) else None)[0], (200, 400, 404))   # me 없는 GET 은 스키마가 400

    def test_unknown_event_type_and_long_text_are_harmless(self):
        for typ in ("EVIL", "", "<script>", "IMPACT" * 50, "한글", "\u0000"):
            code, _ = post("/api/road/event", {"t": 3, "type": typ, "value": "v" * 300, "s": 100}, self.ids[0])
            self.assertIn(code, (200, 400), typ)
        view(self.ids[2])

    def test_impact_with_degenerate_samples(self):
        for samples in ([], [[0, 25]], [[0, 25], [0.1, 25]], [[0, 25]] * 300, [[0, 1e999], [0.1, 0]], [[1, 25], [0, 0]]):
            code, _ = post("/api/road/event", {"t": 3, "type": "IMPACT", "value": "25->0", "s": 100, "samples": samples}, self.ids[0])
            self.assertIn(code, (200, 400), str(samples)[:40])
        view(self.ids[1])


class OrderAndDuplicates(HubCase):
    def test_old_timestamp_never_rewinds_clock(self):
        post("/api/road/state", {"t": 100, "s": 1000, "speed": 25}, self.ids[0])
        now = L.HUB.now
        post("/api/road/state", {"t": 5, "s": 1010, "speed": 25}, self.ids[1])      # 늦게 도착한 옛 보고
        self.assertEqual(L.HUB.now, now)
        view(self.ids[1])

    def test_duplicate_reports_do_not_multiply_hazards(self):
        for _ in range(5):
            post("/api/road/event", {"t": 10, "type": "HARD_BRAKE", "value": "9->1", "s": 1500, "speed": 2}, self.ids[0])
        n1 = len(L.HUB.hazards)
        for _ in range(5):
            post("/api/road/event", {"t": 10, "type": "HARD_BRAKE", "value": "9->1", "s": 1500, "speed": 2}, self.ids[0])
        self.assertEqual(n1, len(L.HUB.hazards))
        self.assertLessEqual(n1, 1)

    def test_out_of_order_state_and_event_for_same_car(self):
        post("/api/road/event", {"t": 20, "type": "HARD_BRAKE", "value": "x", "s": 2000, "speed": 3}, self.ids[0])
        post("/api/road/state", {"t": 19, "s": 1990, "speed": 3}, self.ids[0])       # 이벤트보다 앞선 시각의 상태가 뒤늦게 도착
        view(self.ids[0]); view(self.ids[2])

    def test_rejoin_gives_new_car_and_old_one_expires(self):
        again = L.HUB.join_road({"t": 3, "name": "A"})["id"]
        self.assertNotEqual(again, self.ids[0])
        post("/api/road/state", {"t": 3 + L.GONE_SEC + 5, "s": 3000, "speed": 25}, again)
        old = L.HUB.car(self.ids[0])
        self.assertIsNotNone(old)                           # 꽉 차기 전에는 지우지 않는다(_purge 는 MAX_CARS 때만)
        self.assertFalse(L.HUB._alive(self.ids[0], old["t"]))   # 그러나 '아직 도로에 있다'로 세지 않는다

    def test_road_fills_up_then_refuses_new_car(self):
        L.HUB.reset(False)
        last = None
        for i in range(L.MAX_CARS + 3):
            last = L.HUB.join_road({"t": 1, "name": f"c{i}"})
        self.assertIsNone(last)                             # 200대가 모두 살아 있으면 새 차를 받지 않는다(503 full)
        code, obj = post("/api/road/join", {"t": 1, "name": "z"})
        self.assertEqual(code, 503); self.assertEqual(obj.get("error"), "full")


class Groups(HubCase):
    def _group(self):
        g = L.HUB.create_group({"t": 3, "me": self.ids[0], "name": "A"})
        self.assertIsNotNone(g)
        return g

    def test_wrong_code_five_times_locks_then_retry_after(self):
        self._group()
        codes = []
        for _ in range(L.JOIN_TRIES):
            codes.append(post("/api/link/join", {"t": 4, "code": "xxxx", "name": "H"}, self.ids[1])[0])
        self.assertEqual(codes, [404] * L.JOIN_TRIES)
        code, obj = post("/api/link/join", {"t": 4, "code": "xxxx", "name": "H"}, self.ids[1])
        self.assertEqual(code, 429); self.assertIn("retryAfter", obj)

    def test_correct_code_is_refused_while_locked(self):
        g = self._group()
        for _ in range(L.JOIN_TRIES):
            post("/api/link/join", {"t": 4, "code": "xxxx"}, self.ids[1])
        self.assertEqual(post("/api/link/join", {"t": 5, "code": g["code"]}, self.ids[1])[0], 429)   # 잠긴 동안은 맞는 코드도 받지 않는다
        self.assertEqual(post("/api/link/join", {"t": 5 + L.JOIN_LOCK + 1, "code": g["code"]}, self.ids[1])[0], 200)

    def test_group_code_closes_after_many_wrong_tries_across_cars(self):
        g = self._group()
        # 한 차는 5번 틀리면 60초 잠기므로(JOIN_TRIES) 코드 하나를 닫으려면 여러 차가 틀려야 한다 — 차 6대 × 5번 = 30 > CODE_WRONG_MAX
        others = [L.HUB.join_road({"t": 3, "name": f"o{i}"})["id"] for i in range(6)]
        for me in others:
            for _ in range(L.JOIN_TRIES):
                L.HUB.join_group({"t": 4, "me": me, "code": "xxxx"})
        self.assertNotIn(g["code"], L.HUB.codes)

    def test_phone_without_car_id_shares_one_lock_slot(self):
        g = self._group()
        for i in range(L.CODE_WRONG_MAX + 2):
            L.HUB.join_group({"t": 4, "code": f"{i:04d}x"})             # 차 id 없는 참가(휴대폰)는 한 칸을 같이 쓴다 → 5번 뒤 잠겨 더 못 센다
        self.assertIn(g["code"], L.HUB.codes)                           # (설계대로) 한 휴대폰 칸만으로는 코드를 닫지 못한다
        self.assertLessEqual(L.HUB.groups[g["id"]]["wrong"], L.JOIN_TRIES)

    def test_lone_surrogate_in_text_fields_never_reaches_responses(self):
        """json 은 짝 없는 서로게이트(\\ud800)를 받아 주지만, 그것이 이름·값으로 허브에 남으면 다른 차의 응답(UTF-8 인코딩)이 모두 깨진다."""
        me = self.ids[0]
        for body in ({"name": "\ud800x"}, {"car": "a\udfffb"}, {"kind": "\ud800"}):
            L.HUB.join_road(dict(body, t=3))
        post("/api/road/state", {"t": 4, "s": 1100, "speed": 20, "wiper": "\ud800"}, me)
        post("/api/road/event", {"t": 4, "type": "HARD_BRAKE", "value": "\ud800", "s": 1100, "speed": 2}, me)
        L.HUB.create_group({"t": 5, "me": me, "name": "\ud800", "car": "\udc00"})
        for c in self.ids:
            view(c)

    def test_join_with_odd_code_types(self):
        self._group()
        for code in (None, 1234, True, [], {}, "", " ", "\u0000", "0" * 5000):
            c, _ = post("/api/link/join", {"t": 4, "code": code}, self.ids[1])
            self.assertIn(c, (404, 429), repr(code)[:20])

    def test_double_join_does_not_duplicate_member(self):
        g = self._group()
        for _ in range(3):
            self.assertEqual(post("/api/link/join", {"t": 4, "code": g["code"], "name": "B"}, self.ids[1])[0], 200)
        self.assertEqual(L.HUB.groups[g["id"]]["members"].count(self.ids[1]), 1)

    def test_group_actions_with_foreign_group_id(self):
        code, _ = L.handle("POST", "/api/link/zzzzzz/rest", {}, {"t": 5, "me": self.ids[0]})
        self.assertEqual(code, 404)
        code, _ = L.handle("GET", "/api/link/zzzzzz", {"me": self.ids[0]}, {})
        self.assertEqual(code, 404)


class Concurrency(HubCase):
    def test_many_cars_reporting_at_once(self):
        """handle 은 허브 전역 LOCK 안에서 돈다 — 스레드 40개가 동시에 위치·이벤트를 올려도 예외 없이 끝나고 차 수가 그대로여야 한다."""
        cars = [L.HUB.join_road({"t": 1, "name": f"x{i}"})["id"] for i in range(40)]
        errors = []

        def work(k, me):
            try:
                for j in range(60):
                    post("/api/road/state", {"t": 5 + j, "s": 1000 + k * 30 + j, "speed": 20 + (j % 7)}, me)
                    if j % 10 == 0:
                        post("/api/road/event", {"t": 5 + j, "type": "HARD_BRAKE", "value": "x", "s": 1000 + k * 30, "speed": 2}, me)
                    view(me)
            except Exception as e:   # noqa: BLE001
                errors.append(repr(e))

        ts = [threading.Thread(target=work, args=(k, me)) for k, me in enumerate(cars)]
        [t.start() for t in ts]; [t.join(60) for t in ts]
        self.assertEqual(errors, [])
        self.assertEqual(len(L.HUB.cars), 3 + 40)


class MutationFuzz(HubCase):
    """올바른 본문에서 한 칸을 이상 값으로 바꾼 요청 6000개(고정 시드): 예외 없음, 매 요청 뒤 모든 차의 보기가 JSON 으로 나간다."""
    BASE = {"/api/road/state": {"t": 0, "s": 1500, "speed": 22.0, "wiper": "OFF", "soc": 50, "temp": 20, "limit": 100, "offRoute": False},
            "/api/road/event": {"t": 0, "type": "HARD_BRAKE", "value": "9.0->2.0", "s": 1500, "speed": 5.0},
            "/api/road/respond": {"t": 0, "ok": True, "timeout": False},
            "/api/road/official": {"t": 0, "items": [{"type": "ACCIDENT", "s": 2000, "end": None, "desc": "x"}]},
            "/api/road/chargerstatus": {"t": 0, "stations": [{"statId": "a", "chargers": [{"id": "1", "stat": "2"}]}]},
            "/api/link/group": {"t": 0, "name": "G"}, "/api/link/join": {"t": 0, "code": "0000", "name": "H"}}

    @staticmethod
    def val(r, depth=0):
        k = r.random()
        if k < .2: return r.choice([0, 1, -1, 10 ** 30, -10 ** 30, 2 ** 63])
        if k < .4: return r.choice([0.0, -0.5, 1e-9, 1e300, 37.5, 1e999, -1e999])
        if k < .55: return r.choice(["", "a", "NaN", "null", "x" * 500, "\u0000", "한글", "🚗", "\ud800", "a\udfffb"])
        if k < .62: return None
        if k < .68: return r.choice([True, False])
        if k < .82 and depth < 2: return [MutationFuzz.val(r, depth + 1) for _ in range(r.randint(0, 3))]
        if depth < 2: return {r.choice(["a", "t", "s", "ok"]): MutationFuzz.val(r, depth + 1) for _ in range(r.randint(0, 2))}
        return 0

    def test_mutated_requests(self):
        r = random.Random(20261113)
        paths = list(self.BASE)
        for i in range(6000):
            path = r.choice(paths)
            b = dict(self.BASE[path]); b["me"] = r.choice(self.ids); b["t"] = L.HUB.now + r.choice([0, 1, 5])
            b[r.choice(list(b) + ["extra"])] = self.val(r)
            try:
                L.handle("POST", path, {}, b)
            except Exception as e:   # noqa: BLE001
                self.fail(f"#{i} {path} {b!r} → {e!r}")
            for me in self.ids:
                try:
                    view(me)
                except Exception as e:   # noqa: BLE001
                    self.fail(f"#{i} 뒤에 {me} 의 보기가 깨짐: {path} {b!r} → {e!r}")


class HttpBoundary(unittest.TestCase):
    """실제 소켓: 파싱 단계(NaN 글자·길이·인코딩·Origin)에서 거절하고 서버는 계속 산다."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), L.Handler)
        cls.port = cls.srv.server_address[1]
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        L.HUB.reset(False)

    def raw(self, data: bytes, wait=1.5) -> bytes:
        s = socket.create_connection(("127.0.0.1", self.port), timeout=4)
        s.sendall(data); s.settimeout(wait)
        out = b""
        try:
            while True:
                c = s.recv(4096)
                if not c:
                    break
                out += c
        except socket.timeout:
            pass
        s.close()
        return out

    def status(self, data: bytes) -> int:
        out = self.raw(data)
        return int(out.split(b" ", 2)[1]) if out.startswith(b"HTTP/") else 0

    def post(self, path, body: bytes, extra=b""):
        return self.status(b"POST " + path.encode() + b" HTTP/1.1\r\nHost: x\r\nContent-Length: " + str(len(body)).encode() + b"\r\n" + extra + b"\r\n" + body)

    def test_json_literals_and_encoding(self):
        self.assertEqual(self.post("/api/road/join", b'{"t": NaN}'), 400)
        self.assertEqual(self.post("/api/road/join", b'{"t": Infinity}'), 400)
        self.assertEqual(self.post("/api/road/join", b'{"t": -Infinity}'), 400)
        self.assertEqual(self.post("/api/road/join", b"\xff\xfe\x00{"), 400)               # 잘못된 UTF-8
        self.assertEqual(self.post("/api/road/join", b"[]"), 400)
        self.assertEqual(self.post("/api/road/join", b"null"), 400)
        self.assertEqual(self.post("/api/road/join", b'{"t":1,"name":"\xed\xa0\x80"}'), 200)  # 짝 없는 서로게이트: json 이 받아 주지만 clean() 이 이름에서 뺀다(아래 서로게이트 시험)

    def test_lengths_and_transfer_encoding(self):
        self.assertEqual(self.status(b"POST /api/road/join HTTP/1.1\r\nContent-Length: -1\r\n\r\n"), 400)
        self.assertEqual(self.status(b"POST /api/road/join HTTP/1.1\r\nContent-Length: abc\r\n\r\n"), 400)
        self.assertEqual(self.status(b"POST /api/road/join HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n"), 400)
        self.assertEqual(self.status(b"POST /api/road/join HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n"), 400)

    def test_origin_and_methods(self):
        self.assertEqual(self.post("/api/road/join", b"{}", b"Origin: http://evil.example\r\n"), 403)
        self.assertEqual(self.post("/api/road/join", b'{"t":1}', b"Origin: http://127.0.0.1:8791\r\n"), 200)
        self.assertIn(self.status(b"PUT /api/road/join HTTP/1.1\r\nContent-Length: 0\r\n\r\n"), (501, 405))
        self.assertEqual(self.status(b"GET /api/road/nope HTTP/1.1\r\n\r\n"), 404)

    def test_short_body_does_not_hang_server(self):
        """본문이 약속한 길이보다 짧게 끊겨도(연결 끊김) 다음 요청을 받는다."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=4)
        s.sendall(b"POST /api/road/join HTTP/1.1\r\nContent-Length: 100\r\n\r\n{\"t\":1"); s.close()
        self.assertEqual(self.post("/api/road/join", b'{"t":1}'), 200)

    def test_many_sequential_connections(self):
        for _ in range(150):
            self.assertEqual(self.status(b"GET /api/road/route HTTP/1.1\r\n\r\n"), 200)

    def test_http_client_roundtrip_state_view(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        c.request("POST", "/api/road/join", json.dumps({"t": 1, "name": "A"}), {"Content-Type": "application/json"})
        me = json.loads(c.getresponse().read())["me"]
        c.request("POST", "/api/road/state", json.dumps({"t": 2, "me": me, "s": 1000, "speed": 22}))
        r = c.getresponse(); body = json.loads(r.read())
        self.assertEqual(r.status, 200); self.assertIn("api", body)
        c.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
