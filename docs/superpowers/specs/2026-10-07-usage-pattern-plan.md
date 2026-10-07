# ecom 사용 패턴 개선 — 구현 명세 (P0 · P1 · P2)

기획서: 아티팩트 https://claude.ai/artifact/TBPsrbBrajDwT2ioDTKy9a (v2.0, 2026-10-07). 이 문서는 그 기획서에서 구현에 필요한 것만 옮긴 계약서다. 줄 번호는 2026-10-07 main 기준 실측.

결정(전부 2026-10-07 사용자 확정): D1~D8 · D10 · D12~D14 = 권고안 (a). **D9 = (a) 보유도 동기화 키 하나로**(옛 화면 보유 동기화는 끊김 — 사용자 승인). **D11 = 보류**(관심 목록 `alerts_config.json` 공개 유지 — 수집기 5곳이 읽음). P3(측정 2주 뒤)는 이번 범위 밖.

배포: 단계마다 브랜치 → PR → 테스트 · UI 게이트 통과 → 병합(운영 배포).

공통 규칙
- 화면 글은 우리말. 파일 · 함수 · 키 이름만 원문. 이모지 금지.
- 새 저장 키는 `econ…_v1` 꼴, 모든 localStorage 읽기 · 쓰기는 try/catch.
- 새 수집 0건. 화면이 쓰는 값은 `bundles/*.json` 또는 이미 있는 루트 json 에서만.
- 앱 검사: `npm test --prefix app` · `npm run build --prefix app`. UI 게이트: `node tests/ui/overflow.mjs`(새 화면 층 5173, `_lib.mjs` NEXT_PATHS). 파이썬: `python -m pytest scripts/tests/<파일>`(Windows 는 `PYTHONIOENCODING=utf-8`, 테스트가 `mer_signals.json` 을 더럽히면 `git checkout -- mer_signals.json`).

---

## P0 (1주) — 펼침 · 띠 · 렌즈 자리 · 알림 주소 · 잘림 · 설정 관문 · 보안 넷

### I1 접힘 → 펼침 기본 · 접기 기억 · 「더 보기」
- `app/src/components/panels.tsx:17-54` `Panel`: `fold` 기본을 **펼침**으로(PC · 모바일 같음). 사용자가 접으면 `localStorage econ_fold_v1` = `{ "<화면>:<패널 제목>": true }` 에 기억, 펼치면 지움. 처음 그릴 때 한 번만 폭을 보던 것(`:30` `useState(() => matchMedia…)`) 삭제 — 폭이 바뀌어도 상태는 기억값이 정한다.
  - `fold` 속성은 남겨 「접을 수 있음」만 뜻하게(접기 단추 표시). `'always'` · `'mobile'` 값의 차이는 없앤다.
- 「더 보기」 부품 신설: 행이 많은 표 · 목록은 모바일(<980) 5행 · PC 10행까지, 끝에 「N행 더 보기」 단추 — 누르면 그 자리에서 전부. `RankTable`(panels.tsx) 과 거래대금 목록 등 긴 목록에 적용.
- 각 화면의 `fold=` 인자: Home.tsx(투자자 매매 · 일정·알림 · 뉴스) · market/Domestic.tsx(`:143-149` 보기 패널들 · 배당·실적) · Global · FxRates · Commodities · Flows · RealEstate · Macro — 접힘 시작이 없어지므로 인자는 「접을 수 있음」으로만 남기거나 지운다.
- 게이트: 첫 그림에서 접힌 패널 0개(390 · 1440, NEXT_PATHS 전부).

