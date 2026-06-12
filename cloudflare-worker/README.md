# 경제 대시보드 CORS 프록시 (Cloudflare Worker)

정적 사이트(GitHub Pages)의 브라우저에서 **실시간 금융 데이터**(네이버 주식 Top10,
Yahoo VIX/MOVE, Stooq 시계열, CNN 공포·탐욕, 환율, 뉴스)를 안정적으로 가져오기 위한
전용 CORS 프록시입니다. 추가로 **AI 시황 요약**(Claude) 중계 엔드포인트를 제공합니다.

## 🤖 AI 시황 요약 — `POST /ai`

대시보드의 "🤖 AI 요약 생성" 버튼을 누르면, 프론트엔드가 그 순간의 실시간 시장
스냅샷(JSON)을 `POST /ai` 로 보내고, Worker 가 LLM 으로 한국어 마켓 브리핑을 생성해 돌려줍니다.

엔진 우선순위 (위에서부터 자동 선택):

1. **🆓 Google Gemini (무료 API · 권장)** — `GEMINI_API_KEY` 시크릿이 있으면 최우선 사용.
   - 무료 키 발급: **https://aistudio.google.com/apikey** (Google AI Studio, 무료 등급 넉넉).
   - 키 설정:
     ```sh
     npx wrangler secret put GEMINI_API_KEY
     # 또는 Cloudflare 대시보드: Workers & Pages > ecom-dashboard-proxy > Settings > Variables and Secrets
     ```
   - 모델(고성능 최신 우선, 무료 한도/가용성 폴백): `gemini-2.5-pro` → `gemini-2.5-flash`
     → `gemini-2.0-flash` → `gemini-1.5-flash`. 2.5 Pro 무료 한도 초과(429) 시 자동으로 Flash 로 폴백.
     프론트가 `geminiModel` 로 강제 지정 가능. 키는 Worker 시크릿에만 보관(브라우저 비노출).
2. **Cloudflare Workers AI (무료 · 키 불필요)** — `wrangler.jsonc` 의 `"ai": { "binding": "AI" }` 가
   배포에 적용된 경우 사용. 무료 플랜 일 10,000 Neurons. 모델: `@cf/meta/llama-3.1-8b-instruct` 등.
3. **Anthropic Claude (선택)** — `ANTHROPIC_API_KEY` 시크릿이 있으면 사용(고품질).
4. **룰기반 요약 (API 없음)** — 위 모두 불가하면 `/ai` 가 503 을 반환하고, 프론트엔드가
   **브라우저 내 룰기반 요약**으로 폴백합니다(네트워크/키/비용 0, 데이터가 외부로 나가지 않음).

- **상태 확인**: 브라우저에서 `https://<worker-url>/ai` (GET) 을 열면
  `{geminiKey, aiBinding, anthropicKey, engine}` 로 어떤 엔진이 활성인지 즉시 확인됩니다.
- 비용/남용 보호: `max_tokens` 와 요청 본문 크기를 제한합니다.
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

- 오픈 프록시 남용을 막기 위해 `worker.js`의 `ALLOWED_HOSTS` **화이트리스트에 등록된
  호스트만** 통과시킵니다. (네이버/야후/Stooq/CNN/환율/뉴스 출처만)
- **Origin 화이트리스트** — POST(`/ai`·`/portfolio`·`/portfolio/test`)는 자기 사이트
  출처(`https://0101-commits.github.io`)·로컬 개발만 허용합니다.
- **IP 레이트리밋** — `wrangler.jsonc` 의 Rate Limiting 바인딩으로 POST 분당 10회,
  프록시 GET 분당 120회를 제한합니다(무료 일 10만 요청 한도·LLM 비용 보호).
  바인딩 미설정 시에는 통과(fail-open)하므로 배포가 깨지지 않습니다.
- **알림 동기화 키(필수)** — `POST /portfolio` 쓰기는 `ALERTS_SYNC_KEY` 시크릿이
  설정되어 있고 요청의 `keyHash`(SHA-256)가 일치할 때만 허용됩니다. 시크릿 미설정 시
  쓰기 자체가 비활성(fail-closed — 무인증 쓰기 개방 방지). 평문 키 호환은 제거됨.
  ```sh
  npx wrangler secret put ALERTS_SYNC_KEY   # 충분히 긴 랜덤 문자열 (예: openssl rand -hex 24)
  ```
  설정 후 프론트 '투자 현황' 페이지의 🔑 동기화 키 버튼에 동일 키를 입력하세요.
- **토큰 권한 분리(선택)** — `GH_ALERTS_TOKEN` 시크릿(Contents RW, 이 저장소 한정)을
  추가하면 `alerts_config.json` 커밋에는 그것만 쓰이고, `GH_DISPATCH_TOKEN` 은
  dispatch 전용으로 권한을 낮출 수 있습니다. 미설정 시 기존처럼 공용.

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

> 우선순위: `localStorage('cfProxyBase')` → `CF_PROXY_DEFAULT`. 공개 프록시 폴백은
> 제거되었습니다(제3자가 시세 응답을 변조할 수 있는 경로 — 2차 보안 개선 S-3).
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

Worker URL 미설정/장애 시에도 사이트는 동작합니다 — 클라이언트 실시간 보강만 조용히
스킵되고, GitHub Actions 가 커밋하는 `data.json` 서버 값이 표시됩니다. (과거의 공개
CORS 프록시 자동 폴백은 데이터 변조 가능 경로라 제거되었습니다.)
