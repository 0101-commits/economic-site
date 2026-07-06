# 메르 블로그(ranto28) 키워드 검색 → 원문 JSON 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** economic-site 대시보드에서 경제 블로거 "메르"(네이버 `ranto28`)의 글을 키워드로 검색하고, 관련 포스팅의 원문을 JSON으로 뽑을 수 있게 한다.

**Architecture:** 하이브리드. (1) GitHub Actions가 `scripts/fetch_merblog.py`로 최근 글 스냅샷을 `merblog.json`에 주기 수집(원문 상위 20개 포함) → 브라우저 클라이언트 필터로 즉시 검색. (2) 임의 키워드 전체기간/원문은 Cloudflare Worker `/merblog` 라우트가 네이버 모바일 API를 프록시(CORS 우회)해 라이브 반환. (3) `index.html`에 「메르 블로그 검색」 페이지(검색창·결과·원문보기·JSON 다운로드) 추가.

**Tech Stack:** Python 3.11(requests) · Cloudflare Worker(JS, fetch) · 순수 인라인 JS/CSS(index.html, 빌드 없음).

## Global Constraints

- **빌드 없음** — `index.html` 단일 파일, 인라인 CSS/JS 직접 편집. Tailwind CDN 재추가 금지(CSP `eval` 위반).
- **`data.json` 건드리지 않음** — 봇 전용 + `validate_data.py` 하드게이트. 신규 데이터는 별도 `merblog.json`.
- **API 키 하드코딩 금지** — 공개 repo. 단 네이버 모바일 블로그 API/RSS/PostView는 **키 불필요**(공개 엔드포인트)이므로 이 기능엔 시크릿 없음.
- **날조 금지** — 네트워크 실패 시 기존 `merblog.json` 보존, 빈/에러는 명시(기존 repo 관행).
- **라이브 사이트 origin** = `https://0101-commits.github.io`. Worker 배포 = `cd cloudflare-worker && npx wrangler deploy`(git push로 배포 안 됨).
- **검증된 엔드포인트(2026-07-06 실측)**:
  - 검색: `https://m.blog.naver.com/api/blogs/ranto28/search/post?query=<kw>&page=<n>&size=<n>&sortType=<sim|date>` → `result.totalCount`, `result.list[]`(필드: `logNo,title,categoryName,addDate(ms),contents,thumbnailUrl`).
  - 최근목록: `https://m.blog.naver.com/api/blogs/ranto28/post-list?categoryNo=0&itemCount=<n>&page=<n>` → `result.items[]`(필드: `logNo,titleWithInspectMessage,categoryName,addDate(ms),briefContents,readCount,thumbnailUrl`).
  - 원문: `https://blog.naver.com/PostView.naver?blogId=ranto28&logNo=<logNo>` → 본문 `<div class="se-main-container">` 내부.
  - 요청 헤더: `User-Agent: Mozilla/5.0`(원문) / `Mozilla/5.0 (iPhone)`(API), API엔 `Referer: https://m.blog.naver.com/ranto28`.
  - `addDate` epoch ms는 KST 기준(예 `1783303800000` = 2026-07-06 11:10 KST).

## File Structure

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `scripts/merblog_lib.py` | 네이버 호출·정규화·원문 파싱 순수 함수(테스트 대상) | 신규 |
| `scripts/fetch_merblog.py` | 스냅샷 생성 진입점 → `merblog.json` 기록 | 신규 |
| `scripts/test_merblog.py` | `merblog_lib` 단위 테스트(python 직접 실행, pytest 아님 — repo 관행) | 신규 |
| `merblog.json` | 스냅샷 산출물(봇 커밋) | 신규(런타임) |
| `.github/workflows/fetch-data.yml` | 스냅샷 수집 스텝 + 커밋에 `merblog.json` 포함 | 수정 |
| `cloudflare-worker/worker.js` | `GET /merblog` 라우트(검색 프록시 + 원문) | 수정 |
| `index.html` | 「메르 블로그 검색」 페이지 UI + 로직 | 수정 |

---

## Task 1: 네이버 파싱 라이브러리 (`merblog_lib.py`)

원문 추출·필드 정규화는 스냅샷과 (참고용) 테스트가 공유하는 순수 로직. 네트워크와 분리해 테스트 가능하게 한다.

**Files:**
- Create: `scripts/merblog_lib.py`
- Test: `scripts/test_merblog.py`

**Interfaces:**
- Produces:
  - `strip_html(s: str) -> str` — 태그 제거 + 엔티티 언이스케이프 + 제로폭문자 제거 + 공백정규화
  - `extract_fulltext(html_str: str) -> str` — PostView HTML에서 본문 평문 추출(최대 20000자)
  - `norm_post(raw: dict, source: str) -> dict` — search/post-list 원소를 공통 스키마로 정규화. 반환 키: `logNo(str), title, date(ISO KST), category, excerpt, url, readCount(int|None)`
  - `POST_URL(log_no) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`scripts/test_merblog.py`:
```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import merblog_lib as M

