#!/usr/bin/env python3
"""외부 링크 상태 점검 → link_status.json 생성.

왜: index.html 에는 출처·바로가기용 외부 링크가 30여 개 있고, 기관 사이트(국민연금
기금운용·청약홈·R-ONE 등)는 예고 없이 URL 구조를 바꾼다. 브라우저에서는 CORS 때문에
타 도메인 응답 상태를 신뢰성 있게 판정할 수 없으므로(no-cors 응답은 opaque) CI 에서
주기 점검해 결과 파일을 커밋하고, 사이트의 '설정 → 시스템 진단' 패널이 이를 표시한다.

분류 기준:
  ok     — 2xx/3xx
  broken — 404/410, DNS 실패 (링크 교체 필요)
  manual — 403/405/406/429/5xx/타임아웃 등 봇 차단·일시 장애 가능성 (사람이 확인)
실행: python scripts/check_links.py   (항상 exit 0 — 보고서 성격, 빌드를 깨지 않음)
"""
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

FILES = ["index.html"]
TIMEOUT = 15
UA = {"User-Agent": "Mozilla/5.0 (compatible; econ-terminal-linkcheck/1.0; "
                    "+https://0101-commits.github.io/economic-site/)"}
# 점검 제외 — 문서 링크가 아닌 리소스/API 성 URL (실패가 화면에서 즉시 드러나거나 GET / 가 무의미)
SKIP_PREFIX = (
    "https://fonts.googleapis.com",                       # 폰트 CSS — 로드 실패 시 화면에서 즉시 식별
    "https://fonts.gstatic.com",
    "https://ecom-dashboard-proxy.baldr0001.workers.dev", # Worker API — 루트 GET 404 가 정상이라 오탐 발생
)


def extract_urls():
    urls = set()
    for path in FILES:
        try:
            with open(path, encoding="utf-8") as f:
                html = f.read()
        except OSError:
            continue
        for m in re.finditer(r'href="(https?://[^"]+)"', html):
            u = m.group(1)
            if not u.startswith(SKIP_PREFIX):
                urls.add(u)
    return sorted(urls)


def probe(url):
    """HEAD 우선, HEAD 거부(403/405/501)·실패 시 GET 으로 1회 재시도."""
    t0 = time.time()
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, headers=UA, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.status, int((time.time() - t0) * 1000)
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 501):
                continue
            return e.code, int((time.time() - t0) * 1000)
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            if method == "HEAD":
                continue
            reason = getattr(e, "reason", e)
            return ("dns" if isinstance(reason, socket.gaierror) else "timeout"), int((time.time() - t0) * 1000)
        except Exception:
            return "error", int((time.time() - t0) * 1000)
    return "error", int((time.time() - t0) * 1000)


def classify(code):
    if isinstance(code, int):
        if 200 <= code < 400:
            return "ok"
        if code in (404, 410):
            return "broken"
        return "manual"              # 403/405/429/5xx — 봇 차단·일시 장애 가능
    return "broken" if code == "dns" else "manual"


def main():
    urls = extract_urls()
    results = []
    for u in urls:
        code, ms = probe(u)
        status = classify(code)
        results.append({"url": u, "code": code, "status": status, "ms": ms})
        icon = {"ok": "✅", "manual": "⚠️", "broken": "❌"}[status]
        print(f"{icon} [{code}] {u} ({ms}ms)")
        if status == "broken":
            print(f"::warning title=링크 끊김::{u} → {code}")
        time.sleep(0.5)              # 대상 서버 예의 — 연속 요청 간격
    summary = {s: sum(1 for r in results if r["status"] == s) for s in ("ok", "manual", "broken")}
    out = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "source": FILES,
        "summary": summary,
        "results": results,
    }
    with open("link_status.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n[link-check] 총 {len(results)}개 — 정상 {summary['ok']} · 수동확인 {summary['manual']} · 끊김 {summary['broken']}")
    sys.exit(0)   # 보고서 성격 — broken 이 있어도 배포를 막지 않음 (결과는 진단 패널에 표시)


if __name__ == "__main__":
    main()
