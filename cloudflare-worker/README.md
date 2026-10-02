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

### 요청 모드 (system 프롬프트는 전부 서버 고정 — 클라이언트가 주입 불가)

| 본문 | 모드 | 출력 |
|------|------|------|
| `{snapshot}` | 마켓 브리핑 | 250~500자 마크다운 브리핑 + "※ 투자 참고용" |
| `{snapshot, question}` | 단발 Q&A | 4문장 이내 답변 + "※ 투자 조언이 아닙니다" |
| `{snapshot, mode:"study"}` | **스터디 회의록** | `# 안건 / # 핵심 논의 / # 결론 / # 액션 아이템` 4섹션 불릿 |

`mode:"study"` 는 **스터디 기록** 페이지의 `✨ AI 요약 초안` 전용입니다. 입력이 시장 데이터가 아니라
사용자가 쓴 회의 메모라서 애널리스트 프롬프트(4문장 제한·투자 고지)로는 회의록이 나오지 않기 때문에
별도 프롬프트를 씁니다. `mode` 가 `question` 보다 우선하며(프론트는 구버전 Worker 폴백용으로 둘 다 전송),
출력 토큰 상한도 회의록 길이에 맞춰 늘립니다. 메모원문은 신뢰할 수 없는 텍스트로 취급합니다(지시 무시).

> ⚠ 스터디 모드는 회의록 텍스트만 전송합니다 — 업로드한 영상·음성·문서 파일은 브라우저(IndexedDB)에만
> 남고 Worker 로 절대 전송되지 않습니다. 세 모드 모두 `keyHash`(`ALERTS_SYNC_KEY` SHA-256) 인증 필요.

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
  설정 후 사이트 ⚙ 설정 페이지의 🔑 동기화 키 버튼에 동일 키를 입력하세요.
- **동기화 키 바꾸기 / 잊었을 때** — 사이트 ⚙ 설정의 「키 바꾸기」가 `POST /sync-key`
  (헤더 `X-Sync-Key-Hash` = 지금 키 해시, 본문 `{newKeyHash}`)로 새 암호의 SHA-256 을 KV
  `ECON_PORTFOLIO` 의 `auth:syncKeyHash` 에 저장합니다. 이 값이 있으면 시크릿보다 우선하고, 모든 인증
  경로(`/portfolio` GET·POST, `/portfolio/test`, `/ai`, `/sync-key`)가 `_verifySyncKey` 한 곳에서
  같은 규칙을 씁니다. 본문에 `newKeyHash` 가 없으면 확인만 합니다(사이트의 「PIN 잊음」). KV 는 지역 간
  전파에 최대 1분이 걸려, 바꾼 직후 잠깐은 다른 지역에서 옛 키가 통할 수 있습니다.
  **바꾼 암호를 잊으면** KV 값을 지워 시크릿 `ALERTS_SYNC_KEY` 로 되돌립니다(저장소 루트에서):
  ```sh
  npx wrangler kv key delete --binding ECON_PORTFOLIO --remote auth:syncKeyHash
  ```
  시크릿 값도 모르면 새로 정합니다: `npx wrangler secret put ALERTS_SYNC_KEY`. 어느 쪽이든 각 기기의 🔑 에 그 키를 다시 넣습니다.
- **토큰 권한 분리(선택)** — `GH_ALERTS_TOKEN` 시크릿(Contents RW, 이 저장소 한정)을
  추가하면 `alerts_config.json` 커밋에는 그것만 쓰이고, `GH_DISPATCH_TOKEN` 은
  dispatch 전용으로 권한을 낮출 수 있습니다. 미설정 시 기존처럼 공용.

## 1층 사용자 데이터 — `/prefs` · `/push/subscribe`

기획안 v4 보안 위험 3 조치입니다. 관심 지표·종목, 알림 조건, 화면 설정, 시나리오를 공개 저장소 파일
(`alerts_config.json`)이 아니라 KV `ECON_PORTFOLIO` 에 둡니다. 인증과 레이트리밋은 다른 경로와 같습니다.

