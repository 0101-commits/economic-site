# economic-site

경제 대시보드 (GitHub Pages 정적 사이트 + GitHub Actions 데이터 수집 + Cloudflare Worker 프록시)

## 주요 문서
- **[STOCK_ALERTS.md](STOCK_ALERTS.md)** — 📈 투자 현황(가상 포트폴리오) & 카카오톡 종목 알림 설정
- **[KAKAO_SETUP.md](KAKAO_SETUP.md)** — 📲 카카오톡 시황 다이제스트(평일 16회·주말 2회) 설정
- **[cloudflare-worker/README.md](cloudflare-worker/README.md)** — CORS 프록시 Worker 배포
- **[IMPROVEMENTS.md](IMPROVEMENTS.md)** — 🛠 고도화 반영 현황 및 로드맵 (보안·UX·기능)

## 📚 스터디 기록 (메뉴: 경제 캘린더 아래, 단축키 `S`, 딥링크 `?p=study`)
스터디 모임 이력을 회차별로 남기는 화면. 좌측 월간 캘린더에서 날짜를 고르고, 우측에서 자료·녹화본·회의록을 관리합니다.

- **저장 위치는 전부 브라우저 로컬** — 메타데이터(제목·참석자·회의록·액션아이템)는 `localStorage['econ_study_v1']`,
  업로드한 파일 실체는 `IndexedDB(econStudyDB/files)`. **서버로 전송되지 않으며 저장소에도 커밋되지 않습니다.**
- 다른 기기로 옮기려면 **데이터 관리 → 파일 포함 백업**(JSON, Base64 내장) 후 가져오기. 용량이 부담되면
  **기록 내보내기**(텍스트만)를 쓰고 영상은 YouTube·Drive **외부 링크**로 등록하세요.
- 녹화/녹음 파일은 인라인 재생 + 배속 조절이 가능하고, **⏱ 현재 시점 메모** 버튼이 회의록에 `[mm:ss]` 를 남깁니다.
  회의록의 `[mm:ss]` 를 클릭하면 그 시점으로 이동합니다.
- **✨ AI 요약 초안** 은 Worker `POST /ai` 를 사용하며 동기화 키(`ALERTS_SYNC_KEY` 해시)가 등록된 기기에서만
  동작합니다. 키가 없거나 호출이 실패하면 회의록을 서버로 보내지 않고 로컬 규칙 기반으로 정리합니다.
- 이 기능 때문에 CSP 에 `media-src 'self' data: blob:` 가 추가되었습니다(로컬 blob 미디어 재생용).

## 🔐 보안 고지
- **`alerts_config.json` 은 공개 저장소에 의도적으로 포함됩니다.** 이 파일은 카카오톡 종목 알림의
  *조건*(종목 코드·이름·시장·목표가/등락률 등 알림 트리거)과 관심목록만 저장합니다.
  **평단가·보유 수량·매입 환율 등 개인 자산(보유) 정보는 일절 포함하지 않습니다** — 프론트엔드가
  해당 정보를 서버로 전송하지 않으며(사용자 선택 '관심목록만 공개 동기화'), Worker 도 화이트리스트
  필드만 커밋합니다.
- 모든 API 키·토큰은 **GitHub Secrets / Cloudflare Worker 시크릿**에만 보관합니다(코드/저장소 하드코딩 금지).
- 쓰기 경로(Worker `POST /portfolio`)와 조회 경로(`GET /portfolio`)는 모두 `ALERTS_SYNC_KEY`(SHA-256 해시) 인증이 필요합니다.
