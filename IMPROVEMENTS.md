# 고도화 현황 및 로드맵

2026-06 「경제현황 터미널 기능·보안·UX/UI 보완 및 고도화 방안」 보고서 기준 추진 현황.

## ✅ 이번 릴리스에 반영된 항목

| # | 항목 | 구현 내용 |
|---|------|----------|
| 1.2 | 동기화 키 인증 강화 | 키를 **SHA-256 해시로만 보관·전송** (`pfSyncKeyHash`), Worker 가 시크릿 해시와 비교 검증. 평문 키가 localStorage/네트워크에 남지 않음. 구버전 평문 호환 유지 |
| 1.1 | 알림 설정 프라이버시 | `STOCK_ALERTS.md` 에 Public 저장소 노출 범위·Private 전환 가이드 명문화 |
| 2.1 | 정보 과부하 완화 | 대시보드 홈 섹션별 **숨김 토글(✕) + 상단 복원 바**, 모바일에서 포트폴리오 테이블 첫 열(종목명) 고정 |
| 2.2 | 스켈레톤 UI | 등락 Top10·공포탐욕·부동산 KPI 의 "로딩 중…" 텍스트를 셔머 스켈레톤 바로 교체, "데이터 추가 필요"는 차분한 — 표기로 통일 |
| 2.3 | 구간 측정 어포던스 | 측정 가능한 6개 차트에 **십자선 커서**, 시작점 클릭 시 차트 위 **수직 점선 마커(📍 시작)** + "끝점을 클릭하세요" 펄스 칩 |
| 2.4 | 지연 안내 단일화 | 카드별 "15분 지연" 문구 제거 → 좌하단 **글로벌 상태 칩** `● Market Data 15m Delayed` (전 페이지 상시 노출, 호버 시 상세) |
| 3.2 | 포트폴리오 고도화 | ① 평단가/수량 **인라인 유효성 검사**(음수·문자 차단) ② 미국 종목 **매입환율 캡처 → 주가손익/환차손익 분리** 표기 ③ 방문일별 스냅샷 적립 → **KOSPI·S&P500 벤치마크 오버레이 차트**(알파 측정) |
| 3.4 | 노트 자동화(부분) | 「📌 지표 스냅샷」 버튼 — 현재 KOSPI/환율/유가/공포탐욕 수치를 마크다운 표로 노트에 박제 |
| 4.1 | 비교차트 지수화 | 「⚖ 지수화 =100」 토글 — 두 지표 시작점을 100으로 환산, 단일 축으로 순수 등락률 비교 (이중축 착시 제거) |
| 4.3 | 캘린더 서프라이즈 | 예측 대비 실제 격차(±15% 또는 ±0.3%p 이상)를 **매크로 서프라이즈**로 판정 — 행 배경 초록(호재)/빨강(악재) 하이라이트 + ⚡ 배지 + 팝업 내 격차 표기 |
| 4.4 | 연기금 교차 비교 | NPS·GPFG·GPIF·TSP·CalPERS **자산배분 교차 비교 차트** (주식/채권/대체/기타 정규화, 100% 누적 막대) |

참고: CSP(스크립트 출처 제한·SRI 무결성 해시·connect-src 허용 목록)는 이전 릴리스에서 이미 적용되어
있어 1.3 의 XSS/유출 방어 핵심은 충족된 상태입니다.

## 🗺 로드맵 (인프라/외부 서비스가 필요한 항목)

정적 호스팅(GitHub Pages) + 무료 티어 제약 안에서 단계적으로 도입할 항목:

- **(1.1/1.2) 사용자별 데이터 분리 + OAuth** — Supabase(무료 티어) Auth + Row Level Security 로
  사용자별 알림 설정을 암호화 보관하고, 카카오/구글 소셜 로그인(OAuth 2.0 + JWT)으로 동기화
  키를 대체. 공개 저장소 커밋 방식(`alerts_config.json`)을 폐기할 수 있게 됨.
- **(1.3) localStorage 암호화** — Web Crypto AES-GCM 암호화는 *키를 같은 브라우저 컨텍스트에
  보관하는 한* XSS 에 대한 실효 방어가 되지 않아(공격 스크립트가 키에도 접근 가능) 이번에는
  도입하지 않음. OAuth 도입 시 서버 측 보관으로 함께 해결하는 것이 올바른 경로.
- **(3.1) 중앙 프록시 + 캐싱 레이어** — 기존 Cloudflare Worker 에 R-ONE/FRED 마스터 키를
  시크릿으로 은닉하고 Cache API/KV 로 1시간~1일 캐싱하는 `/macro`, `/realestate` 엔드포인트
  추가. 비개발자 사용자가 API 키 발급 없이 전체 기능을 쓸 수 있게 됨.
- **(3.3) AI 요약 대화형(RAG) 확장** — 요약 하단 질문창 + 당일 뉴스·캘린더 서프라이즈 수치를
  컨텍스트로 주입하는 Worker `/ai` 확장 (현재 단방향 요약은 동작 중).
- **(3.4) 클라우드 동기화** — Notion API / Google Drive 토큰 연동으로 분석 노트 자동 백업.
- **(4.2) 지도 성능** — 행정구역 GeoJSON → TopoJSON 전환(용량 ~80%↓) + 마커 클러스터링.

---

## ✅ 2차 보완·고도화 (2026-06-12 검토 보고서 반영)