- 인증: 헤더 `X-Sync-Key-Hash` = 동기화 키의 SHA-256(hex). `_verifySyncKey` 한 곳에서 검사합니다. 틀리면 401.
- 레이트리밋: `AI_LIMITER`(IP당 분당 10회, `/ai`·`/portfolio` 와 같은 바구니). 바인딩이 없으면 503. 설정을 바꿀 때마다 PUT 하면 429 가 나기 쉬우니 화면에서 모아 보냅니다.
- 응답: 인증이 필요한 경로라 모든 응답에 `Cache-Control: no-store` 가 붙습니다. 예상 못 한 오류도 CORS 가 붙은 500 `internal_error` 로 돌아옵니다.
- 출처: 운영 출처만 허용하고, 개발 출처는 아래 「출처(CORS)」의 플래그가 있을 때만 허용합니다.

### `GET /prefs`

저장본이 없으면 빈 기본값을 200 으로 줍니다.

```sh
curl -H "X-Sync-Key-Hash: <키 해시>" https://ecom-dashboard-proxy.e-hcg.workers.dev/prefs
```

```json
{ "v": 1, "updatedAt": null, "watch": [], "alerts": [],
  "settings": { "theme": "system", "updown": "kr", "unit": "man", "quiet": null }, "scenarios": [] }
```

### `PUT /prefs` — 전체 교체

```sh
curl -X PUT -H "X-Sync-Key-Hash: <키 해시>" -H "content-type: application/json" \
     -H "If-Match: 2026-10-01T03:00:00.000Z" \
     -d '{"watch":[{"id":"kospi","kind":"indicator"}],"alerts":[{"id":"a1","target":"005930","type":"price","cond":{"op":">=","value":90000},"repeat":"once","channels":["push"],"enabled":true}],"settings":{"theme":"dark"}}' \
     https://ecom-dashboard-proxy.e-hcg.workers.dev/prefs
```

응답은 실제로 저장된 문서입니다. 무엇이 버려졌는지 이 응답으로 확인합니다.
`updatedAt` 은 서버가 정하고, 저장본보다 항상 큽니다. 받은 문서를 그대로 다시 PUT 해도 통과합니다.

| 필드 | 형태 | 상한 |
|---|---|---|
| `watch[]` | `{ id, kind: "indicator"\|"stock", addedAt }` | 100개 |
| `alerts[]` | `{ id, target, type: "price"\|"pct"\|"high52"\|"event"\|"flow"\|"lens", cond: {…}, repeat: "once"\|"daily", channels: ["push","discord"], enabled }` | 100개, `cond` 512자 |
| `settings` | `{ theme: "system"\|"light"\|"dark", updown: "kr"\|"us", unit: "man"\|"won", quiet: { from: "HH:MM", to: "HH:MM" } }` | `theme`·`updown`·`unit` 은 모르는 값이면 첫 값, `quiet` 는 둘 다 HH:MM 문자열이 아니면 `null` |
| `scenarios[]` | `{ name, inputs: {…} }` | 20개, `name` 60자 |

거부와 버림의 규칙은 다음과 같습니다.

- **버림**: 표에 없는 필드, 모르는 `kind`·`type`, 형식 밖 `id`·`target`(영문·숫자·`._:^=-`, 64자까지), 상한을 넘는 항목. 같은 `kind`+`id` 의 관심 항목은 하나만 남습니다.
- **400 `tier2_field_rejected`**: 보유정보 이름의 키가 본문 어디에든 있으면 통째로 거부합니다. 버려질 필드 안과 `cond`·`inputs` 안도 봅니다. 키 이름은 NFKC 정규화·소문자화 뒤 공백·`_`·`-`·보이지 않는 글자를 빼고 비교합니다(전각 ｑｔｙ, `avg_price` 도 걸립니다). 목록은 `worker.js` 의 `TIER2_KEYS` 입니다(`avg`·`avgPx`·`qty`·`shares`·`units`·`position`·`fxBuy`·`costKrw`·`holdings`·`평단가`·`평균단가`·`수량`·`매입금액`·`투자금액` 등).
  단독 `amount`·`금액`·`balance` 는 막지 않습니다. 수급 알림 `cond` 의 금액 기준이나 시나리오 입력이 정당하게 쓰기 때문입니다. 이름 목록이라 작정하고 바꾼 이름은 못 막습니다. 목적은 화면이 실수로 보유정보를 섞는 것을 막는 것입니다.
