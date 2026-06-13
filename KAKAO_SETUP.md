# 📲 카카오톡 시황 알림 (평일 16회·주말 2회) — 설정 가이드

**평일 07~22시 매시간 / 주말 11·17시(KST) 03분 무렵** `data.json` 시황이
**본인 카카오톡** 으로 자동 발송됩니다.

수신 모드는 2가지이며 **자동 판별**됩니다(아래 ⑤ 설정 여부에 따라):

- **친구에게 보내기(권장)** — 보조 계정이 발신자가 되어 본 계정·지인들에게 발송.
  일반 카톡처럼 **푸시 알림이 울립니다**. 설정: 아래 **⑤** (1회, 약 10분)
- **나에게 보내기(기본)** — "나와의 채팅"으로 발송. **알림이 울리지 않습니다**
  (카카오톡이 '내가 보낸 메시지'로 취급해 무음·자동 읽음 처리).

**발송 형식은 모든 슬롯이 동일한 '피드 한 통'입니다** (형식 통일):

- 슬롯별 **차트 이미지 1장** (당일 인트라데이 기준, 당일 데이터가 없으면 **7일 일봉으로 폴백**)
- 제목: `M/D(요일) H시 시황`
- 공통 내용 4종 — **증시**(코스피·S&P) / **환율**(달러-원·달러-엔) / **심리**(공포탐욕·VIX) / **원자재**(WTI·금·구리)
- `대시보드 보기` 버튼

| 구분 | 시각(KST) | 차트 (위 + 아래) |
|---|---|---|
| 평일 | **07시 · 08시** | S&P500 + 달러-원 |
| 평일 | **09시** | S&P500 + 금 |
| 평일 | **10시 ~ 16시** | 코스피 + 달러-원 |
| 평일 | **17시** | 달러-원 + 금 |
| 평일 | **18시 ~ 22시** | 달러-원 + WTI |
| 주말 | **11시 · 17시** | 달러-원 + 금 *(본문은 평일과 동일)* |

서버(GitHub Actions)에서 실행되므로 브라우저를 켜둘 필요가 없습니다.
(차트 라벨은 CI 한글폰트 부재 대비 영문이며, 차트를 끄려면 저장소 변수 `KAKAO_CHARTS=0` 을 두면 됩니다.)

> ⏰ 발송 시각은 **정각이 아닌 03분**입니다. Cloudflare Cron 이 각 슬롯 02분(UTC)에 GitHub 워크플로를
> 깨우고, 잡 기동·차트 생성·발송에 약 1분이 걸려 카카오 도착이 03분 부근이 됩니다.

> 자동 발송은 GitHub Actions(아래 시크릿 2개 필요)가 담당합니다. PlayMCP 의 "나에게 보내기(MemoChat)"
> 도구는 즉석 파일럿/테스트 발송용이며, 매일 정해진 시각의 무인 자동 발송에는 사용할 수 없습니다
> (MCP 도구는 세션이 떠 있어야만 동작하므로). 따라서 정기 루틴은 GitHub Actions 로 구성합니다.

> 카카오톡은 임의의 상대에게 무료 발송이 불가하지만, **"나에게 보내기"(메모 API)** 는
> 무료이고 앱 심사도 필요 없습니다. 개인 데일리 브리핑에 적합합니다.

---

## 1회 설정 (약 10분)

### ① 카카오 개발자 앱 만들기
1. <https://developers.kakao.com> 로그인 → **내 애플리케이션 → 애플리케이션 추가하기**
2. 생성된 앱 → **앱 키** 의 **REST API 키** 를 복사 (나중에 `KAKAO_REST_API_KEY` 로 사용)

### ② 카카오 로그인 + 메시지 권한 켜기
1. **제품 설정 → 카카오 로그인 → 활성화 ON**
2. **Redirect URI** 등록 — 임시로 `https://localhost` 입력해도 됩니다(토큰 1회 발급용)
3. **제품 설정 → 카카오 로그인 → 동의항목** 에서 **"카카오톡 메시지 전송(`talk_message`)"** 을 **사용함**으로 설정