### I2 홈 「띠 보기」 삭제 → 관심이 띠에 붙는다
- `app/src/screens/Home.tsx:18-24` `VIEWS` · 보기 줄(`:169` 부근) · viewStrip 삭제. 띠는 「전체」 8장 고정.
- 별표한 지표 · 종목(`lib/watch.ts` `useWatch`)이 띠 9번째 칸부터 붙는다. 카드 이름 옆 「관심」 알약. 모바일 2열이라 짝수 맞춤 불필요(빈 칸 두지 않음). 최대 8장, 넘으면 「관심 N개 더」 링크(검색 오버레이 또는 알림 › 사건 내 조건으로 — 간단한 쪽).
- 「관심」 패널 삭제(`:185-215` 부근). 그 자리를 「업종」이 PC 6칸(`sp6`)으로. 관심이 0개면 띠 8장 그대로 · 빈 안내 문장 없음.
- PC 격자: 1줄 큰 차트 6 + 업종 6 → 2줄 거래대금 4 + 투자자 매매 4 + 일정·알림 4 → 3줄 렌즈 오늘 8 + 뉴스 4.
- 띠 카드를 누르면 큰 차트가 바뀌는 규칙은 그대로.

### I3(앞부분) 시장 7화면 끝 「렌즈」 패널 삭제
- `app/src/components/market/parts.tsx:109-111` `MarketGrid` 끝의 렌즈 패널 세 줄 삭제. (지표 상세 렌즈 한 줄은 P1.)

### I6 알림 주소 2건 · 39건 전수 게이트
- `scripts/alerts_v2/events.yml:367` `url: "#/home"` → `"#/"`.
- `events.yml:125` · `:479` `#/lens?m=chain&c={…}` → `#/lens?m=chain&s={…}`(ChainView.tsx:15 가 `s` 를 읽는다).
- 신설 `scripts/tests/test_v2_urls.py`: 사전의 모든 사건 url 을 앱 경로표(`app/src/App.tsx` `<Route path=…>`)와 각 화면의 주소 변수 이름(`useViewParam('<키>'`)에 대조. 없는 경로 · 그 화면이 읽지 않는 변수면 실패. 틀 변수(`{…}`)는 값 대신 이름만 본다. `export_dict.py` 로 `app/src/lib/alerts/dict.json` 갱신이 필요하면 다시 내보내고 `test_v2_parity.py` 통과.

### I7 1440 국내 상승 · 하락 표 잘림
- `market/Domestic.tsx` 상승 · 하락 표 열을 종목 · 현재가 · 등락률 · 거래량 4개로. 범위가 「전체」일 때만 「시장」 열. 거래량은 「만주」 단위로 4자리 안(`:68-69` 부근 포맷).
- `tests/ui/overflow.mjs`(`_lib.mjs`) 가 보기 기본값만이 아니라 `?v=gainers` · `?v=losers` 경로(PC 둘째 줄 4칸 자리)도 찍도록 NEXT_PATHS 에 추가.

### S1 설정 PIN 관문 (D7 = 설정 화면 전체)
- `app/src/App.tsx:131` `/settings` 를 `PinGate` 로 감싼다. PIN 없는 기기는 설정 · 내 자산 어느 쪽을 먼저 열든 「이 기기 PIN 정하기」.
- 화면 모드(밝게 · 어둡게)만은 PIN 없이: 머리 톱니 옆에 화면 모드 아이콘 단추 하나(누르면 기기 설정 → 밝게 → 어둡게 순환). `lib/theme.ts` `applyTheme` 재사용.
- `PinGate` 머리 문구: 「잠긴 화면 · 설정과 내 자산은 이 기기 PIN 으로 엽니다」.

### S6 PIN 잊음 (새 화면 안에)
- `components/PinGate.tsx:116-120` 옛 화면 링크 → 「PIN 잊음」 단추: 동기화 키 입력 → `POST /sync-key`(본문에 키 해시만, `newKeyHash` 없음 = 검사만, worker.js:800-817) 200 이면 `econLockPin_v2` 지우고 「정하기」로. 키가 없거나 401 이면 「동기화 키가 없으면 이 기기 데이터를 지운 뒤 새로 정해야 합니다」 + 그 자리에서 「이 기기 데이터 지우기」(확인 2번, `store.ts wipeDevice`).
- 새 PIN 은 숫자 6자리만(옛 화면 4자 규칙 비켜 가기 차단).

