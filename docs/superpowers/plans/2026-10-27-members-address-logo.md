# ecom 멤버 입장 · 새 주소 · ECOM 로고 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 마스터 1명 + 초대 멤버가 각자 입장 키로 들어와 자산 · 관심 · 알림을 따로 쓰는 ecom 을, 새 주소 `ecom-terminal.pages.dev` 와 ECOM 로고로 낸다.

**Architecture:** Worker KV 에 사람 표(`user:`/`ukey:`/`users:index`)를 두고 모든 인증 경로를 해석기 하나(`resolveUser`)로 모은다 — 사람 표가 없으면 지금의 단일 키 방식으로 그대로 동작(마이그레이션 전 무변화). 앱은 키 해시 소지 방식을 그대로 쓰고 입장 화면 · 계정 메뉴 · 멤버 관리 화면을 더한다. 새 주소는 Cloudflare Pages `_worker.js` 가 GitHub Pages 원본을 넘겨받는 방식이라 수집 · 배포는 그대로다.

**Tech Stack:** Cloudflare Workers + KV(JS, 무빌드), React 18 + TS + Vite 8 + Tailwind v4(`app/`, `node --test`), Python 3(GHA 파이프라인, pytest), Playwright(아이콘 렌더 · UI 게이트).

**Spec:** `docs/superpowers/specs/2026-10-27-members-address-logo-design.md` (기획서 https://claude.ai/artifact/RB5d4CA5stqjfaW4mZMj7k 판 3, D1~D7 권고안 승인됨 2026-10-27)

## Global Constraints

- 저장소는 **공개**다. 멤버의 이름 · 관심 · 조건 · 종목은 저장소 파일(`alerts_config.json` · `alerts_state.json` · `events/` · `briefs/` 등)에 절대 쓰지 않는다. 공개 파일엔 무작위 uid 나 HMAC 만.
- `alerts_config.json` 은 마스터 것 그대로(수집기 6곳이 읽음). 멤버 관심은 넣지 않는다(D7).
- 무료 한도: Workers 하루 100,000 요청(계정 공유) · KV 쓰기 하루 1,000 · KV list 하루 1,000 → **KV `.list()` 금지**, 접속일은 하루 1회만 쓰기.
- 입장 키 형식 `ECOM-XXXX-XXXX-XXXX`, 알파벳 `23456789ABCDEFGHJKMNPQRSTUVWXYZ`(31자, 0 O 1 I L 없음), 무작위 12자. 서버엔 SHA-256 해시만, 키 원문은 발급 응답 1회만.
- 정규화는 `ECOM` 형식으로 읽히는 입력에만(공백 · 하이픈 제거 + 대문자). 그 밖의 키는 지금처럼 `trim()` 만 — 마스터의 지금 동기화 키 해시와 보유 열쇠(`holdKeyOf`)가 바뀌면 안 된다.
- 화면 용어: 마스터 / 멤버 / 입장 키. 내부 role 값 `owner` / `member`, 상태 `active` / `paused`.
- 멤버 AI 질문 하루 30회(D4), 마스터 무제한. 키 없는 방문자는 입장 화면만(D1). 옛 주소는 안내 띠만, 자동 이동 없음(D3). 초록은 로고 · 입장 화면 · 아이콘만(D5). 옛 화면 legacy 는 마스터만(D6).
- 새 주소 `https://ecom-terminal.pages.dev/`, 원본 `https://0101-commits.github.io/economic-site/`. 색: 진초록 `#005034`, 로고 초록 `#006F3A`, 보조 `#00744C`, 연초록 `#B5C9BA`.
- 앱 라우트는 `<Route path="…" element={…} />` 한 줄 형식 유지(`scripts/tests/test_v2_urls.py:27` 이 정규식으로 읽음).
- 앱 테스트는 `node --test`(타입 제거 실행) — 테스트가 읽는 모듈의 런타임 import 는 `.ts` 확장자를 붙인다.
- 커밋 메시지에 배포 명령 글자(`wrangler deploy`)를 쓰지 않는다(원격 승인 훅 오탐). 커밋 끝 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 작업 위치 = 워크트리 `C:\Users\cgpar\economic-site\.claude\worktrees\members`(브랜치 `worktree-members`). 이 PC 메모리 1~4GB — Playwright · vite 는 한 번에 하나.

## Review Focus

1. **마이그레이션 전 Worker 배포** — 사람 표가 없을 때 마스터의 지금 키로 `/prefs` · `/portfolio` · `/push/*` · `/ai` · `/sync-key` 가 지금과 똑같이 동작해야 한다(공간 이름도 `hash16` 그대로). → Task 5 `legacy mode` 시험.
2. **마스터 키에 대문자 · 공백 · 하이픈이 섞인 경우** — 정규화가 건드리지 않아 해시가 같아야 한다. → Task 4 `normalizeEntryKey` 시험의 `'My-Key 2026 Pass'` 행.
3. **한 기기에서 멤버를 바꿔 들어오기** — 이전 사람의 보유 · 원장 · 스냅샷 · 관심이 보이면 안 되고, 다시 들어오면 그대로 돌아와야 한다. → Task 9 시험.
4. **멈춘 키 · 다시 만든 키로 이미 들어와 있던 기기** — 403 은 아무것도 안 지우고 입장 화면, 401 은 해시 · 보유 열쇠만 지우고 입장 화면. → Task 9 · 10 시험.
5. **알림 파이프라인이 멤버 조건을 정리하다 마스터 조건 상태를 지우는 것** — `run.py:90-93` 의 `_prefs` 정리는 전체 사람의 현재 키 합집합 기준이어야 한다. → Task 14 시험.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `cloudflare-worker/users.js` (신규) | 입장 키 정규화 · 생성, uid, 사람 표 CRUD, `resolveUser`(60초 캐시), 마이그레이션 |
| `cloudflare-worker/worker.js` | 인증 해석기 교체, 공간 = uid, 새 경로(`/me` · `/admin/*` · `/prefs/all` · `/push/subscriptions/all` · `/fired`), CORS · AI 한도 |
| `cloudflare-worker/test_users.mjs` · `test_members.mjs` (신규) | 사람 표 단위 · 경로 통합 시험 |
| `cloudflare-pages/_worker.js` · `test_proxy.mjs` · `README.md` (신규) | 새 주소 넘김 장치 + 시험 + 만들기 · 배포 절차 |
| `scripts/brand/` (신규) | 로고 원본 PNG · 벡터 추적 · 아이콘 렌더 · 겹침 검사 |
| `app/public/brand/*.svg`, `app/public/{favicon.svg,icon-*.png,badge-96.png,apple-touch-icon.png,og-cover.png}` | 브랜드 산출물 |
| `app/src/components/Brand.tsx` (신규) | `BrandMark` · `BrandWord` · `BrandLogo` 인라인 SVG |
| `app/src/components/MovedBanner.tsx` (신규) | 옛 주소 안내 띠 |
| `app/src/lib/personal/entryKey.ts` (신규) | 앱 쪽 `normalizeEntryKey`(Worker 와 같은 규칙) |
| `app/src/lib/personal/account.ts` (신규) | `/me` · 입장 · 나가기 · 현재 사람 · 관리 호출 |
| `app/src/lib/personal/store.ts` | 멤버 저장 이름 `:<uid>` 접미 |
| `app/src/screens/Welcome.tsx` · `Members.tsx` (신규) | 입장 화면 · 멤버 관리 |
| `app/src/components/personal/AccountMenu.tsx` · `MyAccount.tsx` (신규) | 머리줄 이름 메뉴 · 설정 「내 계정」 |
| `scripts/app_url.py` (신규) | 알림 · 메시지 링크 주소 단일 원천 |
| `scripts/prefs_client.py` · `alerts_v2/{subscribe,run,deliver}.py` · `send_push.py` · `check_alerts.py` | 사람별 순회 |

---

# P1 주소 · 로고

### Task 1: ECOM 로고 벡터화 + 브랜드 산출물

**Files:**
- Create: `scripts/brand/ecom-logo-source.png`(킥오프 pptx `ppt/media/image1.png` 복사), `scripts/brand/trace_logo.py`, `scripts/brand/build_icons.mjs`, `scripts/brand/check_logo.mjs`
- Create: `app/public/brand/ecom-mark.svg`, `ecom-word.svg`, `ecom-logo.svg`, `app/public/favicon.svg`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png`, `badge-96.png`, `og-cover.png`
- Modify: 루트 `og-cover.png`(옛 화면 공유 그림, 1200×630 새 그림으로 덮기)

**Interfaces:**
- Produces: SVG 3종은 `viewBox` 만 있고 `width/height` 없음, 모든 도형 `fill="currentColor"`(색은 쓰는 쪽이 정함). `ecom-mark.svg` = 마크만, `ecom-word.svg` = 「ECOM」 글자만, `ecom-logo.svg` = 마크 + ECOM + 영문 두 줄. 원본 소스: ECOM 킥오프 자료(pptx) 안 `ppt/media/image1.png`(500×500 투명, 로고 영역 bbox (61,159)-(442,307), 마크 = 로고 영역 왼쪽 x<102, 글자 = x≥129, 「ECOM」 = 글자 영역 y<64).

- [ ] **Step 1:** `trace_logo.py` — 원본 알파를 4배 확대(LANCZOS) → 임계 128 → potrace 로 추적(`pip install --target .omc/tmp/pylib potracer`, 저장소에 넣지 않음) → 세 SVG 저장. 글꼴로 대체하지 말 것(윤곽만).
- [ ] **Step 2:** `check_logo.mjs` — Playwright 로 각 SVG 를 원본 해당 영역 크기로 렌더(검정 채움) → 원본 알파(>128)와 픽셀 비교, 불일치 비율 출력. 실행: `node scripts/brand/check_logo.mjs` → 기대 `mark <1% · word <1% · logo <1%`, 하나라도 1% 이상이면 exit 1.
- [ ] **Step 3:** `build_icons.mjs` — Playwright 로 렌더: `favicon.svg`(마크, fill `#006F3A` 고정 사본) · `icon-192/512.png`(진초록 `#005034` 둥근 타일 radius 22% + 흰 마크 56%) · `icon-maskable-512.png`(전면 `#005034` + 흰 마크 44%, 안전 영역) · `apple-touch-icon.png`(180, 모서리 없음) · `badge-96.png`(투명 + 흰 마크 단색) · `og-cover.png`(1200×630, `#005034` 바탕 + 흰 `ecom-logo` 폭 520 + 「ECOM 멤버 시장 화면 · ecom-terminal.pages.dev」 + 오른쪽 장식 타일 `#00744C`·`#B5C9BA` 2개). 루트 `og-cover.png` 도 같은 그림으로 덮는다.
- [ ] **Step 4:** 산출물 확인 — `python -I -c "from PIL import Image; …"` 로 각 PNG 크기(192·512·512·180·96·1200×630) 출력, `check_logo.mjs` 재실행 통과.
- [ ] **Step 5:** 커밋 `feat(brand): ECOM 로고 벡터화 + 아이콘·공유 그림`

### Task 2: 앱 · 옛 화면에 로고 적용

**Files:**
- Create: `app/src/components/Brand.tsx`
- Modify: `app/src/App.tsx:155,175`(머리줄 글자 → 로고), `app/src/styles/tokens.css`(브랜드 토큰), `app/public/manifest.webmanifest`, `app/index.html:8-19`, `app/public/sw.js:27`, `index.html:67-80`(옛 화면 파비콘 · og)
- Test: `app/src/components/Brand.test.ts`

**Interfaces:**
- Produces: `BrandMark({ className?: string, title?: string }): JSX.Element`, `BrandWord(...)`, `BrandLogo({ tagline?: boolean, className? })` — Task 1 SVG 의 path 를 인라인(`fill="currentColor"`), 색은 클래스 `text-brand-logo`(토큰 `--c-brand-logo`: 밝음 `#006F3A` · 어둠 `#FFFFFF`). 토큰 `--c-brand: #005034`(밝음 · 어둠 같음, 입장 화면 판).

- [ ] **Step 1: 시험** — `Brand.test.ts`: `renderToStaticMarkup(<BrandLogo tagline />)` 에 `fill="currentColor"` 포함 · `aria-label="ECOM"` 1개 · 하드코딩 hex 없음(`/#[0-9a-f]{6}/i` 불일치). `BrandMark` 도 같은 검사.
- [ ] **Step 2:** 실패 확인 `npm test --prefix app` → `Cannot find module`.
- [ ] **Step 3:** 구현 — `Brand.tsx`, `tokens.css` 에 두 토큰(밝음 · 어둠 두 블록 모두), 머리줄 `<Link>` 안을 `<BrandMark className="h-[22px] w-auto"/><BrandWord className="h-[15px] w-auto"/>` 로(PC · 모바일), manifest `name/short_name "ECOM"`, `background_color/theme_color "#005034"`, icons = 192 any · 512 any · 512 maskable. `app/index.html`: favicon `favicon.svg`, apple-touch `apple-touch-icon.png`, `og:image` `https://ecom-terminal.pages.dev/og-cover.png`, `og:url` 추가. `sw.js`: `icon:'icon-192.png', badge:'badge-96.png'`. 옛 `index.html`: 📈 파비콘 → 마크 SVG data URI, og:image · canonical 새 주소.
- [ ] **Step 4:** `npm test --prefix app` 전부 통과 + `npm run build --prefix app` 성공.
- [ ] **Step 5:** 커밋 `feat(brand): 머리줄·아이콘·공유 미리보기에 ECOM 로고`

### Task 3: 링크 주소 단일 원천 + 넘김 장치 + 옛 주소 안내 띠

**Files:**
- Create: `scripts/app_url.py`, `scripts/tests/test_app_url.py`, `cloudflare-pages/_worker.js`, `cloudflare-pages/test_proxy.mjs`, `cloudflare-pages/README.md`, `app/src/components/MovedBanner.tsx`, `app/src/components/MovedBanner.test.ts`
- Modify: `scripts/alerts_v2/deliver.py:24`, `scripts/check_alerts.py:500,540,778,1426`, `scripts/build_go_page.py:32`(→ `go.html` 재생성), `scripts/notify_discord.py:134`, `scripts/send_kakao_digest.py:64`, `scripts/check_halts.py:145,168,177`, `scripts/check_releases.py:233,239,262`, `scripts/check_swings.py:200,218`, `scripts/check_mer_thresholds.py:198,203`, `cloudflare-worker/worker.js:97-99`(ALLOWED_ORIGINS) · `:1749,1797,1826`(디스코드 링크), `scripts/collect_site.mjs:37-42`(FORBIDDEN 에 `cloudflare-pages/`), `app/src/App.tsx`(배너 자리 = 정지 배너 182 위), 관련 시험의 주소 기대값(`scripts/tests/test_v2_subscribe.py`·`test_card_links.py` 등)
- Test: `scripts/tests/test_app_url.py`, `cloudflare-pages/test_proxy.mjs`, `MovedBanner.test.ts`

**Interfaces:**
- Produces (Python): `scripts/app_url.py` — `APP_URL: str = os.environ.get("APP_URL") or "https://ecom-terminal.pages.dev/"`, `OLD_URL = "https://0101-commits.github.io/economic-site/"`, `def app_link(query: str = "") -> str`(`app_link("?p=market")` → `"https://ecom-terminal.pages.dev/?p=market"`).
- Produces (Worker): 상수 `APP_URL = 'https://ecom-terminal.pages.dev/'`, `ALLOWED_ORIGINS = {'https://0101-commits.github.io','https://ecom-terminal.pages.dev'}`.
- Produces (Pages): `_worker.js` default export `fetch(request)` — `ORIGIN = 'https://0101-commits.github.io/economic-site'`.
- Produces (앱): `MovedBanner()` — `location.hostname === '0101-commits.github.io'` 일 때만 렌더, 「주소가 ecom-terminal.pages.dev 로 바뀌었습니다. 이 기기에만 있던 기록은 옮겨 가야 합니다.」 + [새 주소로](`https://ecom-terminal.pages.dev/` + 현재 `location.hash`) + [기록 옮기는 법](`#/settings`, 「내 데이터 내려받기 → 새 주소에서 올리기」 안내 펼침). 닫기 없음.

- [ ] **Step 1: 시험**
  - `test_app_url.py::test_app_link` — `app_link("?p=market") == "https://ecom-terminal.pages.dev/?p=market"`, `APP_URL` env 덮기 동작.
  - `test_app_url.py::test_no_hardcoded_old_url` — `scripts/**/*.py`, `cloudflare-worker/worker.js`, `index.html`, `go.html`, `app/index.html`, `app/src/**/*.ts(x)` 에서 `0101-commits.github.io` 를 찾되 허용 목록(`scripts/app_url.py` · `cloudflare-worker/worker.js` 의 `ALLOWED_ORIGINS` 줄 · `app/src/components/MovedBanner.tsx` · `cloudflare-pages/_worker.js` · `scripts/check_links.py` · `scripts/tests/`)만 남아야 함.
  - `test_proxy.mjs` — 전역 `fetch` 대체로: `GET /` → 원본 `…/economic-site/` 요청 · `GET /data.json?v=1` → `…/economic-site/data.json?v=1` · 원본 301 `Location: https://0101-commits.github.io/economic-site/next/` → 응답 `Location: /next/` · `POST /` → 405 · 응답에 `X-Robots-Tag: noindex`.
  - `MovedBanner.test.ts` — hostname 옛 주소면 문구 · 링크 href 에 해시 유지, 새 주소면 `null`.
- [ ] **Step 2:** 실패 확인(`python -m pytest scripts/tests/test_app_url.py -q`, `node cloudflare-pages/test_proxy.mjs`, `npm test --prefix app`).
- [ ] **Step 3:** 구현. 넘김 장치: GET/HEAD 만, 요청 머리는 `accept`·`accept-language`·`if-none-match`·`if-modified-since` 만 전달, `redirect:'manual'`, 응답 머리 그대로 + `X-Robots-Tag: noindex`. `README.md` = 프로젝트 만들기(API `POST /accounts/{id}/pages/projects` `{name:"ecom-terminal", production_branch:"main"}` — wrangler `pages project create` 는 실패 사례 있음), 배포 `npx wrangler pages deploy cloudflare-pages --project-name ecom-terminal --branch main`(실패 시 `--force`), 되돌리기.
- [ ] **Step 4:** 통과 확인 — 위 셋 + `python -m pytest scripts/tests -q -x`(기존 전체) + Worker 시험 5종(`for f in cloudflare-worker/test_*.mjs; do node $f; done`) + `node scripts/collect_site.mjs` 자체 검사. 그 뒤 `git checkout -- mer_signals.json data.json 2>/dev/null`(시험이 봇 파일을 더럽힘).
- [ ] **Step 5:** 커밋 `feat(address): 새 주소 ecom-terminal.pages.dev — 링크 단일 원천·넘김 장치·옛 주소 안내`

# P2 사람 표(Worker)

### Task 4: `users.js` — 키 · uid · 사람 표 · 해석기

**Files:**
- Create: `cloudflare-worker/users.js`, `cloudflare-worker/test_users.mjs`

**Interfaces:**
- Produces:
  - `ENTRY_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'`
  - `normalizeEntryKey(raw: string): string` — `raw` 에서 공백 · 하이픈을 빼고 대문자화한 결과가 `/^ECOM[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{12}$/` 이면 `ECOM-XXXX-XXXX-XXXX`, 아니면 `raw.trim()`
  - `newEntryKey(): string`(crypto.getRandomValues, 편향 없는 거절 표본), `newUid(): string`(`[a-z0-9]{12}`)
  - KV 이름: `user:<uid>` = `{uid,name,role,status,keyHash,backupKeyHash?,createdAt,lastSeenDay,aiDay,aiCount}`, `ukey:<keyHash>` = `uid`, `users:index` = `[uid,…]`
  - `async resolveUser(env, keyHash, legacyHash): Promise<{user}|{status:number,error:string}>` — `users:index` 없으면 **legacy**: `keyHash === legacyHash` 일 때 `{user:{uid:keyHash.slice(0,16), role:'owner', status:'active', name:'마스터', legacy:true}}`; 있으면 `ukey:` → `user:` → `status==='paused'` 면 `{status:403,error:'paused'}`, 없으면 `{status:401,error:'unauthorized'}`. `viaBackup: keyHash === user.backupKeyHash`. 60초 메모리 캐시, `_clearUserCache()` 내보냄.
  - `async createUser(env, {name, role='member'}): Promise<{user, key}>`, `listUsers(env)`, `patchUser(env, uid, {name?, status?})`, `rekeyUser(env, uid): Promise<{key}>`, `deleteUser(env, uid)`(사람 + `ukey:` + `prefs:`/`push:`/`hold:`/`fired:` 칸; role owner 는 거절), `issueBackupKey(env, ownerUid): Promise<{key}>`, `touchSeen(env, user, kstDay)`(값이 다를 때만 쓰기)
  - `async migrateOwner(env, legacyHash): Promise<{uid, created:boolean}>` — 멱등. 처음: owner 생성(keyHash = legacyHash) + `prefs:<h16>`→`prefs:<uid>` · `push:<h16>`→`push:<uid>` · `portfolio:encHoldings`→`hold:<uid>` · 최근 30일 `portfolio:encHoldings:prev:<날짜>`→`hold:<uid>:prev:<날짜>` **복사**(옛 칸 유지). 두 번째부터 `{created:false}` 로 아무것도 안 씀.

- [ ] **Step 1: 시험** `test_users.mjs`(test_prefs.mjs 와 같은 골격, KV 모의에 `delete` 추가):
  - `normalizeEntryKey`: `' ecom-7kq3 px9m-2hta '` → `'ECOM-7KQ3-PX9M-2HTA'` · `'My-Key 2026 Pass'` → `'My-Key 2026 Pass'` · `'ECOM-7KQ3-PX9M-2HT'`(11자) → 그대로 trim · `'ECOM-OKQ3-PX9M-2HTA'`(O 포함) → 그대로 trim
  - `newEntryKey()` 1,000개: 전부 `normalizeEntryKey(k) === k`, 형식 정규식 통과, 중복 0
  - legacy: 사람 표 없음 + 맞는 해시 → `user.legacy === true`, `uid === hash.slice(0,16)`; 틀린 해시 → 401
  - `migrateOwner` 두 번 → 두 번째 `created:false`, KV 쓰기 횟수 0; 옛 칸 내용이 새 칸과 같음
  - `createUser` → 키로 `resolveUser` 성공 role member; `patchUser status:'paused'` → 403 `paused`(캐시 비운 뒤); `rekeyUser` → 옛 키 401 · 새 키 성공; `deleteUser` → 401 + 칸 4종 없음; owner `deleteUser` → 거절
  - `issueBackupKey` → 예비 키로 owner 해석 + `viaBackup:true`
- [ ] **Step 2:** `node cloudflare-worker/test_users.mjs` → 실패(모듈 없음).
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** `node cloudflare-worker/test_users.mjs` → `전부 통과`.
- [ ] **Step 5:** 커밋 `feat(worker): 사람 표 — 입장 키·uid·해석기·마이그레이션`

### Task 5: Worker 인증을 사람 표로 + 공간 = uid

**Files:**
- Modify: `cloudflare-worker/worker.js` — `_verifySyncKey`(863), `_userKvKey`(1173-1179), `handlePortfolioGet/Post`(813, 919 — KV 키 `hold:<uid>`, legacy 면 기존 `ENC_HOLDINGS_KV_KEY`), `handleSyncKey`(890 — migrated 면 `ukey:` 교체 + `user.keyHash` 갱신, 정규화 적용), `handleAiSummary`(424 — 멤버 하루 30회, 넘으면 429 `{error:'ai_quota'}`), `POST_CORS` 메서드에 `PATCH`
- Create: `cloudflare-worker/test_members.mjs`

**Interfaces:**
- Consumes: Task 4 전부.
- Produces: 내부 `async _authUser(request, env, keyHashFromBodyOrHeader): Promise<{user}|{resp: Response}>` — 모든 인증 경로가 이것만 부른다. 공간 이름 `_space(user) = user.legacy ? user.uid /*hash16*/ : user.uid`.
- 기존 시험 5종은 **수정 없이** 통과해야 한다(사람 표 없음 = legacy).

- [ ] **Step 1: 시험** `test_members.mjs`: 사람 표 없이 기존 키로 `GET /prefs`·`POST /portfolio`·`GET /portfolio` 가 `prefs:<h16>`·`portfolio:encHoldings` 를 씀(legacy) → `migrateOwner` 후 같은 키가 `prefs:<uid>`·`hold:<uid>` 를 씀 → 멤버 A·B 만들어 A 의 `PUT /prefs` 가 B 의 `GET /prefs` 에 안 보임 → 멈춘 B 403 → 멤버 `/ai` 31번째 429 `ai_quota`(AI 호출은 `env.AI` 모의) · 마스터 31번째 통과 → 멤버 `/sync-key` 키 바꾸기 후 새 키로 같은 prefs.
- [ ] **Step 2:** 실패 확인.
- [ ] **Step 3:** 구현. 접속일 `touchSeen` 은 인증 성공 때 `ctx.waitUntil` 로.
- [ ] **Step 4:** `node cloudflare-worker/test_members.mjs` + 기존 5종 + `test_users.mjs` 전부 통과, `node --check cloudflare-worker/worker.js`.
- [ ] **Step 5:** 커밋 `feat(worker): 인증을 사람 표로 — 공간=uid, 멤버 AI 하루 30회`

### Task 6: 새 경로 — `/me` · `/admin/*` · CI 복수 읽기 · `/fired`

**Files:**
- Modify: `cloudflare-worker/worker.js` 라우터(OPTIONS 경로 목록 1923-1924, 사용자 자료 블록 1929-1940, POST 블록 1945-1976, 405 줄 1977 **앞**), `cloudflare-worker/README.md`(새 경로 표 · 예비 키도 잃었을 때 `wrangler kv key put` 절차)
- Test: `cloudflare-worker/test_members.mjs`(확장)

**Interfaces:**
- Produces(HTTP, 모두 JSON):
  - `GET /me` (키 해시 머리) → `{uid,name,role,viaBackup}`
  - `GET /admin/users` → `{users:[{uid,name,role,status,lastSeenDay,pushCount}]}`(키 해시 없음), `POST /admin/users {name}` → `{user,key}`, `PATCH /admin/users/<uid> {name?,status?}`, `POST /admin/users/<uid>/rekey` → `{key}`, `DELETE /admin/users/<uid>`, `POST /admin/backup-key` → `{key}` — 전부 role owner 만(아니면 403 `owner_only`), 이름 1~20자
  - `POST /admin/migrate` — 머리 `X-Push-Read-Key` + 바디 `keyHash`(legacy 키) 둘 다 → `migrateOwner` 결과
  - `GET /prefs/all` · `GET /push/subscriptions/all` (`X-Push-Read-Key`) → `{users:[{uid,role,prefs}]}` · `{users:[{uid,role,quiet,subs}]}`(active 만); `PUT /push/prune {uid, endpoints}`; 단수 `/prefs`·`/push/subscriptions` 는 **마스터 칸 고정**
  - `POST /fired {uid, item}` (머리 `X-Push-Write-Key` = 새 시크릿 `PUSH_WRITE_KEY`) → `fired:<uid>` 앞에 넣고 50건 유지; `GET /fired` (키 해시) → `{items}`

- [ ] **Step 1: 시험** — 멤버가 `/admin/users` → 403 `owner_only` · 마스터 생성 응답에만 `key` · 목록에 `keyHash` 문자열 없음 · `/admin/migrate` 머리 하나만 → 401 · `/prefs/all` 이 멈춘 사람 제외 · `/fired` 쓰기 51번 → 50건 · 잘못된 write key 403 · OPTIONS `/admin/users/abc` → 204 + `PATCH` 허용.
- [ ] **Step 2~4:** 실패 확인 → 구현 → 전부 통과(Worker 시험 7종).
- [ ] **Step 5:** 커밋 `feat(worker): /me·멤버 관리·CI 복수 읽기·발송 기록 경로`

# P3 입장 · 관리 화면(앱)

### Task 7: 앱 키 정규화 + 계정 모듈

**Files:**
- Create: `app/src/lib/personal/entryKey.ts`, `entryKey.test.ts`, `app/src/lib/personal/account.ts`, `account.test.ts`
- Modify: `app/src/lib/personal/remote.ts:12`(`keyHash` 가 `normalizeEntryKey` 를 거침) + 관리 호출, `app/src/lib/personal/e2e.ts:84-85`(`holdKeyOf` 도)

**Interfaces:**
- Produces:
  - `normalizeEntryKey(raw: string): string` — Worker 와 같은 규칙(같은 시험 행 그대로).
  - `remote.ts`: `meGet(hash): Promise<{status:number, me?:Me}>`, `adminList(hash)`, `adminCreate(hash, name)`, `adminPatch(hash, uid, patch)`, `adminRekey(hash, uid)`, `adminDelete(hash, uid)`, `adminBackupKey(hash)`, `firedGet(hash)` — 모두 `Reply` 꼴(`{status, doc?, error?}`).
  - `account.ts`: `type Me = {uid:string, name:string, role:'owner'|'member', viaBackup:boolean}`; `readMe(): Me|null`(localStorage `econMe_v1`); `useMe(): Me|null`; `async signIn(raw: string): Promise<'ok'|'bad'|'paused'|'rate'|'offline'>` — 정규화 → 해시 → `meGet` → ok 면 `econMe_v1` 저장 + 기존 `connectSync(raw)` 호출; `async refreshMe(): Promise<void>` — 401 이면 `disableSync()` + `econMe_v1` 삭제, 403 이면 `econMe_v1.status` 만 표시용으로 남김; `signOut(): void` = `forgetDevice()` + `econMe_v1` 삭제.
- [ ] **Step 1: 시험** — `entryKey.test.ts` 는 Task 4 의 normalize 행과 같은 입력 · 기대(행 목록을 두 시험이 문자 그대로 같게). `account.test.ts` — `fetch` 모의로 200/401/403/429/네트워크 오류 → 반환값 5종, 401 에서 `econSyncHashKeep_v1` 제거 확인, 403 에서 아무 키도 안 지움. `e2e.test.ts` 기존 `holdKeyOf` 시험(공백 무시) 그대로 통과 + `holdKeyOf('ecom-7kq3-px9m-2hta') === holdKeyOf('ECOM-7KQ3-PX9M-2HTA')`.
- [ ] **Step 2~4:** 실패 → 구현 → `npm test --prefix app` 전부 통과.
- [ ] **Step 5:** 커밋 `feat(app): 입장 키 정규화·계정 모듈`

### Task 8: 입장 화면 + 키 없는 기기 막기

**Files:**
- Create: `app/src/screens/Welcome.tsx`
- Modify: `app/src/App.tsx`(라우트 `<Route path="/welcome" element={<Welcome />} />` 한 줄 추가, `Shell` 에서 키 해시 없고 경로가 `/welcome` 아니면 `<Navigate to={'/welcome?next=' + encodeURIComponent(현재 경로+검색)} replace />`, `/welcome` 에선 머리줄 · 하단 탭 숨김), `scripts/tests/test_v2_urls.py`(라우트 목록에 `/welcome`)
- Test: `app/src/screens/welcome.test.ts`(`next` 파라미터 해석 순수 함수 `safeNext(next: string|null): string` — `/`로 시작하는 앱 경로만, 그 밖은 `/`)

**Interfaces:**
- Consumes: `signIn` · `readMe`(Task 7), `BrandLogo`(Task 2).
- 문구(고정): 제목 「들어가기」, 라벨 「입장 키」, 버튼 「들어가기」, 안내 「키는 모임 운영자에게 받습니다. 한 번 들어가면 이 기기는 다음부터 바로 열립니다. 키는 기기에 저장하지 않습니다.」, 왼쪽 판 「ECOM 모임 멤버를 위한 시장 화면입니다. 자산과 관심 종목은 사람마다 따로 저장됩니다.」, 오류 bad 「키가 맞지 않습니다. 하이픈과 대소문자는 신경 쓰지 않아도 됩니다.」 · paused 「멈춘 키입니다. 모임 운영자에게 문의해 주세요.」 · rate 「시도가 많아 1분 뒤에 다시 넣을 수 있습니다.」 · offline 「연결되지 않았습니다. 잠시 뒤 다시 눌러 주세요.」, 성공 「{이름}님, 어서 오세요」 0.8초 뒤 `safeNext(next)`.
- 레이아웃: PC 2열(왼쪽 `bg-[var(--c-brand)]` 판 + 흰 `BrandLogo tagline`, 오른쪽 카드), ≤768 1열. 입력 `autocomplete="off"`, `autocapitalize="characters"`, 16px 이상(iOS 확대 방지).
- [ ] **Step 1~4:** `safeNext` 시험(`'/my'`→`'/my'`, `'https://evil.example'`→`'/'`, `'//x'`→`'/'`, `null`→`'/'`) → 구현 → `npm test --prefix app` + `python -m pytest scripts/tests/test_v2_urls.py -q` 통과.
- [ ] **Step 5:** 커밋 `feat(app): 입장 화면 — 키 없는 기기는 입장부터`

### Task 9: 사람별 기기 저장 이름 + 401/403 처리

**Files:**
- Modify: `app/src/lib/personal/store.ts:22-31,44-64,112-157`, `app/src/lib/watch.ts:6`(관심 키도 `store.ts` 의 이름 함수를 쓰게), `app/src/lib/personal/sync.ts:133`(`lost` 가 `refreshMe` 경로로), 앱 부팅(`main.tsx` — `refreshMe()` 1회)
- Test: `app/src/lib/personal/store.test.ts`(신규 또는 확장)

**Interfaces:**
- Produces: `storeKey(base: 'portfolioV1'|'pfSnapshotsV1'|'pfLedgerV1'|'econ_watch_v1'|'econPrefsV1'|'econ_scenarios_v1'): string` — 현재 사람이 role owner 거나 없으면 `base` 그대로(마스터와 옛 화면 호환), member 면 `base + ':' + uid`. 기존 `KEYS.*` 사용처는 전부 `storeKey(...)` 로.
- [ ] **Step 1: 시험** — 마스터로 `writePortfolio(A)` → 멤버 X 로 바꿈 → `readPortfolio()` 빈 값 → `writePortfolio(B)` → 마스터로 바꿈 → `A` → 멤버 X → `B`. 원장 · 스냅샷 · 관심 같은 방식. `wipeDevice` 는 현재 사람 이름의 키만 지움.
- [ ] **Step 2~4:** 실패 → 구현 → `npm test --prefix app` 통과.
- [ ] **Step 5:** 커밋 `feat(app): 멤버마다 기기 저장 분리`

### Task 10: 머리줄 이름 메뉴 + 설정 「내 계정」

**Files:**
- Create: `app/src/components/personal/AccountMenu.tsx`, `app/src/components/personal/MyAccount.tsx`
- Modify: `app/src/App.tsx:164-169,175-179`(오른쪽 끝 이름 동그라미), `app/src/screens/Settings.tsx:41,55`(`DeviceLink` 자리 → `MyAccount`, legacy 링크는 owner 만), `app/src/components/personal/DeviceLink.tsx`(키 바꾸기 · 보유 범위 · 폰 알림 하위 부품은 `MyAccount` 가 재사용 — 키 입력 폼은 제거)

**Interfaces:**
- Consumes: `useMe`, `signOut`(Task 7). 
- 메뉴 항목: 이름 + 「마스터」/「멤버」 · 내 계정(`#/settings`) · 멤버 관리(`#/members`, owner 만) · 이 기기에서 나가기(확인 한 단계: 「이 기기에서 나가면 입장 키를 다시 넣어야 합니다. 기기 안 기록은 남습니다.」).
- 종목 상세(`app/src/screens/Detail.tsx`): 수급 · 「왜 움직였나」 자료가 그 종목에 없으면 칸을 숨기는 대신 「수집 대상이 아닌 종목입니다 — 시세 · 차트 · 알림은 그대로 됩니다」 한 줄(D7). 자료가 있으면 지금 그대로.
- 「내 계정」 카드: 이름 · 입장 키 바꾸기(기존 `KeyChange`) · 폰 알림(기존 `PushScope`) · 「키는 기기에 저장하지 않습니다. 보유는 내 키로 잠가 두어 운영자도 열 수 없습니다.」 · [이 기기에서 나가기]. `viaBackup` 이면 「예비 키로 들어왔습니다 — 보유는 마스터 키로만 열립니다. 새 마스터 키를 만들어 주세요」 줄.
- [ ] **Step 1:** 화면 확인 스크립트 대신 기존 UI 게이트로 검증 — `tests/ui/_lib.mjs:48-55` `newCtx` 가 `econSyncHash_v1`·`econSyncHashKeep_v1`·`econMe_v1`(owner) 를 심고 `/me` 를 `route()` 로 200 응답 모의, `NEXT_PATHS`(:22)에 `#/settings` 추가.
- [ ] **Step 2:** 구현.
- [ ] **Step 3:** `npm test --prefix app` + `npm run build --prefix app` + `npm run dev --prefix app -- --host 127.0.0.1 --port 5199`(백그라운드) 후 `node tests/ui/overflow.mjs --url http://127.0.0.1:5199/next/` → 위반 0. 서버 끄기.
- [ ] **Step 4:** 커밋 `feat(app): 이름 메뉴·내 계정`

### Task 11: 멤버 관리 화면(마스터)

**Files:**
- Create: `app/src/screens/Members.tsx`
- Modify: `app/src/App.tsx`(`<Route path="/members" element={<PinGate><Members /></PinGate>} />` 한 줄), `scripts/tests/test_v2_urls.py`, `tests/ui/_lib.mjs`(`NEXT_PATHS` 에 `#/members`)

**Interfaces:**
- Consumes: `adminList/adminCreate/adminPatch/adminRekey/adminDelete/adminBackupKey`(Task 7), `useMe`.
- role member 면 「마스터만 쓸 수 있는 화면입니다」 한 줄만.
- 목록 행: 이름 · 「마스터」/「멤버」 · 상태 배지(사용 중/멈춤) · 마지막 접속(오늘/`M/D`/없음) · 폰 알림 기기 수. 행 메뉴: 이름 바꾸기 · 멈추기/다시 열기 · 키 다시 만들기 · 지우기(owner 행엔 이름 바꾸기만).
- [멤버 추가] → 이름(1~20자) → 키 카드: 키 큰 글자 · 「이 화면을 닫으면 다시 볼 수 없습니다. 잃어버리면 「키 다시 만들기」로 새 키를 줍니다.」 · [키 복사] · [카톡에 보낼 글 복사](`ECOM 시장 화면 https://ecom-terminal.pages.dev 에서 이 키로 들어오세요: {키}`). 클립보드 실패 시 키 글자 선택.
- 키 다시 만들기 확인: 「옛 키는 바로 막힙니다. 보유는 옛 키로 잠겨 있어 새 키로는 열 수 없습니다 — 옛 키가 남은 기기에서 다시 잠가 올리거나 보유를 다시 입력해야 합니다.」 · 지우기 확인: 「{이름}의 관심 · 알림 조건 · 보유 · 폰 알림이 모두 지워집니다.」
- 하단: [마스터 예비 키 만들기](이미 있으면 「다시 만들기」) — 발급 카드 문구 「마스터 키를 잃었을 때 이 키로 들어와 새 키를 만듭니다. 따로 적어 두세요.」
- [ ] **Step 1~3:** 구현 → `npm test --prefix app` · build · overflow 게이트(`#/members`, owner 모의 + `/admin/users` 모의 3행) 위반 0.
- [ ] **Step 4:** 커밋 `feat(app): 멤버 관리 화면 — 키 발급·멈춤·재발급·삭제·예비 키`

# P4 멤버 알림(파이프라인)

### Task 12: CI 읽기를 사람별로 — `prefs_client` · `subscribe`

**Files:**
- Modify: `scripts/prefs_client.py:33-60`, `scripts/alerts_v2/subscribe.py:26,35-52`
- Test: `scripts/tests/test_check_alerts_prefs.py`, `scripts/tests/test_v2_subscribe.py`(확장)

**Interfaces:**
- Produces: `prefs_client.fetch_all(base_url: str) -> list[dict] | None`(`GET /prefs/all` → `[{"uid","role","prefs"}]`), `subscribe.load_all_prefs(log=print) -> list[tuple[str, str, dict]]`(uid, role, upgrade_prefs 적용된 prefs). 기존 `fetch`·`load_prefs` 는 유지(마스터 칸).
- [ ] **Step 1~4:** 시험(HTTP 모의: 2명 응답 → 튜플 2개, 401 → None, 빈 목록 → `[]`) → 구현 → `python -m pytest scripts/tests -q -x` 통과.
- [ ] **Step 5:** 커밋 `feat(alerts): 사람별 설정 읽기`

### Task 13: 발송 상태 키 · 사람별 판정 · 공개 원장 제외

**Files:**
- Modify: `scripts/alerts_v2/run.py:64-110,137`, `scripts/alerts_v2/subscribe.py:104,135,162,276`, `scripts/alerts_v2/deliver.py`, `scripts/check_alerts.py:1176-1210`
- Test: `scripts/tests/test_v2_members.py`(신규)

**Interfaces:**
- Produces:
  - `subscribe.state_key(uid: str, role: str, cond_id: str) -> str` — owner 면 `cond_id`(지금 키 그대로), member 면 `hmac_key(uid + ":" + cond_id)`.
  - `_pipeline_b` 는 `load_all_prefs()` 의 사람마다 `user_hits → match → schedule.plan` 을 돌고, Decision 에 `uid` · `role` 을 단다. `_prefs` 정리(90-93)는 **모든 사람의 현재 상태 키 합집합** 밖만 지운다.
  - 공개 원장: role member 의 사용자 조건 행(U1 · U2 · 종목 B1)은 `ledger.append` 하지 않고 `deliver.post_fired(uid, item)`(Worker `POST /fired`, 머리 `X-Push-Write-Key`=env `PUSH_WRITE_KEY`, 실패해도 발송은 진행)로만 기록. 시장 전체 사건 행은 지금처럼.
  - 카톡: role owner 의 Decision 만(지금 경로 그대로).
  - 하루 상한 · 쿨다운: 멤버는 `state_key` 로 같은 `_prefs` 장부를 씀(값 = 지금처럼 side 한 글자 · 시각).
- [ ] **Step 1: 시험** `test_v2_members.py` — 사람 2명(owner, member) 모의 prefs: member U1 넘는 순간 → Decision uid=member, 원장 미기록, `post_fired` 1회; owner 조건 상태 키가 정리 단계 뒤에도 남음; member 가 조건을 지우면 그 member 키만 사라짐; 공개 `_prefs` 에 member 원문 조건 id 없음.
- [ ] **Step 2~4:** 실패 → 구현 → `python -m pytest scripts/tests -q -x` 통과, `git checkout -- mer_signals.json`.
- [ ] **Step 5:** 커밋 `feat(alerts): 멤버 조건 판정 — 상태 키 HMAC·공개 원장 제외`

### Task 14: 폰 알림 사람별 발송

**Files:**
- Modify: `scripts/send_push.py:37-160`, 푸시 큐 항목에 `uid`(Task 13 의 deliver 가 넣음)
- Test: `scripts/tests/test_send_push.py`(확장)

**Interfaces:**
- Consumes: `GET /push/subscriptions/all`(Task 6), 큐 항목 `{..., "uid": str|None}`.
- 규칙: `uid` 있는 항목 → 그 사람 구독에만, 그 사람 `quiet`(조용한 시간엔 `pierceQuiet` 만). `uid` 없는 항목(옛 큐 · 시장 전체) → **마스터에게만**(멤버의 시장 사건은 Task 13 이 사람별 항목으로 만든다). 만료 구독 정리는 `PUT /push/prune {uid, endpoints}` 사람별.
- [ ] **Step 1~4:** 시험(2명 구독 모의: 멤버 항목이 마스터 기기로 안 감 · 조용한 시간 사람별 · uid 없는 항목은 마스터만 · prune 이 사람별 호출) → 구현 → 통과.
- [ ] **Step 5:** 커밋 `feat(push): 사람별 폰 알림 발송`

### Task 15: 워크플로 비밀값 배선 + 문서

**Files:**
- Modify: `.github/workflows/stock-alerts.yml`·`alerts-v2.yml`·`fetch-data.yml`·`briefing.yml` 의 알림 단계 env 에 `PUSH_WRITE_KEY: ${{ secrets.PUSH_WRITE_KEY }}`, `CLAUDE.md`(「멤버 · 입장 키」 절: 사람 표 KV 이름 · 해석기 하나 · 공개 파일 금지 · 마스터 예비 키 · 새 주소 넘김 장치 · `scripts/app_url.py` 단일 원천), `docs/ALERTS_V2.md`(사람별 발송)
- [ ] **Step 1:** `python -m pytest scripts/tests/test_watchdog.py -q`(워크플로 이름 보호) 통과 확인.
- [ ] **Step 2:** 커밋 `chore: 멤버 알림 비밀값 배선·문서`

---

## 배포(컨트롤러가 직접, 사용자 승인 뒤 — 코드 작업 아님)

순서대로, 각 줄의 확인이 통과해야 다음 줄:
1. **사용자**: 카카오 개발자 콘솔 「사이트 도메인」에 `https://ecom-terminal.pages.dev` 추가 — **합치기 전**(합치는 순간 카톡 링크가 새 주소로 바뀐다). 네이버 클라우드 콘솔에 같은 도메인 등록(옛 화면 지도).
2. Pages 프로젝트 `ecom-terminal` 생성 + `cloudflare-pages/` 배포 + 확인(`https://ecom-terminal.pages.dev/` 200, `data.json` `lastUpdated` 가 옛 주소와 같음) — **합치기 전**.
3. `main` 을 브랜치에 병합 → 전 시험 → PR → 병합(봇 데이터 커밋과 겹치는 파일 없음 확인). Worker(Workers Builds) · Pages 배포가 끝날 때까지 기다린다. 마스터 키로 `/me` = legacy owner 확인.
4. 시크릿 `PUSH_WRITE_KEY` 생성(값 미출력) → Worker(`wrangler secret put`) + GitHub(`gh secret set --body`).
5. **조용한 창에서 이전**: 장 마감 뒤, 마스터 기기의 화면을 모두 닫고 `POST /admin/migrate` 1회 → 응답 `created:true` → 2분 기다림 → 다시 1회 `created:false` → 새 주소에서 마스터 키로 입장 · 보유 · 관심 확인.
6. 마스터 예비 키 발급(종이에 적어 보관) + 시험 멤버 1명으로 칸 분리 · 폰 알림 · 받은 알림 확인 → 시험 멤버 삭제. 멤버 초대는 **한 명씩**(같은 와이파이에서 동시에 넣으면 IP 당 분당 10회 제한에 걸린다).
7. 사용자 안내: 기기마다 「내 데이터 내려받기 → 새 주소에서 올리기」, PIN · 폰 알림 · 홈 화면 아이콘 다시. 옛 주소에서 받은 폰 알림을 누르면 앱 첫 화면이 열린다(새 주소에서 폰 알림을 다시 켜면 해결).

**되돌리기**: 이전(5) 뒤에 Worker 를 되돌리면 옛 칸(`prefs:<hash16>` · `push:<hash16>` · `portfolio:encHoldings`)이 이전 시점 값으로 보인다 — 이전 뒤 되돌리기는 사람 표를 지우지 말고 앞으로 고쳐 나간다. 옛 칸은 저절로 만료되지 않는다(필요하면 손으로 지운다).

**후속**: P4 실발송 확인 뒤 단수 CI 경로(`GET /prefs` · `GET /push/subscriptions` 마스터 고정) 정리 · 새 주소 요청 수 2주 실측.
