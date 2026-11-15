"""비컨 토큰 읽기 순서(환경변수 → ev_token.local → 무작위)와 '저장소 코드에 옛 고정값이 없다'를 고정한다(2026-11-13, docs/dev/83 S4)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ev_token  # noqa: E402

OLD = "meeos-" + "ev-demo"   # 폐기한 옛 시연 토큰(이 파일에 통으로 적지 않는다)


class EvToken(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop("TAGO_EV_TOKEN", None)
        self._file = ev_token.LOCAL_FILE
        self.tmp = Path(tempfile.mkdtemp()) / "ev_token.local"
        ev_token.LOCAL_FILE = self.tmp

    def tearDown(self):
        ev_token.LOCAL_FILE = self._file
        os.environ.pop("TAGO_EV_TOKEN", None)
        if self._env is not None:
            os.environ["TAGO_EV_TOKEN"] = self._env

    def test_env_wins(self):
        self.tmp.write_text("fromfile\n", encoding="utf-8"); os.environ["TAGO_EV_TOKEN"] = " fromenv "
        self.assertEqual(ev_token.load(), ("fromenv", "env"))

    def test_file_then_random(self):
        self.tmp.write_text("fromfile\n", encoding="utf-8")
        self.assertEqual(ev_token.load(), ("fromfile", "file"))
        self.tmp.write_text("  \n", encoding="utf-8")
        t, src = ev_token.load()
        self.assertEqual(src, "random"); self.assertGreaterEqual(len(t), 12)
        self.assertNotEqual(t, ev_token.load()[0])        # 실행마다 다르다

    def test_missing_file_is_random(self):
        self.assertEqual(ev_token.load()[1], "random")

    def test_old_fixed_token_is_gone_from_code(self):
        root = Path(__file__).resolve().parents[2]
        hits = []
        for rel in ("server/link/link_server.py", "server/link/check_link_parity.py", "app/src/main/java/ai/meeos/tago/engine/LinkHub.kt",
                    "app/src/test/java/ai/meeos/tago/engine/LinkHubTest.kt"):
            if OLD in (root / rel).read_text(encoding="utf-8"):
                hits.append(rel)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