### ③ refresh_token 1회 발급
1. 아래 주소를 브라우저 주소창에 붙여넣고 이동 (`REST_API_KEY` 를 ①에서 복사한 값으로 교체):
   ```
   https://kauth.kakao.com/oauth/authorize?client_id=REST_API_KEY&redirect_uri=https://localhost&response_type=code&scope=talk_message
   ```
2. 카카오 로그인/동의 후 `https://localhost/?code=XXXXXXXX...` 로 이동됩니다 → 주소의 **`code=` 뒤 값**을 복사
3. 터미널에서 토큰 교환 (둘 다 본인 값으로 교체):
   ```bash
   curl -X POST "https://kauth.kakao.com/oauth/token" \
     -d "grant_type=authorization_code" \
     -d "client_id=REST_API_KEY" \
     -d "redirect_uri=https://localhost" \
     -d "code=붙여넣은_code"
   ```
4. 응답 JSON 의 **`refresh_token`** 값을 복사 (나중에 `KAKAO_REFRESH_TOKEN` 으로 사용)

### ④ GitHub Secrets 등록
저장소 → **Settings → Secrets and variables → Actions → New repository secret** 에서 2개 추가:

| 이름 | 값 |
|---|---|
| `KAKAO_REST_API_KEY` | ①에서 복사한 REST API 키 |
| `KAKAO_REFRESH_TOKEN` | ③에서 복사한 refresh_token |

### ⑤ (선택·권장) 친구에게 보내기 — 푸시 알림 받기

"나에게 보내기"는 알림이 울리지 않으므로, **발신용 보조 카카오 계정**을 만들어
보조 계정 → 본 계정(친구) 방향으로 보내면 일반 메시지처럼 알림이 옵니다.
검수(비즈니스 인증) 없이 쓰려면 받는 사람이 모두 **앱 팀 멤버**여야 합니다.

1. **보조 카카오 계정 준비** — 새 계정을 만들고, 카카오톡에서 **본 계정과 친구**를 맺습니다.
   (메시지를 받을 지인이 더 있다면 그 지인들도 보조 계정과 친구 맺기)
2. **앱 멤버 추가** — 카카오 developers(본 계정/Owner) → 앱 → **앱 설정 → 멤버 → 멤버 추가** 에서
   보조 계정 이메일을 추가합니다(역할은 Viewer 면 충분). 메시지 받을 지인도 각각 추가.
3. **동의항목 켜기** — **제품 설정 → 카카오 로그인 → 동의항목** 에서
   **"카카오 서비스 내 친구 목록(`friends`)"** 을 사용함(선택 동의)으로 설정합니다
   (`talk_message` 는 ②에서 이미 켜져 있음).
4. **양쪽 계정 로그인·동의** — 위 ③의 토큰 발급 주소에서 `scope` 만 바꿔 사용합니다:
   ```
   https://kauth.kakao.com/oauth/authorize?client_id=REST_API_KEY&redirect_uri=https://localhost&response_type=code&scope=talk_message,friends
   ```
   - **보조 계정**으로 로그인·동의 → 받은 `code` 로 ③과 동일하게 토큰 교환 → **`refresh_token` 보관**
   - **본 계정**(및 지인들)도 같은 주소로 로그인·동의만 하면 됩니다(토큰은 안 써도 됨 —
     발신자의 친구 목록 API 에 잡히려면 앱 연결 + `friends` 동의가 필요).
5. **시크릿 교체** — GitHub Secret `KAKAO_REFRESH_TOKEN` 을 **보조 계정의 refresh_token** 으로 교체.
6. **테스트** — 아래 '테스트(즉시 발송)' 실행 → 본 계정 카톡에 **알림과 함께** 도착하면 성공.
   (워크플로 로그에 `수신: 친구 N명 (...)` 이 찍힙니다)

