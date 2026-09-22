#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discord 앱 설정 진단 — 버튼이 "응답하지 않았어요" 로 죽을 때 원인을 가른다.

증상(2026-09-22): 링크 버튼(style 5)은 멀쩡한데 custom_id 버튼(🔄 지금 시세)만
"애플리케이션이 적시에 응답하지 않았어요". 링크는 디스코드가 직접 열지만 custom_id 는
**Interactions 엔드포인트로 왕복**해야 하므로, 그 설정 하나가 틀리면 딱 이 증상이 된다.

원인 후보 둘을 가른다 — 워커 로그만으로는 '요청이 안 왔다'까지만 알 수 있고
'왜 안 왔는가'는 앱 설정을 봐야 안다.
  ① interactions_endpoint_url 이 비었거나 옛 주소  → 디스코드가 워커에 오지 않는다
  ② verify_key 가 워커의 DISCORD_PUBLIC_KEY 와 다름 → 와도 서명 검증에서 401

봇 토큰으로 GET /applications/@me 를 읽는다(읽기 전용). 토큰·키 전문은 찍지 않는다 —
공개키는 본래 공개값이지만 로그에 전문을 남길 이유가 없어 앞 12자만 비교용으로 낸다.
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
WORKER_HEALTH = "https://ecom-dashboard-proxy.e-hcg.workers.dev/discord/health"
EXPECTED = "https://ecom-dashboard-proxy.e-hcg.workers.dev/discord"


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main():
    tok = (os.environ.get("DISCORD_BOT_TOKEN") or "").strip()
    if not tok:
        print("DISCORD_BOT_TOKEN 미설정 — 진단 불가")
        return 1
    try:
        app = _get(f"{API}/applications/@me", {"Authorization": f"Bot {tok}",
                                               "User-Agent": "ecom-diag"})
    except urllib.error.HTTPError as e:
        print(f"앱 조회 실패 HTTP {e.code} — 봇 토큰이 이 앱의 것이 맞는지 확인")
        return 1

    url = app.get("interactions_endpoint_url")
    vkey = str(app.get("verify_key") or "")
    print(f"앱 이름            : {app.get('name')}")
    print(f"앱 ID              : {app.get('id')}")
    print(f"interactions URL   : {url or '(비어 있음)'}")
    print(f"verify_key(앞 12)  : {vkey[:12] or '(없음)'}")

    ok = True
    if not url:
        print("→ ① 확정: Interactions Endpoint URL 이 비어 있다. 이 설정이 없으면 "
              "custom_id 버튼·드롭다운은 영원히 '응답하지 않았어요' 가 된다.")
        ok = False
    elif url.rstrip("/") != EXPECTED:
        print(f"→ ① 확정: 엔드포인트가 다른 곳을 가리킨다. 기대값 = {EXPECTED}")
        ok = False

    # 워커가 들고 있는 공개키와 대조 — 다르면 요청이 와도 401 이다.
    try:
        h = _get(WORKER_HEALTH, {"User-Agent": "ecom-diag"})
        wk = str(h.get("publicKeyPrefix") or "")
        print(f"워커 공개키(앞 12) : {wk or '(미설정)'}")
        if not wk:
            print("→ ② 확정: 워커에 DISCORD_PUBLIC_KEY 가 없다.")
            ok = False
        elif vkey and wk != vkey[:12]:
            print("→ ② 확정: 앱의 verify_key 와 워커의 DISCORD_PUBLIC_KEY 가 다르다 "
                  "(다른 앱의 키가 들어가 있다).")
            ok = False
    except Exception as e:                                   # noqa: BLE001
        print(f"워커 health 조회 실패({type(e).__name__}) — 워커 배포 여부 확인")
        ok = False

    print("판정: " + ("설정 일치 — 다른 원인" if ok else "위 항목을 고치면 해결된다"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