def test_strip_html():
    got = M.strip_html('8월 <em class="highlight">물가</em>지수&nbsp;발표')
    assert got == '8월 물가지수 발표', repr(got)

def test_strip_html_zerowidth():
    assert M.strip_html('가​나  다') == '가나 다'

def test_extract_fulltext():
    html = ('<html><body><div class="se-main-container">'
            '<p>첫 문단.</p><p>둘째 <b>문단</b>.</p></div>'
            '<div class="wrap_postcomment">댓글영역</div></body></html>')
    got = M.extract_fulltext(html)
    assert '첫 문단.' in got and '둘째 문단.' in got, repr(got)
    assert '댓글영역' not in got, '본문 뒤 위젯은 잘라야 함'

def test_extract_fulltext_none():
    assert M.extract_fulltext('<html><body>no container</body></html>') == ''

def test_norm_post_search():
    raw = {'logNo': 223967469436, 'title': '<em class="highlight">물가</em> 발표',
           'categoryName': '경제', 'addDate': 1783303800000,
           'contents': '발췌 <em>물가</em> 내용'}
    p = M.norm_post(raw, 'search')
    assert p['logNo'] == '223967469436'
    assert p['title'] == '물가 발표'
    assert p['excerpt'] == '발췌 물가 내용'
    assert p['category'] == '경제'
    assert p['url'] == 'https://blog.naver.com/ranto28/223967469436'
    assert p['date'].startswith('2026-07-06T11:10')  # KST

def test_norm_post_postlist():
    raw = {'logNo': 224337546731, 'titleWithInspectMessage': '청년미래적금',
           'categoryName': '경제', 'addDate': 1783303800000,
           'briefContents': '요약문', 'readCount': 12345}
    p = M.norm_post(raw, 'postlist')
    assert p['title'] == '청년미래적금'
    assert p['excerpt'] == '요약문'
    assert p['readCount'] == 12345

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn(); print('ok', name)
    print('ALL PASS')
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /c/Users/cgpar/economic-site && python scripts/test_merblog.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'merblog_lib'`

- [ ] **Step 3: 최소 구현**

`scripts/merblog_lib.py`:
```python
"""메르 블로그(ranto28) 파싱·정규화 순수 함수. 네트워크 없음(테스트 가능)."""
import re, html
from datetime import datetime, timezone, timedelta

BLOG_ID = 'ranto28'
KST = timezone(timedelta(hours=9))

def POST_URL(log_no):
    return f'https://blog.naver.com/{BLOG_ID}/{log_no}'

def strip_html(s):
    if not s:
        return ''
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = s.replace('​', '')                 # 제로폭공백(네이버 본문 다수)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def extract_fulltext(html_str):
    if not html_str:
        return ''
    # script/style 제거
    html_str = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html_str, flags=re.S | re.I)
    m = re.search(r'se-main-container', html_str)
    if not m:
        return ''
    body = html_str[m.end():]
    # 본문 뒤 페이지 위젯 절단(댓글·공감·추천·푸터)
    body = re.split(r'wrap_postcomment|area_sympathy|post_footer|revenue_share|floating_menu', body)[0]
    return strip_html(body)[:20000]

def _kst_iso(add_ms):
    if not add_ms:
        return None
    dt = datetime.fromtimestamp(int(add_ms) / 1000, tz=KST)
    return dt.strftime('%Y-%m-%dT%H:%M:%S+09:00')