- **400**: `cond` 가 512자를 넘을 때(`cond_too_large`), 중첩이 너무 깊을 때(`too_deep`, 본문 6단까지라 `cond`·`inputs` 안은 2단까지), JSON 이 아닐 때.
- **413**: 본문이 32KB(UTF-8 바이트 기준)를 넘을 때(`payload_too_large`). 정리한 저장 문서가 기본값이 채워져 32KB 를 넘을 때도 413 입니다(`prefs_too_large`).
- **409 `conflict`**: `If-Match` 가 저장본의 `updatedAt` 과 다를 때. 다른 기기가 먼저 저장했다는 뜻이므로 다시 읽고 합쳐서 저장합니다. 저장본이 없을 때는 `If-Match: ""` 또는 `null` 이 통과합니다. `If-Match` 를 빼면 확인 없이 덮어씁니다. 값 비교만 하므로 `*` 와 `W/"…"` 는 409 가 됩니다.
  KV 에는 트랜잭션이 없고, 다른 지역에 반영되기까지 최대 약 60초 걸립니다. 그 사이 다른 지역 기기끼리 저장하면 서로 덮어쓸 수 있습니다. 같은 기기의 연속 저장은 잡힙니다.

### `/push/subscribe` — 웹 푸시 구독 보관

발송은 다음 단계입니다. 지금은 구독을 받아 두기만 합니다.
Worker 시크릿 `VAPID_PUBLIC_KEY` 가 없으면 인증(401)을 통과한 요청은 세 메서드 모두 503 입니다. 그 밖의 메서드는 405 입니다.

| 메서드 | 본문 | 응답 |
|---|---|---|
| `GET` | 없음 | `{ vapidPublicKey, count }`. 브라우저 `pushManager.subscribe` 의 `applicationServerKey` 로 씁니다. |
| `PUT` | `PushSubscription.toJSON()` 그대로 | `{ ok, count }`. 같은 `endpoint` 는 교체합니다(기기당 1개). 5개를 넘으면 가장 오래된 것을 버립니다. |
| `DELETE` | `{ "endpoint": "…" }` | `{ ok, count }` |

`endpoint` 는 https 이면서 알려진 브라우저 푸시 서비스여야 하고, 사용자 정보·포트가 붙으면 안 됩니다(`fcm.googleapis.com`, `*.push.services.mozilla.com`,
`*.notify.windows.com`, `*.push.apple.com`). 보관 필드는 `endpoint`·`expirationTime`·`keys.p256dh`·`keys.auth` 뿐입니다.

### KV 키 형식(`ECON_PORTFOLIO`, id `49d7bd1ee2874995a7bf0439c4e297b3`)

| 키 | 값 |
|---|---|
| `prefs:<키 해시 앞 16자>` | `/prefs` 문서(JSON) |
| `push:<키 해시 앞 16자>` | 구독 배열(JSON, 최대 5개) `[{ endpoint, expirationTime, keys: { p256dh, auth } }]` |
| `auth:syncKeyHash` | 사이트에서 바꾼 동기화 키의 해시(기존) |
| `portfolio:encHoldings` | 암호화 보유정보(기존) |

키 해시 앞 16자는 `sha256(동기화 키)` 의 hex 앞 16자입니다. 발송 스크립트는 해시를 몰라도 접두어로 찾을 수 있습니다.

**KV 읽기 권한은 로그인 권한과 같습니다.** Cloudflare API 의 「Workers KV Storage: Read」 토큰은 계정 단위라 이름공간 하나로
좁힐 수 없습니다. 그 토큰으로 `auth:syncKeyHash` 도 읽히는데, 이 값은 서버가 비교하는 해시 그 자체라 그대로 보내면 인증을 통과합니다.
그래서 발송 스크립트에 이 토큰을 주면 동기화 키를 준 것과 같습니다. 그 토큰은 동기화 키와 같은 등급으로 보관합니다.
더 좁히려면 Worker 에 발송용 읽기 경로를 따로 만들고 별도 시크릿으로 지킵니다(후속 과제).

```sh
# 저장소 루트에서 — 목록과 값
npx wrangler kv key list --binding ECON_PORTFOLIO --remote --prefix push:
npx wrangler kv key get  --binding ECON_PORTFOLIO --remote "push:<키 해시 앞 16자>"
# 스크립트(HTTP)
GET https://api.cloudflare.com/client/v4/accounts/<account_id>/storage/kv/namespaces/49d7bd1ee2874995a7bf0439c4e297b3/keys?prefix=push:
GET https://api.cloudflare.com/client/v4/accounts/<account_id>/storage/kv/namespaces/49d7bd1ee2874995a7bf0439c4e297b3/values/push:<키 해시 앞 16자>
```