### S4 · D10 자동 이어 가기
- `lib/personal/sync.ts:174-178` `startSync`: 기억 해시(`econSyncHashKeep_v1`)가 있으면 PIN 없이 이 탭 해시로 옮겨 잇는다(`isUnlocked()` 조건 삭제).
- `enableSync`(설정, 이제 PIN 뒤에서만 불린다)가 성공하면 **기억을 기본으로 켠다**(`rememberKey(true)` — PIN 이 열려 있으니 바로 된다). 끄기는 S2 의 「이 기기 잊기」.
- 알림 › 채널 `KeepBox`(Alerts.tsx:664-708)의 「이어 가기」 PIN 입력은 더 필요 없다 — P1 에서 패널째 설정으로 옮기므로 P0 에서는 이어 가기 PIN 요구만 뺀다.

### B3 옛 화면 비밀 저장 끊기
- `js/app2.js:1236,1269` `pfSyncKeyHash` · `:1565,1609` `pfHoldingsPass` 를 localStorage 에 쓰지 않는다 — sessionStorage 로(탭을 닫으면 사라짐). 읽을 때 남아 있는 옛 localStorage 값은 한 번 지운다. `js/app2.min.js` 는 build-frontend.yml 이 만든다(손대지 말고 워크플로에 맡김 — 확인).
- D9 영향(P1 에서): 옛 화면의 보유 동기화 단추는 「보유 동기화는 새 화면 설정에서 합니다」 안내로 바꾼다 — P1 에서 함께.

### B4 지우기 보강
- `store.ts:104` `WIPE_KEYS` 에 `pfHoldingsPass` · `pfSyncKeyHash` · `econ_scenarios_v1` · `econAlertsSeen_v1` · `econ_fav_v1` · `econ_fold_v1` 추가. 지우기 때 푸시 구독도 해지(`lib/push.ts unsubscribePush`, 실패해도 계속).
- 지우기는 설정이 PIN 뒤로 가면서 자동으로 PIN 뒤(S1).

### B7 PIN 실패 대기
- `lib/pin.ts`: 실패 횟수 `localStorage econLockFail_v1 = { n, until }`. 5회 실패 → 30초, 10회 → 5분, 이후 실패마다 5분. 대기 중엔 입력 막고 「N초 뒤 다시」. 맞으면 초기화. `pin.ts` 단위 테스트.

### B1 (확인만)
- 코드 변경 없음. 기획서 6장 B1: git 기록의 옛 PIN · 옛 보유 암호를 다시 쓰지 말 것. D9(a) 이전 때 서버 보유 덩어리가 새 열쇠로 다시 올라가므로 KV 사본 문제는 P1 에서 해소.

P0 끝 증거: 390/1440 첫 그림 접힘 0 · 알림 39 주소 게이트 통과 · `/settings` 직접 열면 PIN 창 · 새 탭에서 동기화가 저절로 이어짐 · `pfHoldingsPass` · `pfSyncKeyHash` 를 localStorage 에 쓰는 줄 0.

---

## P1 (1주) — 목차 · 거시 한 격자 · 상세 렌즈 · 사용 기록 · 기기 연결 · 보유 한 열쇠 · 채널 정리

### I4 시장 보기 줄 → 목차
- `market/parts.tsx:100-114` `arrange`(고른 패널을 둘째 자리로 옮기고 나머지 접기) 삭제. 보기 줄을 **목차**로: 누르면 그 패널로 부드럽게 내려가고, 화면에 보이는 패널의 칩이 테두리로 표시(IntersectionObserver), 화면 위에 붙음(sticky, `top: env(safe-area-inset-top,0)`+머리 높이).
- 주소 `v=` 는 그대로: `#/market?a=kr&v=gainers` 로 오면 「상승」 패널로 내려간다.
- 범위 줄(코스피 · 전체 · 코스닥 · ETF)과 거시 · 부동산의 「지표」 줄은 패널 내용을 바꾸므로 그대로.