「2차 보완·고도화 검토 보고서」의 항목별 반영 현황.

| ID | 항목 | 구현 내용 |
|----|------|----------|
| S-1 | `/portfolio` 무인증 쓰기 차단 | `ALERTS_SYNC_KEY` 미설정 시 쓰기 거부(**fail-closed**, 503). ⚠ 배포 후 `npx wrangler secret put ALERTS_SYNC_KEY` 1회 실행 필요 |
| S-2 | 레이트리밋 + Origin 제한 | Cloudflare Rate Limiting 바인딩(POST 10/분, 프록시 GET 120/분) + POST 경로 Origin 화이트리스트. 바인딩 미설정 시 통과(점진 도입) |
| S-3 | 공개 CORS 프록시 폴백 제거 | allorigins/codetabs/corsproxy 폴백·CSP 허용 제거 — 전용 Worker 단일 경로 (변조 가능 경로 차단, fail-safe) |
| S-4 | lightweight-charts SRI | sha384 무결성 해시 추가 (npm 원본 타볼 기준, 기존 Chart.js·XLSX·Leaflet 과 동일 방식) |
| S-5(부분) | 평문 키 레거시 제거 | Worker 의 평문 `body.key` 호환(okLegacy) 제거 — 해시 전송만 허용. HMAC 서명은 백로그 유지 |
| S-6(부분) | 토큰 분리 지원 | Worker 가 `GH_ALERTS_TOKEN`(Contents RW 전용) 시크릿을 우선 사용하도록 코드 지원 — 토큰 발급/교체는 운영 작업 |
| S-7 | 클릭재킹 완화 | JS 프레임버스트 추가 (meta CSP 의 frame-ancestors 무시 한계 보완) |
| P-1 | data.json 전량 재다운로드 | `data_meta.json`(~100B) 선조회 — lastUpdated 동일 시 3.6MB 본체 페치 생략. fetch_data.py 가 메타 동시 생성, 워크플로가 함께 커밋 |
| P-2 | XLSX 지연 로드 | `<head>` 정적 로드 제거 → Excel 저장 버튼 클릭 시 `loadXlsxOnce()` 동적 로드(SRI 유지) |
| P-3 | 차트 재초기화 누수 | Chart 생성자 가드 — 동일 캔버스 재사용 시 기존 인스턴스 자동 `destroy()` (호출부 46곳 무수정 중앙 차단) |
| P-4 | preconnect | fonts.googleapis/gstatic + 전용 Worker 사전 연결 |
| F-1 | 알림 테스트 발송 | 🔔 테스트 발송 버튼 → Worker `POST /portfolio/test` → `repository_dispatch(alerts-test)` 로 워크플로 즉시 실행. 테스트 런은 장중/쿨다운 무시·이력 미갱신·"[테스트]" 프리픽스 |
| F-2 | 공통 fetch 래퍼 | `fetchWithRetry()`(타임아웃·재시도 2회·지수 백오프+지터) — Worker 단일 경로의 모든 프록시 페치에 적용 |
| F-4 | CI 데이터 검증 게이트 | `scripts/validate_data.py` — 스키마·핵심 시계열 검증 실패 시 커밋 중단(직전 정상 data.json 유지) |
| U-1 | DevTools/우클릭 차단 제거 | 보안 효과 0, 사용성 손실만 실재 — 전체 제거 |
| U-2 | OG 메타 | description + og:title/description/type/url 추가 (og:image 는 스크린샷 준비 후 활성화, 카카오 캐시 초기화 필요) |
| U-3 | 탭 접근성 | role=tablist/tab + aria-selected 자동 장식, 화살표/Home/End 키보드 내비게이션 (위임 방식, 마크업 무수정) |
| U-4 | prefers-reduced-motion | 애니메이션/전환 비활성 CSS + Chart.js 애니메이션 끄기 |
| U-5 | 가상 뉴스 데이터 제거 | 하드코딩 생성형 헤드라인 전부 제거 — 카테고리 슬롯 구조(`_newsSlot`)만 유지, 실기사(data.json.news·RSS)만 표시 |
| U-6 | 시스템 다크모드 연동 | 첫 방문 기본값: 저장값 > OS prefers-color-scheme > 라이트. `color-scheme` 메타 추가 |
| U-7 | 모바일 터치 타깃 | `(pointer: coarse)` 에서 탭 버튼 히트영역 ±8px 확장 (시각 크기 유지) |

백로그(미반영, 보고서 권고 유지): S-5 HMAC 서명 방식, S-6 토큰 실제 분리·만료 운영,
S-8 인라인 onclick → 이벤트 위임 전환, F-3 PWA, F-5 포트폴리오 CSV 내보내기, P-1② 데이터 분할.

⚠ 배포 체크리스트 (코드 머지 후 운영 작업):
1. `npx wrangler secret put ALERTS_SYNC_KEY` — **미설정 시 알림 동기화 저장이 503 으로 비활성화됨** (의도된 fail-closed)
2. `npx wrangler deploy` (또는 main 머지 시 자동 배포) — 레이트리밋 바인딩 반영
3. 프론트 🔑 동기화 키 버튼에 동일 키 입력
4. (선택) `GH_ALERTS_TOKEN` 시크릿 추가 후 `GH_DISPATCH_TOKEN` 권한 축소