> 동작 원리: 발송 스크립트가 매번 친구 목록을 조회해 **동의된 친구가 있으면 친구에게**,
> 없으면 종전대로 **나에게 보내기**로 자동 전환합니다(코드 수정·재배포 불필요).
> 끄려면 저장소 변수 `KAKAO_FRIENDS=0`.
>
> 쿼터: 한 호출당 5명씩 분할 발송. **발신자당 일 100건 / 발신자→수신자 쌍당 일 20건** —
> 평일 16회 발송 기준 **수신자 6명까지** 안전합니다.

---

## 테스트 (즉시 발송)
설정 후 바로 확인하려면:
**GitHub → Actions → "KakaoTalk Digest (평일 07-22 매시간 · 주말 11·17 KST)" → Run workflow** 클릭
→ 잠시 후 본인 카카오톡 "나와의 채팅" 에 차트 피드가 도착하면 성공입니다.

## 발송 예시 (모든 슬롯 동일 구성)
```
[차트 이미지: 코스피 + 달러-원 (당일)]
6/10(수) 10시 시황
코스피 8,097▲8.2% S&P 7,387▼0.3%
달러-원 1,529.0▲0.0% 달러-엔 160.1▲0.0%
심리    공포탐욕 33(공포) VIX 18.9
원자재  WTI 89.0▼1.3% 금 4,269▼2.1% 구리 6.34▲0.3%
[대시보드 보기]
```

> ℹ️ 과거에 쓰던 **카카오 콘솔 커스텀 템플릿(`KAKAO_TEMPLATE_ID`) 폴백은 제거**했습니다.
> 콘솔 템플릿은 레이아웃이 코드와 따로 놀아(이미지 없음·심리 누락·값 잘림) "형식이 다른 알림"이
> 가던 원인이었습니다(2026-06-10 10시 사례). 지금은 어떤 경우에도 위와 같은 내용 구성으로만 발송되며,
> 카카오 이미지 서버 장애 등 극단적 상황에서만 **같은 내용의 텍스트 한 통**(이미지 제외)으로 폴백합니다.
> 메시지 내용·차트 구성을 바꾸려면 `scripts/send_kakao_digest.py` 의 `build_digest_parts` /
> `SLOT_CHARTS` 를 수정하세요.

---

## ⏰ 자동 발송 시각 안정화 — Cloudflare Cron (권장, 1회 설정)

GitHub Actions 의 `schedule`(cron) 은 best-effort 라 **정각 보장이 안 되고 통째로 누락**되곤 합니다(실측: 며칠씩 드롭).
그래서 **이미 배포돼 있는 Cloudflare Worker**(`ecom-dashboard-proxy`)의 **Cron Trigger** 가 매 슬롯 **02분(UTC)**
(`wrangler.jsonc` 의 `triggers.crons`)에 GitHub 워크플로를 **on-demand(repository_dispatch)** 로 깨웁니다.
on-demand 실행은 스케줄 드롭의 영향을 받지 않아 **즉시** 돌고, 차트 생성·발송은 그대로 GitHub Actions 가 합니다.

**해야 할 일 (딱 1개) — Worker 에 GitHub 토큰 시크릿 추가:**
1. GitHub → 우상단 프로필 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate**
   - **Repository access**: `0101-commits/economic-site` 만 선택
   - **Permissions → Repository permissions → Contents: Read and write** (이게 있어야 `repository_dispatch` 가능)
   - 토큰 생성 후 값 복사
2. 이 토큰을 **Cloudflare Worker 시크릿 `GH_DISPATCH_TOKEN`** 으로 등록:
   - Cloudflare 대시보드 → **Workers & Pages → `ecom-dashboard-proxy` → Settings → Variables and Secrets → Add → Secret**
     이름 `GH_DISPATCH_TOKEN`, 값=위 토큰 → Save
   - (또는 CLI) 저장소 루트에서 `npx wrangler secret put GH_DISPATCH_TOKEN`
3. 끝. 이후 평일 16개·주말 2개 슬롯에 자동 발송됩니다. (Worker 는 `main` push 시 자동 재배포되어 cron 이 등록됩니다 —
   cron 시각을 바꿨다면 재배포 전까지는 이전 시각으로 동작하니, `npx wrangler deploy` 로 즉시 반영할 수도 있습니다.)