### I5 거시 나라 칩 삭제 → 주제 한 격자
- `market/Macro.tsx:22-25` COUNTRIES · `:59-70` 나라 줄 삭제. 고른 주제의 카드를 모든 나라 한 격자에, 카드마다 나라 꼬리표(알약), 한국 · 미국 먼저 그다음 유로 · 영국 · 독일 · 일본 · 중국. 패널 머리 「물가 · 나라 7 · 지표 9」(묶음에서 센다). 「{나라}의 이 주제 지표가 묶음에 없습니다」 문장 삭제. 경제 일정은 나라 꼬리표.
- 묶음 실측(2026-10-07): 6주제 × 7나라 = 42칸 중 빈 칸 13, 지표 66.

### I3(뒷부분) 지표 상세 「렌즈」 한 줄
- `screens/Detail.tsx:88-94` 뒤에 「렌즈」 패널 — 그 지표가 렌즈 지표 48개에 들 때만(`components/personal/BellSheet.tsx:33` 판정 재사용): 상태 알약(돌파 · 주시 · 정상) · 기준값 · 지금 값 · 걸린 사슬 이름 · 글 수 · 「렌즈에서 보기 ›」(`#/lens?m=chain&s=…`). 48개 밖이면 패널 없음(빈 문장 없음). 흐름 차트에 기준선 점선(가능하면).

### I8 사용 기록 — 이 기기에만 2주
- 신설 `app/src/lib/usage.ts`: `localStorage econ_usage_v1` 에 횟수만 — 화면 열기(경로), 범위 · 보기 누르기(키), 패널 접기 · 펼치기(패널 키), 「더 보기」. 값 · 종목 없음, 서버 전송 없음. 시작일 기록.
- 설정 「내 사용」(접힘 패널 아님 — 「고급」 안): 화면별 연 횟수 · 많이 누른 보기 5 · 접은 패널 · 한 번도 안 연 패널 · 지우기.

### S2 · S5 설정 「기기 연결」 한 칸
- 설정 카드 순서: **기기 연결 → 보안 → 표시 → 내 데이터 → 데이터 상태(접힘) → 고급(접힘)**.
- 「기기 연결」 = 지금의 `SyncBox` + `HoldRow`(Settings.tsx:155-212) + 알림의 `PhonePush`(Alerts.tsx:560-583) + `KeepBox`(:664-708) 를 한 부품으로:
  - 연결 전: 동기화 키 입력 한 칸 + 「연결」. 연결할 때 서버에 저장본이 있으면 「서버 것으로 맞추기 / 이 기기 것을 올리기」 한 번 묻는다(지금은 서버 것이 통째로 덮음, sync.ts:116-126).
  - 연결 후: 상태 알약 「연결됨 · 13:40 맞춤」 · 키 칸은 ●●●● · 「키 바꾸기」 · 「이 기기 잊기」(= 끄기, 기억 해시 지움).
  - 범위 체크 3(기본 모두 켬): ① 관심 · 알림 조건 · 표시 · 렌즈 시나리오(「알림이 울리려면 켜져 있어야 함」) ② 보유(평단가 · 수량 · 매입 환율 — 같은 키로 잠가 올림 · 서버는 못 읽음 · 마지막 올림 시각) ③ 이 기기로 폰 알림 받기(받는 기기 N/5 — `GET /push/subscribe` 로 센다, worker.js:1141).
- 알림 › 채널 탭에서 `PhonePush` · 「동기화」 패널 · `KeepBox` 삭제. 채널 탭 = 울림 채널 · 하루 상한 · 조용한 시간 · 브리핑 · 디스코드만. 맨 위 한 줄 「폰 알림 · 동기화 키 · 받는 기기는 설정 › 기기 연결에서」.
- 범위 문구 한 벌: 알림 머리줄(Alerts.tsx:163) · 내 조건(`:305`)의 「이 기기에만 · 울리지 않음 / 서버에 올라감 / 동기화 켜짐」을 「연결됨 · 폰 알림 켜짐」 「이 기기만 — 울리지 않음」 두 문구로.