def norm_post(raw, source):
    log_no = str(raw.get('logNo'))
    if source == 'postlist':
        title = strip_html(raw.get('titleWithInspectMessage') or raw.get('title'))
        excerpt = strip_html(raw.get('briefContents') or raw.get('contents'))
    else:  # search
        title = strip_html(raw.get('title'))
        excerpt = strip_html(raw.get('contents') or raw.get('briefContents'))
    rc = raw.get('readCount')
    return {
        'logNo': log_no,
        'title': title,
        'date': _kst_iso(raw.get('addDate')),
        'category': raw.get('categoryName') or '',
        'excerpt': excerpt,
        'url': POST_URL(log_no),
        'readCount': int(rc) if isinstance(rc, (int, float)) or (isinstance(rc, str) and rc.isdigit()) else None,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /c/Users/cgpar/economic-site && python scripts/test_merblog.py`
Expected: `ok test_...` 6줄 + `ALL PASS`

- [ ] **Step 5: 커밋**

```bash
cd /c/Users/cgpar/economic-site
git add scripts/merblog_lib.py scripts/test_merblog.py
git commit -m "feat(merblog): 네이버 블로그 파싱·정규화 라이브러리 + 테스트"
```

---

## Task 2: 스냅샷 생성기 (`fetch_merblog.py`)

`post-list` API를 페이징해 최근 글 ~150개 메타를 모으고, 최신 20개는 PostView에서 원문을 채워 `merblog.json` 기록.

**Files:**
- Create: `scripts/fetch_merblog.py`
- Modify(런타임 산출): `merblog.json`

**Interfaces:**
- Consumes: `merblog_lib.norm_post`, `extract_fulltext`, `POST_URL`
- Produces: `merblog.json` — `{asOf, blogId, blogName, count, fullCount, posts:[{...norm_post + fullText?}]}`

- [ ] **Step 1: 구현**

`scripts/fetch_merblog.py`:
```python
"""메르 블로그(ranto28) 최근글 스냅샷 → merblog.json.
   네트워크 실패 시 기존 파일 보존(날조 금지)."""
import os, sys, json, time
import requests
sys.path.insert(0, os.path.dirname(__file__))
import merblog_lib as M

OUT = os.path.join(os.path.dirname(__file__), '..', 'merblog.json')
BLOG_ID = M.BLOG_ID
RECENT_TARGET = 150     # 메타 수집 목표
FULLTEXT_TOP = 20       # 원문 채울 최신 개수
PAGE_SIZE = 30
API_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'
POST_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

def _get(url, ua, referer=None, timeout=15):
    h = {'User-Agent': ua}
    if referer:
        h['Referer'] = referer
    r = requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()
    return r

def fetch_recent(target):
    """post-list 페이징으로 최근글 메타 target개."""
    posts, page = [], 1
    ref = f'https://m.blog.naver.com/{BLOG_ID}'
    while len(posts) < target and page <= 20:
        url = (f'https://m.blog.naver.com/api/blogs/{BLOG_ID}/post-list'
               f'?categoryNo=0&itemCount={PAGE_SIZE}&page={page}')
        data = _get(url, API_UA, ref).json()
        items = (data.get('result') or {}).get('items') or []
        if not items:
            break
        for it in items:
            posts.append(M.norm_post(it, 'postlist'))
        page += 1
        time.sleep(0.3)
    return posts[:target]

def fill_fulltext(posts, top):
    for p in posts[:top]:
        try:
            url = f'https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={p["logNo"]}'
            html_str = _get(url, POST_UA).text
            p['fullText'] = M.extract_fulltext(html_str)
        except Exception as e:
            print(f'  fulltext 실패 logNo={p["logNo"]}: {e}', file=sys.stderr)
        time.sleep(0.4)
    return posts

def main():
    try:
        posts = fetch_recent(RECENT_TARGET)
        if not posts:
            raise RuntimeError('수집 0건 — 기존 파일 보존')
        posts = fill_fulltext(posts, FULLTEXT_TOP)
    except Exception as e:
        print(f'[fetch_merblog] 실패: {e} — merblog.json 보존', file=sys.stderr)
        return 0  # 커밋 스텝이 기존 파일 유지
    out = {
        'asOf': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime()),
        'blogId': BLOG_ID,
        'blogName': '메르의 블로그',
        'count': len(posts),
        'fullCount': sum(1 for p in posts if p.get('fullText')),
        'posts': posts,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'[fetch_merblog] {out["count"]}개(원문 {out["fullCount"]}) → merblog.json')
    return 0

if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 로컬 실행(실네트워크 스모크 테스트)**

Run: `cd /c/Users/cgpar/economic-site && python scripts/fetch_merblog.py`
Expected: `[fetch_merblog] 150개(원문 20) → merblog.json` (건수는 근사)

- [ ] **Step 3: 산출물 검증**

Run:
```bash
cd /c/Users/cgpar/economic-site && python -c "import json;d=json.load(open('merblog.json',encoding='utf-8'));p=d['posts'][0];print('count',d['count'],'full',d['fullCount']);print('키',sorted(p));print('title',p['title'][:40]);print('date',p['date']);assert d['count']>50;assert d['fullCount']>=1;assert len(d['posts'][0].get('fullText',''))>200;print('OK')"
```
Expected: `count`>50, 첫 글 `fullText` 200자+, `OK`. 실패 시 `extract_fulltext` 절단 마커 조정.

- [ ] **Step 4: 커밋**

```bash
cd /c/Users/cgpar/economic-site
git add scripts/fetch_merblog.py merblog.json
git commit -m "feat(merblog): 최근글 스냅샷 생성기 + 초기 merblog.json"
```

---

## Task 3: Actions 파이프라인 연결 (`fetch-data.yml`)

