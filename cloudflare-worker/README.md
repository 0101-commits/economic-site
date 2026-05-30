# 경제 대시보드 CORS 프록시 (Cloudflare Worker)

정적 사이트(GitHub Pages)의 브라우저에서 **실시간 금융 데이터**(네이버 주식 Top10,
Yahoo VIX/MOVE, Stooq 시계열, CNN 공포·탐욕, 환율, 뉴스)를 안정적으로 가져오기 위한
전용 CORS 프록시입니다. 추가로 **AI 시황 요약**(Claude) 중계 엔드포인트를 제공합니다.

## 🤖 AI 시황 요약 — `POST /ai` (Claude 중계)

대시보드의 "🤖 AI 요약 생성" 버튼을 누르면, 프론트엔드가 그 순간의 실시간 시장
스냅샷(JSON)을 `POST /ai` 로 보냅니다. Worker 는 시크릿 `ANTHROPIC_API_KEY` 로
Anthropic(Claude) API 를 호출해 한국어 마켓 브리핑을 생성해 돌려줍니다.

- **키는 Worker 시크릿에만 보관** → 브라우저에 노출되지 않습니다(정적 사이트에서 안전하게 LLM 사용).
- 키 설정:
  ```sh
  npx wrangler secret put ANTHROPIC_API_KEY
  # 또는 Cloudflare 대시보드: Workers & Pages > ecom-dashboard-proxy > Settings > Variables and Secrets
  ```
- **키 미설정 시**: `/ai` 는 503 을 반환하고, 프론트엔드는 자동으로 **자체 룰기반 요약**으로 폴백합니다(사이트는 정상 동작).
- 모델 기본값: `claude-haiku-4-5-20251001` (빠르고 저렴). 비용 보호를 위해 `max_tokens` 와 요청 본문 크기를 제한합니다.
- 테스트:
  ```sh
  curl -X POST 'https://<worker-url>/ai' -H 'content-type: application/json' \
       -d '{"snapshot":{"indices":{"KOSPI":{"price":8476,"change":3.5}}}}'
  ```

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

## 배포 — Git 연동 (대시보드, 현재 설정됨)

이 저장소는 Cloudflare Workers Builds 로 `main` 브랜치에 연결돼 있어,
**`main` 에 push/머지될 때마다 자동 배포**됩니다.

- 설정 파일: 저장소 **루트 `wrangler.jsonc`**
  - `name`: `ecom-dashboard-proxy` (대시보드 Worker 이름과 일치)
  - `main`: `cloudflare-worker/worker.js` (프록시 코드)
  - ⚠️ `assets` 를 두면 프록시가 아니라 저장소를 정적 서빙하게 되므로 넣지 않음
- 대시보드 Build settings (Compute > Workers & Pages > ecom-dashboard-proxy > Settings > Build)
  - **Root directory**: `/`
  - **Deploy command**: `npx wrangler deploy` (기본값)
  - **Build command**: 비움
- 배포 URL: `https://ecom-dashboard-proxy.baldr0001.workers.dev`

CLI 로 직접 배포하려면 저장소 루트에서 `npx wrangler deploy` (루트 `wrangler.jsonc` 사용).

## 프론트엔드 연결 — 이미 설정됨

`index.html` 상단 상수에 배포 URL 이 연결되어 있습니다:

```js
const CF_PROXY_DEFAULT = 'https://ecom-dashboard-proxy.baldr0001.workers.dev';
```

> 우선순위: `localStorage('cfProxyBase')` → `CF_PROXY_DEFAULT` → (미설정 시) 공개 프록시 폴백.
> URL 을 바꾸려면 위 상수를 수정하거나 콘솔에서 `localStorage.setItem('cfProxyBase', '...')`.

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