### S3 · D9(a) 보유도 같은 키로
- 연결할 때(키 원문이 손에 있을 때) 보유 열쇠 재료를 만든다: `PBKDF2-SHA256(키, salt="ecom-holdings-v1", 600000) → 32바이트`, hex 를 `localStorage econHoldKey_v1` 에 둔다(기억 해시와 같은 수명 — 「이 기기 잊기」 · 401 · 지우기 때 함께 지움). 서버는 SHA-256(키)만 알므로 이 재료를 만들 수 없다.
- 보유 덩어리 형식은 `lib/personal/e2e.ts` 그대로 두고 그 「암호」 자리에 위 hex 를 넣는다(`passProblem` 은 이 경로에선 건너뜀).
- 이전(마이그레이션): 서버 덩어리가 새 열쇠로 안 풀리면 「예전 보유 암호로 잠긴 서버 사본이 있습니다 — 예전 암호를 한 번 넣으면 새 열쇠로 다시 잠가 올립니다 / 서버 사본 버리고 이 기기 것 올리기」.
- 자동: 범위 ② 가 켜져 있으면 보유 저장 2초 뒤 자동 올림(If-Match 대신 지금처럼 「본 덩어리와 같을 때만」). 양쪽이 다 바뀌었을 때만 내 자산 「동기화」 시트가 묻는다. 시트는 비교 결과 + 「서버 것 받기 / 이 기기 것 올리기」 단추만, 암호 칸 없음.
- 키를 바꾸면(「키 바꾸기」) 새 재료로 보유를 다시 잠가 올린다.
- 옛 화면(js/app2.js) 보유 동기화 단추 → 「보유 동기화는 새 화면 설정 › 기기 연결에서 합니다」 안내(사용자 승인).

### S7 카톡 숨김
- 알림 › 채널 「카톡」 패널(Alerts.tsx:603-619) → 설정 「고급」 안으로(친구 모드 · 받는 사람). 운영에서 친구 모드를 켜기 전엔 효과가 없다는 문구 유지.

### S9 화면 모드 · 금액 단위는 이 기기
- `lib/personal/remote.ts:49` 동기화 문서에서 `theme` · `settings.unit` 제외(받을 때도 덮지 않음). 설정 「표시」 머리에 「이 기기만」 표식. 등락 색은 계속 모든 기기.

### S10 말없이 바뀌는 값 3
- 꾸러미(Alerts.tsx:293-297)를 바꿀 때 「하루 상한 6→3 · 브리핑 3→1 로 바뀝니다」 한 줄 미리보기 + 확인(같은 줄에서 「바꾸기」).
- 새 조건 폼(Alerts.tsx:450-555) 100개 검사(BellSheet.tsx:69 와 같은 문구).
- 90일 미열람 자동 강등(Alerts.tsx:136-142 · housekeeping.ts): 설정 「고급」에 끄는 스위치, 내려갈 때 받은 알림 맨 위 한 줄(지금 동작 유지).