스냅샷을 기존 데이터 워크플로에 얹어 주기 수집·커밋. `merblog.json`은 별도 파일이라 `validate_data.py`와 무관.

**Files:**
- Modify: `.github/workflows/fetch-data.yml`

**Interfaces:**
- Consumes: `scripts/fetch_merblog.py`

- [ ] **Step 1: 수집 스텝 추가**

`.github/workflows/fetch-data.yml`에서 `- name: Generate AI macro briefing` 스텝 **직전**에 추가(들여쓰기 = 기존 스텝과 동일 6칸):
```yaml
      - name: Fetch 메르 블로그 스냅샷
        continue-on-error: true
        run: python scripts/fetch_merblog.py
```
(`requests`는 기존 `pip install` 스텝에 이미 포함됨 — 추가 의존성 없음.)

- [ ] **Step 2: 커밋 스텝에 merblog.json 포함**

같은 파일에서 `git add data.json data_meta.json`이 나오는 **두 곳 모두**(정상 경로 + 재시도 루프, 계획 스펙 기준 line ~184, ~197) 뒤에 다음 줄을 각각 추가:
```yaml
          [ -f merblog.json ] && git add merblog.json || true
```
(기존 `[ -f halts_state.json ] && git add halts_state.json || true` 줄 바로 아래에 같은 형식으로.)

- [ ] **Step 3: YAML 문법 검증**

Run: `cd /c/Users/cgpar/economic-site && python -c "import yaml;yaml.safe_load(open('.github/workflows/fetch-data.yml',encoding='utf-8'));print('YAML OK')"`
Expected: `YAML OK` (yaml 없으면 `pip install pyyaml`)

- [ ] **Step 4: 커밋 & 푸시(파이프라인 실행 트리거)**

```bash
cd /c/Users/cgpar/economic-site
git add .github/workflows/fetch-data.yml
git commit -m "ci(merblog): fetch-data 워크플로에 메르 블로그 스냅샷 수집·커밋 추가"
```
(푸시는 Task 6 통합 검증 후 일괄. 단독 푸시 원하면 여기서 `git push` 가능.)

---

## Task 4: Worker 라이브 검색 라우트 (`/merblog`)

임의 키워드 전체기간 검색 + 선택적 원문을 서버측에서 프록시(CORS 우회)해 정규화 JSON 반환.

**Files:**
- Modify: `cloudflare-worker/worker.js`

**Interfaces:**
- Produces: `GET /merblog?q=<kw>&page=<n>&size=<n>&sort=<sim|date>&full=<0|1>&fullK=<n>` → `{blogId, query, page, totalCount, count, posts:[{logNo,title,date,category,excerpt,url,fullText?}]}`

- [ ] **Step 1: 핸들러 함수 추가**

