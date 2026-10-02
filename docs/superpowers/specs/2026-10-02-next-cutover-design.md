# 현행 화면(index.html) → 새 화면 층(/next/) 전환 계획

작성 2026-10-02 · 기획 원문 = 개인투자자용 투자 정보 서비스 기획안 v4(아티팩트 DiJ3byy8gvHH8dynCdejGB) · 구현 가지 redesign-v4(PR #133 병합)

## 1. 지금 상태

| 항목 | 현행 화면 | 새 화면 층 |
|---|---|---|
| 주소 | `/economic-site/` (`index.html`, `?p=화면&t=탭&v=보기`) | `/economic-site/next/` (`#/화면?a=자산군&v=보기`) |
| 코드 | `index.html` 5,659줄 + `js/app0~7.js` + `css/seed` | `app/`(React, 빌드 산출물 `_site/next/`) |
| 데이터 | `data.json` 직접(4.8MB → history 분리 뒤 축소) | `bundles/*.json` 11개(화면 단위, 각 200KB 이하) |
| 저장소(브라우저) | 같은 origin — `localStorage` 공유 | 같음 |
| 배포 | `pages.yml` 허용 목록 | 같은 런에서 `app/dist` → `_site/next/` |

두 화면은 **같은 origin** 이라 브라우저 저장소를 공유한다. 호환 상태:

| 저장 키 | 현행 | 새 화면 | 상태 |
|---|---|---|---|
| PIN `econLockPin_v2` | 사용 | 같은 형식(PBKDF2 600k) | 호환 |
| 보유 `portfolioV1`·`pfSnapshotsV1`·`pfLedgerV1` | 사용 | 같은 형식 | 호환 |
| 테마 `econ_theme` | 사용 | 읽음 | 호환 |
| 관심 `econ_fav_v1` → `econ_watch_v1` | 지표 id 배열 | 지표 id 배열 | 새 화면이 첫 실행 때 이어받음(2026-10-02) |
| 설정·알림 조건 `econPrefsV1` | 없음(알림은 `alerts_config.json`) | 사용 + Worker `/prefs` | 새 화면 전용 |

## 2. 단계

### 단계 A — 공존(지금 ~ 전환 조건 충족까지)
- 현행 머리줄에 「새 화면 보기」 글자 링크 하나(`/next/`), 새 화면 설정 맨 아래에 「이전 화면으로」 링크 하나. 둘 다 작은 글자, 배너·팝업 없음.
- 주소 별칭표(아래 §3)를 `app/src/lib/legacyUrl.ts` 한 곳에 둔다. 새 화면이 `?p=` 가 붙은 주소로 열리면(현행 북마크·알림 버튼) 그 표로 `#/…` 로 바꿔 연다.
- 사용자(1인)가 2주 써 보고 결함을 모은다. 결함은 이 문서 아래 「전환 조건」 표에 적는다.

### 단계 B — 기본 전환
- `index.html` 머리에 짧은 분기 스크립트: `localStorage.econ_ui === 'legacy'` 또는 주소에 `?legacy=1` 이 없으면 `/next/` + 별칭 주소로 이동(`location.replace`). 「이전 화면으로」 를 누르면 `econ_ui=legacy` 를 기록해 현행에 머문다.
- 알림(디스코드 버튼·카카오 버튼·웹 푸시)의 링크 생성은 한 곳(`scripts/discord_card.py`/`notify_discord.py`/`send_kakao_digest.py` 의 URL 조립 함수)에서 새 주소로 바꾼다. 발송 주소 변경은 알림 글 검사(`scripts/tests/test_alert_redesign.py`)에 사례를 더해 고정한다.
- `og:*`·`canonical` 은 루트 주소 그대로(검색·공유 링크 보존). PWA `manifest.webmanifest` 의 `start_url` 은 `./`(= `/next/`) 유지.

### 단계 C — 폐기
- `index.html` 을 안내 한 장(「새 화면으로 옮겼습니다」 + 링크, `go.html` 과 같은 꼴)으로 바꾸고 `js/`·`css/seed/` 를 지운다. `collect_site.mjs` 허용 목록에서 `js`·`css` 를 빼고 `data.json` 직접 공개도 필요한지 다시 본다(새 화면은 `bundles/` 만 읽는다. 단 `history.json`·`data.json` 을 읽는 외부 사용자가 있으면 남긴다).
- 현행 전용 UI 게이트 13종(`tests/ui/shots.mjs`·`structure.mjs`·`components.mjs`·`readability*.mjs` 등)과 `scripts/check_seed_classes.py`·`vendor_seed_css.py` 를 지운다. 새 화면 게이트 4종(`overflow`·`longdata`·`matrix`·`check_text_limits`)만 남는다.
- `build_indicators.py` 가 만드는 `js/app0.js` 는 현행 화면용이다 — 레지스트리는 `bundles/registry.json` 으로 이미 가므로 `js/app0.js` 생성을 끈다.

## 3. 주소 별칭표(현행 → 새 화면)

| 현행 | 새 화면 |
|---|---|
| `/` `?p=dashboard` | `#/` |
| `?p=market&t=kr` `?p=equity` `?p=investor` | `#/market?a=kr` (`t=flows` → `v=flows`) |
| `?p=market&t=global` | `#/market?a=global` |
| `?p=market&t=fx` `?p=market&t=rate` | `#/market?a=fxrate` |
| `?p=market&t=commodity` | `#/market?a=commod` |
| `?p=macro` (`t=` 주제) | `#/market?a=macro&v=주제` |
| `?p=realestate` | `#/market?a=realestate` |
| `?p=merlens` `?p=merblog` `?p=lede` | `#/lens` (`m=whatif|chain|flow`) |
| `?p=portfolio` | `#/my` |
| `?p=calendar` | `#/`(홈 일정 패널) — 전용 화면 없음, 홈에 접힘으로 |
| `?p=settings` | `#/settings` |
| `?p=notes` `?p=study` | 이관하지 않음(로컬 전용 기록, 단계 C 전에 JSON 내보내기 안내) |

별칭표는 코드가 단일 원천이다(`legacyUrl.ts`). 이 표가 바뀌면 코드도 함께 바꾼다.

## 4. 전환 조건(단계 B 로 가기 전에 전부 충족)

| 조건 | 상태(2026-10-02) | 조치·주체 |
|---|---|---|
| 새 화면 넘침·잘림 게이트 18경로 × 폭 4 × 테마 2 위반 0 | 충족 | — |
| 실제 주소 콘솔 오류·실패 요청 0 | 충족(21경로 실측) | — |
| 분기·연간 지표 기준시점 표기, 부동산 거래량 중복 | 수정·푸시(85406bd4) | — |
| 신규 데이터 3건(시도 시계열·KRX 순위·공시) 실제 수신 | 일일 런 대기(수동 런 07:40 UTC 진행 중) | 팀장 확인 |
| KRX 순위·52주(KRX Open API 401) | 미충족 — 서비스별 이용신청 승인 | 사용자 |
| 보유 E2E 동기화(encHoldings) 현행 호환 | 진행 중(에이전트) | 팀장 |
| 알림 「발동됨·다시 켜기」 | 진행 중(에이전트) | 팀장 |
| 웹 푸시 실발송(시크릿 4종·Worker 재배포) | 미충족 | 사용자 |
| 노트·스터디 기록 내보내기 안내 | 미착수(단계 C 전) | 팀장 |
| 2주 실사용 결함 0 | 미착수 | 사용자 |

## 5. 결정이 필요한 것

| 번호 | 질문 | 권고 |
|---|---|---|
| D1 | 기본 전환(단계 B) 시점 | 전환 조건 전부 충족 + 2주 실사용 뒤. 날짜를 미리 못 박지 않는다 |
| D2 | 현행 화면 유지 기간(단계 C 까지) | 단계 B 뒤 4주. 그 사이 「이전 화면으로」 사용 횟수가 0 이면 폐기 |
| D3 | 알림 링크를 새 주소로 바꾸는 시점 | 단계 B 와 동시(한 번에). 폰에서 `/next/` 가 열리는지 디스코드·카카오 버튼으로 먼저 실측 |
| D4 | `?p=notes`·`?p=study` 기록 | 이관하지 않고 내보내기 안내. 새 화면에 같은 기능을 만들지 않는다(기획 범위 밖) |
| D5 | `data.json`·`history.json` 공개 유지 | 단계 C 에서도 유지(외부 사용 여부 모름 — 끊으면 조용히 깨진다) |

## 6. 위험

- `pages.yml` 의 앱 빌드 단계가 실패하면 현행 화면 배포도 멈춘다(한 런). 빌드는 로컬과 같은 명령이라 PR 전 로컬 통과가 조건이다.
- `?p=` 북마크가 깨지지 않게 별칭 리다이렉트는 단계 C 뒤에도 안내 페이지가 맡는다.
- iOS 웹 푸시는 홈 화면에 추가한 `/next/` 에서만 된다 — 현행 주소로 추가한 사용자는 다시 추가해야 한다(설정 화면 한 줄 안내).
