# 경제 대시보드 CORS 프록시 (Cloudflare Worker)

정적 사이트(GitHub Pages)의 브라우저에서 **실시간 금융 데이터**(네이버 주식 Top10,
Yahoo VIX/MOVE, Stooq 시계열, CNN 공포·탐욕, 환율, 뉴스)를 안정적으로 가져오기 위한
전용 CORS 프록시입니다.

## 왜 필요한가

- 이 사이트는 백엔드가 없는 정적 사이트라, 실시간 데이터는 브라우저가 외부 API를
  직접 호출해야 합니다.
- 그런데 대부분의 금융 API는 **CORS를 허용하지 않고**, 특히 **네이버 모바일 API**는
  `Referer`/`Origin`/`User-Agent` 헤더가 없으면 거부합니다. 브라우저는 이 헤더들을
  직접 설정할 수 없습니다.
- 공개 CORS 프록시(allorigins/codetabs 등)는 **가용성이 들쭉날쭉**하고 헤더를 제대로
  전달하지 못해, "Top10이 오전 데이터에 고정되는" 문제의 근본 원인이 됩니다.
- 이 Worker는 타깃별로 **적절한 헤더를 주입**해서 가져온 뒤 `Access-Control-Allow-Origin: *`
  로 응답하므로, 프론트엔드가 안정적으로 실시간 데이터를 받습니다.

## 보안

오픈 프록시 남용을 막기 위해 `worker.js`의 `ALLOWED_HOSTS` **화이트리스트에 등록된
호스트만** 통과시킵니다. (네이버/야후/Stooq/CNN/환율/뉴스 출처만)

## 배포

> Cloudflare 계정이 필요합니다(무료). 하루 100,000 요청까지 무료라 개인 대시보드에는 충분합니다.

### 방법 1 — Git 연동 (대시보드, 권장)

대시보드에서 이 저장소(`0101-commits/economic-site`)에 연결해 Worker 를 만들면,
**`main` 브랜치에 push 될 때마다 자동 배포**됩니다. 저장소 루트의 `wrangler.toml`
(`name = "ecom-dashboard-proxy"`, `main = "cloudflare-worker/worker.js"`)을 사용합니다.

- Cloudflare 대시보드 > **Compute > Workers & Pages** > 해당 Worker > **Settings > Build**
  - **Root directory**: `/` (저장소 루트)
  - **Deploy command**: `npx wrangler deploy` (기본값)
  - **Build command**: 비워둠 (단일 JS, 의존성 없음)
- ⚠️ Worker 이름이 루트 `wrangler.toml` 의 `name` 과 **정확히 일치**해야 같은 URL 로 배포됩니다.
- 코드(`cloudflare-worker/worker.js`)가 `main` 에 머지된 뒤 빌드가 실행되어야 실제 프록시가 배포됩니다.

### 방법 2 — CLI (wrangler)

```bash
# 저장소 루트에서 (루트 wrangler.toml 사용)
npx wrangler login     # 브라우저 인증
npx wrangler deploy
```

배포 후 URL: `https://ecom-dashboard-proxy.<your-account>.workers.dev`

## 프론트엔드 연결 (2가지 방법 중 택1)

### 방법 A — 코드에 직접 설정 (영구)

`index.html` 상단의 상수를 수정합니다:

```js
const CF_PROXY_DEFAULT = 'https://econ-dashboard-proxy.<your-account>.workers.dev';
```

커밋·푸시하면 모든 방문자에게 적용됩니다. (배포된 URL이 외부에 노출되지만,
화이트리스트 덕분에 지정된 금융 API 중계에만 쓰입니다.)

### 방법 B — 브라우저에서 즉시 설정 (코드 수정 없이 테스트)

사이트를 연 상태에서 개발자 콘솔(F12)에 입력:

```js
localStorage.setItem('cfProxyBase', 'https://econ-dashboard-proxy.<your-account>.workers.dev');
location.reload();
```

> 우선순위: `localStorage('cfProxyBase')` → `CF_PROXY_DEFAULT` → (미설정 시) 공개 프록시 폴백.

## 동작 확인

1. 브라우저에서 `https://<worker-url>/` 직접 열기 → `{"ok":true, ...}` JSON이 보이면 정상.
2. 대시보드에서 **Top10 카드 기준 표시가 `실시간 HH:MM · 네이버`** 로 바뀌고
   장중 1분마다 값이 갱신되면 연결 성공입니다.
3. 콘솔에서 테스트:
   ```js
   fetch('https://<worker-url>/?url=' + encodeURIComponent('https://m.stock.naver.com/api/stocks/exchange/KOSPI/up?page=1&pageSize=5')).then(r=>r.json()).then(console.log)
   ```

## 비용/한도

- Cloudflare Workers Free: **100,000 요청/일**. 30초 edge 캐시가 있어 동시 사용자가
  많아도 origin 호출이 합쳐집니다. 개인/소규모에는 무료로 충분합니다.

## 미설정 시 동작

Worker URL을 설정하지 않아도 사이트는 정상 동작합니다 — 기존 공개 CORS 프록시로
자동 폴백합니다. Worker는 **신뢰성을 끌어올리는 최우선 경로**로만 쓰입니다.
