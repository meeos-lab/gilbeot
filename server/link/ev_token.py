"""긴급차량(구급차) 비컨 토큰 — 저장소 코드에 값을 두지 않는다(2026-11-13, docs/dev/83 5절 S4).

읽는 순서: ① 환경변수 TAGO_EV_TOKEN ② 저장소 루트(pleos-meeos)의 `ev_token.local`(git 제외 파일, 한 줄) ③ 둘 다 없으면 이 실행에서만 쓰는 무작위 값.
앱(APK)은 같은 값을 빌드 때 넣는다(`app/build.gradle.kts` 가 -Pmeeos.evToken → 환경변수 → `ev_token.local` 순으로 읽는다). 값이 다르면 비컨 참가는 403.
옛 고정값은 시연 전용이었고 폐기했다(이력에 남아 있어도 더는 쓰이지 않는다).
"""
import os
import secrets
from pathlib import Path

LOCAL_FILE = Path(__file__).resolve().parents[2] / "ev_token.local"


def load():
    """(토큰, 출처) — 출처는 'env'·'file'·'random'"""
    t = os.environ.get("TAGO_EV_TOKEN", "").strip()
    if t:
        return t, "env"
    try:
        t = LOCAL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        t = ""
    if t:
        return t, "file"
    return secrets.token_urlsafe(12), "random"