> 토큰 미설정 시: Worker 의 cron 은 돌지만 dispatch 를 건너뛰고 경고만 남깁니다(안전).
> 그동안은 GitHub `schedule`(:03) 백업이 살아있을 때만 발송됩니다.

---

## 참고 / 문제 해결
- **발송 시각**: 평일 07~22시 매시간·주말 11·17시 03분(KST) 무렵. Cloudflare Cron(주 경로) + GitHub
  `schedule`(:03)·`workflow_run` 백업. 어느 경로든 **슬롯당 하루 한 번만** 발송(중복 방지 마커).
- **발송 형태(통일)**: 모든 슬롯이 같은 '피드 한 통' — 차트 이미지 + 증시·환율(설명) + 심리·원자재(행) +
  '대시보드 보기' 버튼. 발송 직전 단계에서 일시 장애가 나도 **모든 카카오 API 호출에 재시도**가 걸려 있고,
  그래도 이미지 첨부가 불가능하면 **같은 내용의 텍스트**로만 폴백합니다(다른 레이아웃 없음).
- **차트 이미지**: 슬롯별 차트를 `matplotlib` 로 1장 만들어 **카카오 이미지 업로드 API** 로 올린 뒤 피드로
  첨부합니다(이미지 호스팅·도메인 등록 불필요). **당일(인트라데이) 시세 우선, 실패 시 7일 일봉 폴백.**
- **🔗 링크가 엉뚱한 사이트(예: `localhost…`)로 열릴 때**: 메시지의 이미지·버튼 링크 도메인은 카카오 앱에 **등록된 사이트 도메인**이어야 합니다. 미등록이면 카카오가 등록된(잘못된) 도메인으로 대체합니다.
  → 카카오 developers → 내 애플리케이션 → **앱 설정 → 플랫폼 → Web → 사이트 도메인** 에 `https://0101-commits.github.io` 를 등록(잘못된 도메인은 삭제)하면 대시보드로 정상 연결됩니다. (코드의 링크는 이미 대시보드입니다.)
- **🔗 메시지 '맨 하단'(앱 이름 ECOM 영역)을 누르면 404 가 뜰 때**: 이미지·'대시보드 보기' 버튼과 달리,
  말풍선 맨 아래의 **앱 이름 영역**은 카카오가 **등록된 사이트 도메인의 루트**(`https://0101-commits.github.io`)
  로 보냅니다. 카카오 도메인 등록은 경로(`/economic-site/`)를 붙일 수 없어 코드로는 바꿀 수 없고,
  GitHub Pages **사용자 사이트 저장소가 없으면** 그 루트가 404 입니다. 해결(1회, 약 2분):
  1. GitHub 에 새 공개 저장소 **`0101-commits.github.io`** 생성 (이름이 정확히 이래야 합니다)
  2. 이 저장소의 [`root-site/index.html`](root-site/index.html) 파일을 새 저장소 루트에 복사
  3. 새 저장소 Settings → Pages → Deploy from a branch → `main` 선택
  → 이후 루트 접속이 대시보드(`/economic-site/`)로 자동 리다이렉트되어 404 가 사라집니다.
- **데이터 기준**: 발송 시점에 저장소에 커밋된 최신 `data.json`(장중 약 10분 주기 갱신본)을 사용합니다.
- **`refresh_token` 만료**: 매일 사용하면 자동 연장됩니다. 만약 만료(약 2개월 미사용 시)되면
  위 **③** 만 다시 수행해 새 `refresh_token` 으로 `KAKAO_REFRESH_TOKEN` 시크릿을 교체하세요.
  (워크플로 로그에 "새 refresh_token 발급" 경고가 뜨면 그 값으로 교체하면 됩니다.)
- **요약 길이**: 카카오 텍스트 템플릿은 200자 제한이라 공통 4블록(증시·환율·심리·원자재)만 담고, 상세는 대시보드 링크로 제공합니다.