**동기화 키를 바꾸면** 새 키의 빈 공간에서 시작합니다. 옛 값은 옛 키 아래 그대로 남습니다.
옮기려면 옛 키의 값을 `kv key get` 으로 받아 새 키 이름으로 `kv key put` 합니다.

### 출처(CORS)

- **운영**: `https://0101-commits.github.io` 만 허용합니다. 새 화면 층은 `/economic-site/next/` 에 배포되어 출처가 같으므로 추가할 것이 없습니다. 응답의 `Access-Control-Allow-Origin` 은 별표가 아니라 요청 출처를 그대로 돌려줍니다.
- **개발**: `http://localhost:5173`·`http://127.0.0.1:5173`(Vite) 은 변수 `DEV_CORS=1` 일 때만 허용합니다. 기본은 불허입니다. 이 플래그는 `/ai`·`/portfolio` 같은 기존 POST 경로의 응답 CORS 에도 똑같이 적용됩니다.
  ```sh
  npx wrangler dev --var DEV_CORS:1          # 로컬 Worker 로 개발할 때
  npx wrangler secret put DEV_CORS           # 운영 Worker 에 잠깐 켤 때(값 1). 끝나면 반드시 끈다:
  npx wrangler secret delete DEV_CORS
  ```
  운영 Worker 에서 `vars` 로 켜면 다음 자동 배포가 지웁니다. 시크릿으로 켠 것은 직접 지울 때까지 남습니다.

### 배포에 필요한 것

```sh
# 저장소 루트에서(설정 파일 wrangler.jsonc 가 루트에 있다). 실행은 담당자.
npx wrangler secret put VAPID_PUBLIC_KEY   # /push/subscribe 용. 없으면 그 경로만 503
npx wrangler deploy
```

- VAPID 키 한 쌍은 `npx web-push generate-vapid-keys` 로 만듭니다. 공개키는 위 Worker 시크릿에 넣습니다. 개인키(`VAPID_PRIVATE_KEY`)와 연락처(`VAPID_SUBJECT`, `mailto:…`)는 발송 스크립트 쪽 시크릿에만 둡니다. Worker 는 개인키를 쓰지 않습니다.
- 둘 다 코드·설정 파일에 값을 쓰지 않습니다. KV 바인딩과 `AI_LIMITER` 는 이미 `wrangler.jsonc` 에 있습니다.

### 현행 `/portfolio` 와의 관계(과도기)

- 현행 화면(`index.html`)은 지금처럼 `/portfolio` 를 씁니다. 새 화면은 `/prefs` 만 읽고 씁니다.
- 그래서 관심 종목이 두 곳에 있을 수 있습니다. 하나는 `/portfolio` 의 `tracking`(공개 `alerts_config.json`)이고, 하나는 `/prefs` 의 `watch` 입니다. 둘을 자동으로 맞추지 않습니다.
- 알림 파이프라인(`check_alerts.py`)은 아직 `alerts_config.json` 만 읽습니다. **`/prefs` 의 `alerts` 는 아직 발송되지 않습니다.** 파이프라인이 `/prefs` 를 읽게 바꾸는 것은 후속 과제입니다. 이때 알림 종류 이름도 옮겨야 합니다. 현행은 `price_above`·`price_below`·`pct_change` 등이고, 새것은 `price`·`pct` 등입니다.
- 2층 보유정보는 두 경로 어디에도 평문으로 두지 않습니다. 암호문은 `/portfolio` 의 `encHoldings` 하나뿐입니다.

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
- 배포 URL: `https://ecom-dashboard-proxy.e-hcg.workers.dev`

CLI 로 직접 배포하려면 저장소 루트에서 `npx wrangler deploy` (루트 `wrangler.jsonc` 사용).

## 프론트엔드 연결 — 이미 설정됨

`index.html` 상단 상수에 배포 URL 이 연결되어 있습니다:

```js
const CF_PROXY_DEFAULT = 'https://ecom-dashboard-proxy.e-hcg.workers.dev';
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
