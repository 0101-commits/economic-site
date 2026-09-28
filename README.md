# economic-site

한국 경제 대시보드 — GitHub Pages 정적 사이트 + GitHub Actions 데이터 수집 + Cloudflare Worker 프록시.

- 사이트: <https://0101-commits.github.io/economic-site/>
- 빌드 단계 없음: `index.html` + `js/app*.js` 를 직접 고치면 push 즉시 반영됩니다(`*.min.js` 는 CI 가 생성).
- 개발 규칙 전체(디자인 토큰·게이트·데이터 신선도): **[CLAUDE.md](CLAUDE.md)**

## 구조

```
economic-site/
├─ index.html              화면 전체(스타일·마크업·로더) — GitHub Pages 진입점
├─ go.html                 카톡 링크 경유 리다이렉트(생성물: scripts/build_go_page.py)
├─ og-cover.png            공유 미리보기 이미지
├─ js/                     앱 스크립트 app0~7(.min.js 는 CI 생성) — js/README.md
├─ css/                    seed/ = SEED 벤더 CSS, fonts/ = 웹폰트
├─ scripts/                데이터 수집·검증·알림 발송(Python) + 로컬 토스 수집기(.cmd/.ps1/.vbs)
│  ├─ tests/               스크립트 단위 테스트
│  └─ legacy/astryx/       폐기된 astryx 토큰 생성기 — 기록용, 실행 금지
├─ tests/ui/               Playwright UI 게이트(.mjs)
├─ cloudflare-worker/      CORS 프록시·AI 중계·카톡 cron Worker — cloudflare-worker/README.md
├─ root-site/              사용자 루트 페이지(0101-commits.github.io) 리다이렉트 원본
├─ docs/                   운영 가이드·기획서 — docs/README.md
├─ .github/workflows/      수집·발송·알림·빌드 워크플로 8종
└─ *.json / *.jsonl        봇이 커밋하는 데이터 산출물(아래 표) — 손으로 고치지 말 것
```

루트의 데이터 파일은 사이트(`fetch('data.json')` 등)·워크플로·Worker 가 **루트 경로로 직접 읽기 때문에** 폴더로 옮기지 않습니다.

| 파일 | 만드는 곳 | 용도 |
|---|---|---|
| `data.json` · `data_meta.json` | `scripts/fetch_data.py` | 시장 데이터 본체 · 갱신 시각 |
| `toss_snapshot.json` | `scripts/fetch_toss_snapshot.py`(로컬 PC) | 토스 Open API 수집분 |
| `mer_signals.json` · `mer_series.json` · `mer_extract_cache.jsonl` · `merblog.json` | `scripts/mer_*.py` · `fetch_merblog.py` | 메르 리스크 렌즈 |
| `fundamentals.json` | `scripts/fetch_fundamentals.py` | 종목 펀더멘털 |
| `link_status.json` | `scripts/check_links.py` | 외부 링크 점검 결과 |
| `alerts_config.json` | Worker `POST /portfolio` | 종목 알림 **조건**(보유 정보 없음) |
| `alerts_state.json` · `halts_state.json` · `releases_state.json` | 알림 스크립트 | 중복 발송 방지 상태 |
| `wrangler.jsonc` · `package.json` | 사람 | Worker 배포 설정 · UI 게이트 의존성 |

## 주요 문서

| 문서 | 내용 |
|---|---|
| [docs/KAKAO_SETUP.md](docs/KAKAO_SETUP.md) | 카카오톡 시황 다이제스트 설정(토큰 발급·시크릿·재동의) |
| [docs/STOCK_ALERTS.md](docs/STOCK_ALERTS.md) | 투자 현황(가상 포트폴리오) & 카카오톡 종목 알림 |
| [docs/STUDY_LOG.md](docs/STUDY_LOG.md) | 스터디 기록 페이지(브라우저 로컬 저장) |
| [docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md) | 고도화 반영 현황 및 로드맵 |
| [cloudflare-worker/README.md](cloudflare-worker/README.md) | CORS 프록시 Worker 배포 |
| [docs/README.md](docs/README.md) | 기획서·설계 문서 목록 |

## 로컬 실행과 점검

```bash
python -m http.server 8080 --bind 127.0.0.1           # http://127.0.0.1:8080 에서 확인
python scripts/validate_data.py                       # data.json 정합성
python scripts/check_seed_classes.py                  # 미정의 seed-* 클래스 0
node tests/ui/shots.mjs --page=<id>                   # UI 16샷 게이트(npm i 필요)
```

전체 게이트 목록은 [CLAUDE.md](CLAUDE.md) 「Gates」 절을 따릅니다.

## 🔐 보안 고지
- **`alerts_config.json` 은 공개 저장소에 의도적으로 포함됩니다.** 이 파일은 카카오톡 종목 알림의
  *조건*(종목 코드·이름·시장·목표가/등락률 등 알림 트리거)과 관심목록만 저장합니다.
  **평단가·보유 수량·매입 환율 등 개인 자산(보유) 정보는 일절 포함하지 않습니다** — 프론트엔드가
  해당 정보를 서버로 전송하지 않으며(사용자 선택 '관심목록만 공개 동기화'), Worker 도 화이트리스트
  필드만 커밋합니다.
- 모든 API 키·토큰은 **GitHub Secrets / Cloudflare Worker 시크릿**에만 보관합니다(코드/저장소 하드코딩 금지).
- 쓰기 경로(Worker `POST /portfolio`)와 조회 경로(`GET /portfolio`)는 모두 `ALERTS_SYNC_KEY`(SHA-256 해시) 인증이 필요합니다.
