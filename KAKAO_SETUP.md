# 📲 카카오톡 매일 아침 시황 요약 — 설정 가이드

매일 **오전 10시(KST)** 에 `data.json` 시황 요약이 **본인 카카오톡("나와의 채팅")** 으로 자동 발송됩니다.
서버(GitHub Actions)에서 실행되므로 브라우저를 켜둘 필요가 없습니다.

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

---

## 테스트 (즉시 발송)
설정 후 바로 확인하려면:
**GitHub → Actions → "KakaoTalk Daily Digest (10AM KST)" → Run workflow** 클릭
→ 잠시 후 본인 카카오톡 "나와의 채팅" 에 요약이 도착하면 성공입니다.

## 발송 예시
```
📊 6/1(월) 아침 시황
코스피 8,476.15(▲3.55%) 코스닥 ...(▲..%)
S&P 7,580.06(▲0.22%) 나스닥 ...(▲..%)
달러 1,506.78(▲0.92%) 100엔 945.xx
WTI $89.46(▲2.40%) 금 $4,571(▼0.47%)
공포탐욕 55(중립) VIX 18.x
```
+ 메시지 하단의 **[대시보드 열기]** 버튼으로 전체 대시보드로 이동.

---

## 참고 / 문제 해결
- **발송 시각**: GitHub Actions 스케줄은 UTC·best-effort 라 10시에서 몇 분 늦을 수 있습니다.
- **데이터 기준**: 발송 시점에 저장소에 커밋된 최신 `data.json`(보통 오전 9~9:30 갱신본)을 사용합니다.
- **`refresh_token` 만료**: 매일 사용하면 자동 연장됩니다. 만약 만료(약 2개월 미사용 시)되면
  위 **③** 만 다시 수행해 새 `refresh_token` 으로 `KAKAO_REFRESH_TOKEN` 시크릿을 교체하세요.
  (워크플로 로그에 "새 refresh_token 발급" 경고가 뜨면 그 값으로 교체하면 됩니다.)
- **요약 길이**: 카카오 텍스트 템플릿은 200자 제한이라 핵심 지표만 담고, 상세는 대시보드 링크로 제공합니다.