`cloudflare-worker/worker.js`에서 `async function handleAiSummary(` **정의 직전**(현재 line ~223 위)에 삽입:
```javascript
// ──────────────────────────────────────────────────────────────────
// 📝 메르 블로그(ranto28) 라이브 검색 — 네이버 모바일 API 프록시(CORS 우회)
//   GET /merblog?q=&page=&size=&sort=sim|date&full=0|1&fullK=
//   공개 엔드포인트(키 불필요). full=1 이면 상위 K개 원문(PostView)도 파싱해 동봉.
// ──────────────────────────────────────────────────────────────────
const MER_BLOG_ID = 'ranto28';
const MER_API_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15';
const MER_POST_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36';

function merStripHtml(s) {
  if (!s) return '';
  s = String(s).replace(/<[^>]+>/g, ' ');
  const ent = { '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };
  s = s.replace(/&nbsp;|&amp;|&lt;|&gt;|&quot;|&#39;/g, m => ent[m]);
  s = s.replace(/​/g, '');
  return s.replace(/\s+/g, ' ').trim();
}
function merKstIso(ms) {
  if (!ms) return null;
  // KST = UTC+9. Date 로 UTC 계산 후 +9h 표기.
  const d = new Date(Number(ms) + 9 * 3600 * 1000);
  const p = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}+09:00`;
}
function merNorm(raw) {
  const logNo = String(raw.logNo);
  return {
    logNo,
    title: merStripHtml(raw.title || raw.titleWithInspectMessage),
    date: merKstIso(raw.addDate),
    category: raw.categoryName || '',
    excerpt: merStripHtml(raw.contents || raw.briefContents),
    url: `https://blog.naver.com/${MER_BLOG_ID}/${logNo}`,
  };
}
function merExtractFulltext(htmlStr) {
  if (!htmlStr) return '';
  htmlStr = htmlStr.replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, ' ');
  const i = htmlStr.search(/se-main-container/);
  if (i < 0) return '';
  let body = htmlStr.slice(i);
  body = body.split(/wrap_postcomment|area_sympathy|post_footer|revenue_share|floating_menu/)[0];
  return merStripHtml(body).slice(0, 20000);
}
async function merFetchFulltext(logNo) {
  try {
    const r = await fetch(`https://blog.naver.com/PostView.naver?blogId=${MER_BLOG_ID}&logNo=${logNo}`,
      { headers: { 'User-Agent': MER_POST_UA } });
    if (!r.ok) return '';
    return merExtractFulltext(await r.text());
  } catch (e) { return ''; }
}
async function handleMerBlog(request) {
  const u = new URL(request.url);
  const q = (u.searchParams.get('q') || '').trim();
  if (!q) return jsonResponse({ error: 'q(검색어) 필요' }, 400);
  const page = Math.max(1, parseInt(u.searchParams.get('page') || '1', 10) || 1);
  const size = Math.min(30, Math.max(1, parseInt(u.searchParams.get('size') || '10', 10) || 10));
  const sort = u.searchParams.get('sort') === 'date' ? 'date' : 'sim';
  const full = u.searchParams.get('full') === '1';
  const fullK = Math.min(20, Math.max(1, parseInt(u.searchParams.get('fullK') || '5', 10) || 5));
  const api = `https://m.blog.naver.com/api/blogs/${MER_BLOG_ID}/search/post`
    + `?query=${encodeURIComponent(q)}&page=${page}&size=${size}&sortType=${sort}`;
  let data;
  try {
    const r = await fetch(api, { headers: { 'User-Agent': MER_API_UA, 'Referer': `https://m.blog.naver.com/${MER_BLOG_ID}` } });
    if (!r.ok) return jsonResponse({ error: 'naver_upstream', status: r.status }, 502);
    data = await r.json();
  } catch (e) {
    return jsonResponse({ error: 'naver_fetch_failed', detail: String(e) }, 502);
  }
  const result = data.result || {};
  const posts = (result.list || []).map(merNorm);
  if (full) {
    const targets = posts.slice(0, fullK);
    await Promise.all(targets.map(async p => { p.fullText = await merFetchFulltext(p.logNo); }));
  }
  return jsonResponse({
    blogId: MER_BLOG_ID, query: q, page,
    totalCount: result.totalCount || 0,
    count: posts.length, posts,
  });
}
```

- [ ] **Step 2: GET 라우팅에 연결**

`cloudflare-worker/worker.js`의 `async fetch(request, env)` 안, `const target = reqUrl.searchParams.get('url');`(현재 line ~861) **직전**에 삽입:
```javascript
    // 📝 메르 블로그 라이브 검색 (GET /merblog) — 공개 데이터, GET_CORS('*') 그대로 사용
    if (reqUrl.pathname === '/merblog') {
      const rl = await _rateLimited(env, 'PROXY_LIMITER', request, false);
      if (rl) return rl;
      return handleMerBlog(request);
    }
```
(`_rateLimited(...,false)`는 fail-open — 기존 GET 프록시와 동일. `PROXY_LIMITER` 미설정이어도 통과.)

- [ ] **Step 3: 로컬 문법 확인**

Run: `cd /c/Users/cgpar/economic-site && node --check cloudflare-worker/worker.js && echo "JS OK"`
Expected: `JS OK`

- [ ] **Step 4: 로컬 dev 서버로 라우트 검증**

Run(백그라운드): `cd /c/Users/cgpar/economic-site/cloudflare-worker && npx wrangler dev --port 8788`
그 다음:
```bash
KW=$(python -c "import urllib.parse;print(urllib.parse.quote('환율'))")
curl -s "http://127.0.0.1:8788/merblog?q=$KW&size=3&full=1&fullK=1" | python -c "import sys,json;d=json.load(sys.stdin);print('total',d['totalCount'],'count',d['count']);p=d['posts'][0];print('title',p['title'][:40]);print('fullText len',len(p.get('fullText','')))"
```
Expected: `total`>0, 첫 글 `fullText len`>200. (wrangler dev 인증 불필요; 종료는 프로세스 kill)

- [ ] **Step 5: 커밋**

```bash
cd /c/Users/cgpar/economic-site
git add cloudflare-worker/worker.js
git commit -m "feat(worker): GET /merblog 메르 블로그 라이브 검색 프록시(+원문)"
```

---

## Task 5: 프론트 UI — 「메르 블로그 검색」 페이지 (`index.html`)

검색창·결과리스트·원문보기·JSON 다운로드. 스냅샷 즉시필터 + Worker 라이브 폴백.

**Files:**
- Modify: `index.html`

**Interfaces:**
- Consumes: `merblog.json`(fetch), Worker `GET /merblog`
- Produces(전역 함수): `merblogInit()`, `merblogSearch()`, `merblogRenderResults(posts, mode)`, `merblogToggleFull(logNo, btn)`, `merblogDownloadJson()`

- [ ] **Step 1: 메뉴 항목 + 페이지 컨테이너 추가**

`index.html`에서 기존 사이드 메뉴 항목(예: `data-page` 또는 `onclick="showPage(...)"` 패턴)을 grep로 찾아 동일 형식으로 메뉴에 추가:
```bash
cd /c/Users/cgpar/economic-site && grep -nE "showPage\('|data-page=|id=\"page-" index.html | head -20
```
찾은 패턴과 동일하게: 메뉴에 「📝 메르 블로그」 항목(`showPage('merblog')`), 페이지 영역에 컨테이너 추가. 기존 페이지 컨테이너가 `<section id="page-XXX">` 형식이면 동형으로:
```html
<section id="page-merblog" class="page" style="display:none">
  <h2 class="page-title">📝 메르 블로그 검색</h2>
  <p class="muted">경제 블로거 "메르"(ranto28) 글을 키워드로 찾고 원문을 JSON으로 내려받습니다.</p>
  <div class="mer-searchbar">
    <input id="merQ" type="search" placeholder="예: 물가, 환율, 미국채 10년물" aria-label="검색어"
           onkeydown="if(event.key==='Enter')merblogSearch()">
    <label><input id="merLive" type="checkbox"> 전체기간 검색(라이브)</label>
    <label>정렬
      <select id="merSort"><option value="sim">관련도</option><option value="date">최신</option></select>
    </label>
    <button onclick="merblogSearch()">검색</button>
    <button id="merDl" onclick="merblogDownloadJson()" disabled>JSON 다운로드</button>
  </div>
  <div id="merStatus" class="muted" role="status" aria-live="polite"></div>
  <div id="merResults"></div>
