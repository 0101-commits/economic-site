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
import os
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
    "https://ecom-dashboard-proxy.e-hcg.workers.dev", # Worker API — 루트 GET 404 가 정상이라 오탐 발생
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
    # 디스코드 알림의 네이버 딥링크(notify_discord.NAVER_LINKS)도 점검 — 네이버는
    # 없는 지표를 404 대신 타 페이지로 조용히 리다이렉트하므로(소프트 200) 여기서
    # 최소한 broken/manual 전환이라도 감지한다(기획 c661d5b0 v3).
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import notify_discord
        urls.update(notify_discord.NAVER_LINKS.values())
    except Exception as e:
        print(f"[links] NAVER_LINKS 로드 실패 무시: {e}")
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


# ── 후보 링크 사전 검사(--probe) ──────────────────────────────────────────
# NAVER_LINKS 에 새 지표를 넣기 전에 '그 지표 페이지에 정말 도착하는가'를 CI 에서 잰다
# (개발 컨테이너·일부 PC 는 네이버에 닿지 않는다). 네이버 새 사이트(stock.naver.com)는
# 미제공 지표를 404 대신 루트로 튕기므로(2026-09-22 실측) 상태 코드만으로는 판정이 안 된다 —
# 리다이렉트를 한 홉씩 기록하고 **요청한 경로에 머물렀는가**를 본다. 카카오톡 인앱 브라우저는
# 모바일 UA 라 두 UA 로 각각 잰다. 실행: Actions → Link Check → Run workflow(probe 입력).
PROBE_UA = {
    "desktop": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "kakao": "Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/128.0 Mobile Safari/537.36 KAKAOTALK 10.9.0",
}
PROBE_KEYWORDS = ("국채", "10년", "금리", "달러인덱스", "달러 인덱스", "US10YT", "KR10YT",
                  "DE10YT", ".DXY", "Treasury", "밀", "옥수수", "구리")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def trace(url, ua):
    """리다이렉트를 따라가며 (코드, URL) 홉을 기록 → (홉 목록, 최종 URL, 본문 앞부분)."""
    from urllib.parse import urljoin
    opener = urllib.request.build_opener(_NoRedirect)
    hops, cur, body = [], url, b""
    for _ in range(8):
        req = urllib.request.Request(cur, headers={"User-Agent": ua,
                                                   "Accept-Language": "ko-KR,ko;q=0.9"})
        try:
            with opener.open(req, timeout=TIMEOUT) as r:
                hops.append((r.status, cur))
                body = r.read(600_000)
            break
        except urllib.error.HTTPError as e:
            hops.append((e.code, cur))
            loc = e.headers.get("Location")
            if e.code in (301, 302, 303, 307, 308) and loc:
                cur = urljoin(cur, loc)
                continue
            body = e.read(20_000)
            break
        except Exception as e:                            # noqa: BLE001
            hops.append((type(e).__name__, cur))
            break
    return hops, cur, body


def probe_report(urls):
    """후보마다: 홉 · 요청 경로 유지 여부 · <title> · 키워드 적중 · 본문의 marketindex 경로."""
    from urllib.parse import urlsplit
    for u in urls:
        for tag, ua in PROBE_UA.items():
            hops, final, body = trace(u, ua)
            text = body.decode("utf-8", "replace")
            a, b = urlsplit(u), urlsplit(final)
            stay = (a.netloc, a.path.rstrip("/"), a.query) == (b.netloc, b.path.rstrip("/"), b.query)
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
            og = re.search(r'property="og:title"\s+content="([^"]*)"', text)
            hits = {k: text.count(k) for k in PROBE_KEYWORDS if k in text}
            paths = sorted(set(re.findall(r'/marketindex/[A-Za-z]+/[A-Za-z0-9.=%_-]+(?:/[a-z]+)?',
                                          text)))[:30]
            print(f"\n=== [{tag}] {u}")
            print("  hops : " + " → ".join(f"{c} {h}" for c, h in hops))
            last = hops[-1][0] if hops else None
            ok = isinstance(last, int) and 200 <= last < 300
            print(f"  final: {final}  ok={ok}  stay={stay}  bytes={len(body)}")
            print(f"  title: {(m.group(1).strip()[:80] if m else '-')}  og: {og.group(1)[:80] if og else '-'}")
            print(f"  hits : {hits}")
            if paths:
                print(f"  paths: {paths}")
            if text.lstrip().startswith(("{", "[")):
                print(f"  json : {text.strip()[:400]}")
            time.sleep(0.5)


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe_report(sys.argv[sys.argv.index("--probe") + 1:])
        sys.exit(0)
    main()