### B5 해시만으로 못 하게
- Worker `POST /sync-key` 의 **키 바꾸기**(newKeyHash 있음)와 `POST /portfolio` 의 보유 덮어쓰기는 본문에 **키 원문** `key` 를 요구하고 서버가 SHA-256 해 비교(TLS 안). 검사만(PIN 잊음)은 해시로 그대로. 키가 바뀌면 디스코드 #시스템 통지(있는 `notify` 경로 재사용). worker.js:800-817 · 839-844.
- 앱 쪽: 키 바꾸기 · 보유 올리기 때 원문이 필요 — 연결 직후 · 키 바꾸기 화면에선 원문이 손에 있다. 자동 올림(S3)은 원문이 없으므로… → **보유 덮어쓰기에 원문 요구는 하지 않는다**(자동 올림과 충돌). 대신 덮기 전 이전 판 하나를 KV `portfolio:encHoldings:prev` 로 남긴다. 키 바꾸기만 원문 요구.
- **계약(앱 · 옛 화면 · Worker 공통)** `POST /sync-key`:
  - 검사만(PIN 잊음 등): 지금 그대로 — 헤더 `X-Sync-Key-Hash`, 본문에 `newKeyHash` · `newKey` 없음 → 200 `{ok:true}` / 401.
  - 바꾸기: 본문 `{ "currentKey": "<지금 키 원문>", "newKey": "<새 키 원문>" }`. 서버가 `SHA-256(currentKey.trim())` 을 기대 해시와 비교, `newKey.trim()` 은 12자 이상 · 지금 키와 다름 → KV `auth:syncKeyHash` = `SHA-256(newKey.trim())`. 응답 `{ok:true}` / 400 `{error:"weak_new_key"}` / 401. 바뀌면 #시스템 디스코드 한 줄(키 글자 · 해시 미기재). **옛 계약(`newKeyHash`)은 400 `{error:"use_new_key"}`** — 해시만 가진 사람이 키를 못 바꾸게.
  - 옛 화면(js/app2.js 「키 바꾸기」 1254 부근)도 새 계약으로 고친다.

### B6 CI 가 동기화 키를 갖지 않게
- Worker: `GET /prefs` 가 헤더 `X-Push-Read-Key`(시크릿 `PUSH_READ_KEY`, 발송기 읽기 키 — 새 시크릿 만들지 않고 재사용)도 받아, 지금 유효한 동기화 키 공간(`_expectedSyncKeyHash` → `prefs:<앞16자>`)의 문서를 읽기 전용으로 돌려준다. 쓰기는 여전히 동기화 키만.
- `scripts/prefs_client.py` · `scripts/alerts_v2/subscribe.py`: `PUSH_READ_KEY` 가 있으면 그것으로 읽고, 없을 때만 `ALERTS_SYNC_KEY`(전환기 호환).
- 워크플로 4개(alerts-v2.yml:114 · briefing.yml:145 · fetch-data.yml:432 · stock-alerts.yml:143,174)에서 `ALERTS_SYNC_KEY` 줄 삭제, `PUSH_READ_KEY` 가 없는 잡엔 추가. GitHub 시크릿 `ALERTS_SYNC_KEY` 자체는 지우지 않는다(사용자 몫).
- `check_alerts.py:42,46` 주석 갱신.

### B13
- 동기화 키 입력칸 `autocomplete="new-password"`(키 바꾸기 · 연결), PIN 칸은 `autocomplete="off"` 유지.

P1 끝 증거: 빈 브라우저 → 연결됨 · 폰 알림 켜짐 · 보유 받음까지 입력 3(PIN 2 · 키 1) · `type=password` 칸이 PIN · 키뿐 · 워크플로에 `ALERTS_SYNC_KEY` 참조 0 · 꾸러미 바꿀 때 미리보기.

---

## P2 (1주) — 백업 올리기 · 살아 있는데 안 읽던 자료

### S8 내 데이터 올리기 · 지우기 · 내려받기 출처
- 설정 「내 데이터」: 「내려받기」(PIN 뒤라 5분 조건 삭제) 파일의 `scenarios` 출처를 `econ_scenarios_v1`(WhatIf.tsx:25)로. 「올리기」: 파일 고르기 → 미리보기(보유 N종목 · 원장 N · 스냅샷 N · 관심 N · 조건 N) → 「이 기기를 이 파일로 덮기」(확인 1번). 내려받기 선택 「PIN 으로 잠근 파일」(e2e.ts 형식, 암호 = PIN) — 올리기 때 PIN 묻기.