</section>
```
(클래스명은 기존 테마 토큰에 맞춰 조정 — 기존 `.muted`/`.page-title` 등이 다르면 근접 클래스 사용.)

- [ ] **Step 2: 스타일 추가**

`index.html`의 인라인 `<style>` 블록 말미에 추가:
```css
.mer-searchbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}
.mer-searchbar input[type=search]{flex:1;min-width:220px;padding:8px 10px}
.mer-item{border:1px solid var(--border,#ddd);border-radius:8px;padding:12px;margin:8px 0}
.mer-item h3{margin:0 0 4px;font-size:15px}
.mer-item .mer-meta{font-size:12px;opacity:.7;margin-bottom:6px}
.mer-item .mer-excerpt{font-size:13px;line-height:1.5}
.mer-item .mer-full{white-space:pre-wrap;font-size:13px;line-height:1.6;margin-top:8px;
  max-height:420px;overflow:auto;border-top:1px dashed var(--border,#ddd);padding-top:8px}
.mer-item a{color:var(--accent,#356CB5)}
```

- [ ] **Step 3: 로직 추가(전역 스크립트 말미)**

`index.html`의 주 인라인 `<script>` 말미에 추가. Worker 베이스 URL은 기존 코드에서 재사용(grep로 확인):
```bash
cd /c/Users/cgpar/economic-site && grep -noE "https://[a-z0-9.-]*workers\.dev" index.html | head -3
```
그 상수/변수명을 `WORKER_BASE`로 참조(기존 이름이 다르면 그 이름 사용):
```javascript
// ── 📝 메르 블로그 검색 ──────────────────────────────────────
let _merSnapshot = null;      // merblog.json 캐시
let _merLastResults = [];     // JSON 다운로드용 마지막 결과
let _merLastQuery = '';

async function merblogInit(){
  if(_merSnapshot) return _merSnapshot;
  try{
    const r = await fetch('merblog.json?v=' + Date.now());
    _merSnapshot = r.ok ? await r.json() : {posts:[]};
  }catch(e){ _merSnapshot = {posts:[]}; }
  return _merSnapshot;
}
function _merEsc(s){ return (s||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function merblogSearch(){
  const q = (document.getElementById('merQ').value||'').trim();
  const live = document.getElementById('merLive').checked;
  const sort = document.getElementById('merSort').value;
  const status = document.getElementById('merStatus');
  const dl = document.getElementById('merDl');
  _merLastQuery = q;
  if(!q){ status.textContent='검색어를 입력하세요.'; return; }
  dl.disabled = true;
  if(!live){
    // 스냅샷 클라이언트 필터(즉시)
    status.textContent = '스냅샷에서 검색 중…';
    const snap = await merblogInit();
    const ql = q.toLowerCase();
    let hits = (snap.posts||[]).filter(p =>
      (p.title||'').toLowerCase().includes(ql) ||
      (p.excerpt||'').toLowerCase().includes(ql) ||
      (p.fullText||'').toLowerCase().includes(ql));
    if(sort==='date') hits = hits.slice().sort((a,b)=>(b.date||'').localeCompare(a.date||''));
    _merLastResults = hits;
    merblogRenderResults(hits, 'snapshot');
    status.textContent = `스냅샷 ${hits.length}건 (전체기간은 '라이브' 체크). ${snap.count||0}개 글 색인.`;
    dl.disabled = hits.length===0;
    return;
  }
  // 라이브(Worker)
  status.textContent = '네이버 전체기간 검색 중…';
  try{
    const url = `${WORKER_BASE}/merblog?q=${encodeURIComponent(q)}&size=20&sort=${sort}`;
    const r = await fetch(url);
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d = await r.json();
    _merLastResults = d.posts||[];
    merblogRenderResults(_merLastResults, 'live');
    status.textContent = `전체 ${d.totalCount||0}건 중 ${d.count||0}건 표시. 원문은 '원문 보기'로 로드.`;
    dl.disabled = (_merLastResults.length===0);
  }catch(e){
    status.textContent = '라이브 검색 실패: '+e.message+' (스냅샷으로 다시 시도해 보세요)';
  }
}

function merblogRenderResults(posts, mode){
  const box = document.getElementById('merResults');
  if(!posts.length){ box.innerHTML = '<p class="muted">결과 없음.</p>'; return; }
  box.innerHTML = posts.map(p => {
    const hasFull = !!p.fullText;
    const btn = hasFull
      ? `<button onclick="merblogToggleFull('${p.logNo}',this)">원문 보기</button>`
      : `<button onclick="merblogToggleFull('${p.logNo}',this)" data-load="1">원문 보기</button>`;
    return `<div class="mer-item" id="mer-${p.logNo}">
      <h3>${_merEsc(p.title)}</h3>
      <div class="mer-meta">${_merEsc(p.date||'')} · ${_merEsc(p.category||'')}
        · <a href="${p.url}" target="_blank" rel="noopener">원글↗</a></div>
      <div class="mer-excerpt">${_merEsc(p.excerpt||'')}</div>
      ${btn}
      <div class="mer-full" style="display:none"></div>
    </div>`;
  }).join('');
}

async function merblogToggleFull(logNo, btn){
  const box = document.querySelector('#mer-'+logNo+' .mer-full');
  if(box.style.display!=='none'){ box.style.display='none'; btn.textContent='원문 보기'; return; }
  const post = _merLastResults.find(p=>String(p.logNo)===String(logNo));
  if(post && post.fullText){
    box.textContent = post.fullText; box.style.display='block'; btn.textContent='원문 접기'; return;
  }
  // 라이브 온디맨드 로드
  btn.disabled=true; btn.textContent='불러오는 중…';
  try{
    const r = await fetch(`${WORKER_BASE}/merblog?q=${encodeURIComponent(_merLastQuery||post.title)}&size=20&full=1&fullK=20`);
    const d = await r.json();
    const hit = (d.posts||[]).find(p=>String(p.logNo)===String(logNo));
    const txt = hit && hit.fullText ? hit.fullText : '(원문을 불러오지 못했습니다. 원글↗ 링크를 이용하세요.)';
    if(post) post.fullText = txt;   // 캐시(다운로드에도 반영)
    box.textContent = txt; box.style.display='block'; btn.textContent='원문 접기';
  }catch(e){
    box.textContent='원문 로드 실패: '+e.message; box.style.display='block'; btn.textContent='원문 접기';
  }finally{ btn.disabled=false; }
}

function merblogDownloadJson(){
  const out = {
    blogId:'ranto28', blogName:'메르의 블로그',
    query:_merLastQuery, exportedAt:new Date().toISOString(),
    count:_merLastResults.length, posts:_merLastResults,
  };
  const blob = new Blob([JSON.stringify(out,null,2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `merblog_${(_merLastQuery||'search').replace(/[^\w가-힣]+/g,'_')}_${new Date().toISOString().slice(0,10)}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
}
```

- [ ] **Step 4: showPage 진입 훅**

`index.html`의 `showPage` 함수를 찾아(`grep -n "function showPage" index.html`), 'merblog' 진입 시 `merblogInit()`을 예열하도록 한 줄 추가(기존 페이지별 init 패턴과 동형):
```javascript
  if(id==='merblog') merblogInit();
```
(기존 `showPage`가 `switch`/`if` 어느 형태든 그 관례에 맞춰 삽입.)

- [ ] **Step 5: 렌더 검증(headless — repo 관행)**

Run:
```bash
cd /c/Users/cgpar/economic-site && node -e "const fs=require('fs');const h=fs.readFileSync('index.html','utf8');['page-merblog','merblogSearch','merblogDownloadJson','merblogToggleFull','mer-searchbar'].forEach(k=>{if(!h.includes(k))throw new Error('missing '+k);});console.log('markup+fns present OK')"
```
Expected: `markup+fns present OK`. 이어서 로컬 서버(`python -m http.server 8000`)로 페이지 열어 검색·다운로드 수동 확인(선택).

- [ ] **Step 6: 커밋**

```bash
cd /c/Users/cgpar/economic-site
git add index.html
git commit -m "feat(merblog): 대시보드 메르 블로그 검색 페이지(검색·원문보기·JSON 다운로드)"
```

---

## Task 6: 통합 검증 · 배포 · 문서화

**Files:**
- Modify: `CLAUDE.md`(기능 문서화)

- [ ] **Step 1: 전체 단위 테스트 재확인**

Run: `cd /c/Users/cgpar/economic-site && python scripts/test_merblog.py`
Expected: `ALL PASS`

- [ ] **Step 2: Worker 배포**

Run: `cd /c/Users/cgpar/economic-site/cloudflare-worker && npx wrangler deploy`
Expected: 배포 성공 + 버전 ID 출력. 이어 라이브 확인:
```bash
WORKER=$(cd /c/Users/cgpar/economic-site && grep -oE "https://[a-z0-9.-]*workers\.dev" index.html | head -1)
KW=$(python -c "import urllib.parse;print(urllib.parse.quote('미국채'))")
curl -s "$WORKER/merblog?q=$KW&size=2" | python -c "import sys,json;d=json.load(sys.stdin);print('total',d['totalCount'],'count',d['count'])"
```
Expected: `total`>0.

- [ ] **Step 3: 푸시(프론트 + 스냅샷 + 워크플로)**

```bash
cd /c/Users/cgpar/economic-site
git push origin HEAD:main
```
푸시가 `fetch-data` 트리거 → 몇 분 뒤 `merblog.json` 봇 커밋 갱신. GitHub Pages에 페이지 반영.

- [ ] **Step 4: 라이브 사이트 E2E 수동 확인**

`https://0101-commits.github.io/economic-site/?p=merblog` 열기 → "물가" 검색(스냅샷 즉시) → "라이브" 체크 후 재검색(전체기간) → 「원문 보기」 → 「JSON 다운로드」 파일 확인.

- [ ] **Step 5: CLAUDE.md 문서화 + 커밋**

`CLAUDE.md` Key Files 표에 행 추가:
```markdown
| `scripts/fetch_merblog.py` + `merblog_lib.py` | 메르 블로그(ranto28) 최근글 스냅샷 → `merblog.json` |
| `merblog.json` | 메르 블로그 검색 스냅샷(봇 커밋, 최근~150글·원문 20) |
```
그리고 Cloudflare Worker 섹션에 한 줄:
```markdown
- **GET /merblog** — 메르 블로그(ranto28) 라이브 키워드 검색 프록시(+원문, 공개 데이터·키 불필요)
```
커밋:
```bash
cd /c/Users/cgpar/economic-site
git add CLAUDE.md && git commit -m "docs(merblog): 기능 문서화" && git push origin HEAD:main
```

---

## Self-Review

**스펙 커버리지:**
- 파트1 스냅샷(별도 merblog.json·최근150·원문20·Actions) → Task 2,3 ✅
- 파트2 Worker 라이브(/merblog·CORS우회·상위K원문·K상한) → Task 4 ✅
- 파트3 프론트(패널·검색창·즉시/라이브·원문보기·JSON다운로드) → Task 5 ✅
- 검증방법(로컬실행·curl·headless) → 각 Task Step + Task 6 ✅
- 위험(sortType 미확정) → 실측 완료: `sortType=date` 동작 확인, 계획 반영 ✅
- YAGNI 제외(이미지/댓글/비공개) → 미포함 유지 ✅

**플레이스홀더 스캔:** 없음. 모든 코드 스텝에 실제 코드. UI 클래스/셀렉터·Worker 베이스·showPage 형태는 "grep로 기존 패턴 확인 후 동형 적용" 지시(기존 파일 의존 부분) — 실제 값 미상이라 정당한 조회 지시.

**타입 일관성:** 정규화 스키마 키(`logNo,title,date,category,excerpt,url`) Python(`norm_post`)·JS(`merNorm`)·프론트 렌더 전부 동일. `fullText` 선택 필드 일관. 함수명 `merblog*` 프론트, `mer*`/`handleMerBlog` 워커, `merblog_lib.*` 파이썬 — 중복 없음.

**한계 명시:** `extract_fulltext` 절단 마커는 휴리스틱 → Task 2 Step 3에서 실데이터 검증·조정 지시. 라이브 원문 온디맨드는 키워드 재검색으로 해당 logNo 매칭(같은 쿼리 20건 내) — 20건 밖 원문은 원글 링크 폴백(명시).