### C1 뉴스
- `scripts/build_bundles.py`: `data.json.news` 16주제를 묶음에 — 지표 상세용은 레지스트리 행의 `news` 키로 3건(`registry` 또는 각 market 묶음 `news`), 자산군 화면용은 주제 5건.
- 지표 상세(Detail.tsx) 「관련 뉴스」 3줄(제목 · 출처 · 시각, 링크). 시장 7화면 끝(I3 로 비운 자리) 「뉴스 · {주제}」 5건 + 「더 보기」.

### C2 AI 3줄 + 질문
- 홈 오늘 한 줄(todayLine) 아래 `aiBriefing.lines` 3줄(묶음 home 에 없으면 추가). 질문칸은 연결된 기기에만(`POST /ai`, 헤더 X-Sync-Key-Hash, worker.js:354) — 답은 그 자리에 「참고용 · 투자 조언 아님」.

### C3 분위기 5칸
- 홈 띠 아래 「분위기」 한 줄 5칸: F&G · VIX · V-KOSPI · MOVE · HY 스프레드(값 · 전주 대비). 해외 「공포·변동성」 패널에 V-KOSPI · HY 합류. 출처 `data.json.sentiment` · `economicIndicators.us.hy_spread`.

### C4 체결 Top20 · LME 재고 · 종목 수급 3열
- 국내 보기 「체결 Top20」(`rankingsKr.tossAmount`) — 국내 보기 12개가 된다(목차에도).
- 원자재 「LME 재고」 패널(묶음 `market-commodities.views.lme` 에 이미 있음 — 부품만).
- 종목 수급(`stockFlows.items[].short/lending/program`)을 묶음에 싣고, 종목 상세가 생기면 쓴다 — 지금은 수급 화면 「종목별」 표에 공매도 · 대차 · 프로그램 세 열(있는 종목만).

### C5 달력 격자
- 거시 「달력」 보기: 월 격자(7열, 날짜 칸에 건수 · 별 3 점) + 목록에 이전 · 예측 · 실제 열(묶음 calendar 의 `prev` · `fore` · `act` · `beat`). 나라 칩은 자료가 있는 나라만(지금 미국 · 한국 · 유로 · 일본).

### C7 갱신 · 중단 배너
- `lib/bundle.ts`: 장중(한국 09:00~15:30 KST 평일 또는 미국 장중) 5분마다 · 탭 복귀(30분 넘게 숨었다 돌아오면) 묶음 다시 읽기 → 화면 갱신(머리 꼬리표 시각이 바뀐다).
- 서킷브레이커 · 사이드카 발동 중(`market-domestic` 매매중단 · halts)이면 머리 아래 배너 한 줄(경보와 같은 사건, 누르면 매매중단 패널).
- 설정 「데이터 상태」에 실패가 있으면 머리 톱니에 점.

### C11 메르 전문 검색 · 출처 3줄
- 검색 오버레이(`components/personal/SearchOverlay.tsx`)가 `merblog.json` 최신 20편 전문도 찾아 글 제목 · 일치 문장 · 링크. 렌즈 「사슬」의 출처 인용을 1줄 → 글마다 3줄(`mer_signals` 인용, 80자 이하).

### 게이트(P2)
- 묶음 사용률: 묶음 생성 때 `data.json` 최상위 키 31 중 어느 묶음에도 안 실리는 키 목록을 찍는다(`scripts/tests/test_bundle_usage.py` — 지금 목록을 기준선으로, 늘면 실패).
- 갱신: 탭을 숨겼다 돌아오면 묶음 다시 읽기(단위 테스트로 판정 함수만).

P2 끝 증거: 살아 있는데 안 읽는 데이터 10 → 2 이하 · 내려받은 파일로 새 기기에 복원 · 장중 값 갱신.

---

## 범위 밖
D11 관심 목록 KV 이전(보류) · D12 출처 분리 · 렌즈 집계 블록 4 · 종목 상세(C9/D14, P3) · 비교 차트(C10) · 벤치마크(C8, P3) · 옛 화면 스터디 · 노트.
