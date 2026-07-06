# 메르 블로그(ranto28) 키워드 검색 → 원문 JSON — 설계

- 날짜: 2026-07-06
- 대상 repo: `C:\Users\cgpar\economic-site`
- 상태: 승인됨(브레인스토밍 완료), 구현계획 대기

## 목적

경제 블로거 "메르"(네이버 블로그 `ranto28`)의 글을 키워드(예: 물가, 환율, 미국채 10년물)로 검색하고, 관련 포스팅의 **원문을 JSON으로 정리**해 뽑을 수 있게 한다. 기존 economic-site 대시보드에 통합한다.

## 검증된 기술 사실 (2026-07-06 실측)

- **검색 API**: `https://m.blog.naver.com/api/blogs/ranto28/search/post?query=<kw>&page=<n>&size=<n>`
  - 로그인 없이 JSON 반환. 응답: `result.totalCount`, `result.list[]`
  - 리스트 항목 필드: `logNo`, `blogId`, `title`(HTML `<em class="highlight">` 포함), `categoryName`, `addDate`(epoch ms), `contents`(발췌, HTML 하이라이트 포함), `thumbnailUrl`
  - 예: `물가` → totalCount 205. 헤더 `User-Agent`(모바일), `Referer: https://m.blog.naver.com/ranto28` 권장.
  - 정렬 `sortType=sim`(관련도) 기본. 날짜순 파라미터 존재 여부는 구현 시 확인.
- **원문 전체**: `https://blog.naver.com/PostView.naver?blogId=ranto28&logNo=<logNo>`
  - 본문 = `<div ... class="se-main-container">` 내부. `<[^>]+>` 제거 + `html.unescape` + 공백 정규화로 평문 추출 확인. HTML ~270KB/글.
  - 이미지/표는 본문 텍스트에서 제외(원문 = 텍스트 중심). 이미지 URL은 선택적으로 별도 배열 수집 가능(YAGNI — 초판 제외).
- **RSS**: `https://rss.blog.naver.com/ranto28.xml` — 최근글 목록(백업 소스, 초판 미사용).
- **CORS**: 네이버 API는 CORS 헤더 없음 → 브라우저 직접 호출 불가. 라이브 검색은 Cloudflare Worker 프록시 필수.

## 아키텍처 (하이브리드: 스냅샷 + 라이브)

```
[GitHub Actions 주기 실행]                 [사용자 브라우저]
 fetch_merblog.py                            index.html
   ↓ 검색 API 페이징                          「메르 블로그 검색」 패널
 merblog.json (최근 ~150개 메타                  ↓ 키워드 입력
   + 최근 20개 원문)                    ┌──── 스냅샷에 있음 → 즉시 표시(클라 필터)
   ↓ 자동 커밋 → Pages 배포            └──── 없음/과거글 → Worker 라이브 호출
                                              ↓
                              [Cloudflare Worker] /merblog?q=&full=
                                네이버 검색 API 프록시(+원문 상위 K)
                                → JSON 반환 (CORS 허용)
                                              ↓
                                       결과 리스트 + 「원문 보기」 + 「JSON 다운로드」
```

## 파트 1 — 데이터/저장 (스냅샷)

- **새 파일 `merblog.json`** (repo 루트). `data.json`은 건드리지 않음 — 1.8만 줄 규모 + `validate_data.py` 하드게이트라 오염 위험. 별도 파일이 검증 마찰 없음.
- **`scripts/fetch_merblog.py`**:
  - 검색 API를 빈/대표 쿼리 또는 최근글 페이징으로 호출해 메르 최근 글 **~150개** 메타 수집.
    - (검색 API는 query 필수일 수 있음 → 최근글 확보는 RSS 또는 카테고리 목록 페이징으로 보강. 구현 시 확정.)
  - 각 항목: `logNo, title(태그 제거), date(ISO), category, excerpt(태그 제거), url`
  - **최근 20개**만 `fullText`(PostView 파싱 원문) 포함. 나머지는 발췌만(용량 절약).
  - 출력 스키마:
    ```json
    {
      "asOf": "2026-07-06T00:10:00Z",
      "blogId": "ranto28",
      "blogName": "메르의 블로그",
      "count": 150,
      "posts": [
        {"logNo":"223967469436","title":"...","date":"2025-08-12T...","category":"경제/주식/국제정세/사회","excerpt":"...","url":"https://blog.naver.com/ranto28/223967469436","fullText":"..."}
      ]
    }
    ```
  - stale/에러 내성: 네트워크 실패 시 기존 `merblog.json` 보존(날조 금지, 기존 repo 관행 준수).
- **Actions**: 기존 `fetch-data.yml`에 스텝 1개 추가(`python scripts/fetch_merblog.py`) → 커밋 스텝이 `merblog.json`도 포함. `validate_data.py`는 손대지 않음(별도 파일이라 무관).

## 파트 2 — 라이브 생검색 (Cloudflare Worker)

- **`cloudflare-worker/worker.js`에 라우트 추가**: `GET /merblog?q=<kw>&page=<n>&size=<n>&full=<0|1>&fullK=<n>`
  - Worker가 네이버 모바일 검색 API를 서버측에서 호출(CORS 우회) → 정규화 JSON 반환.
  - `full=1`이면 결과 **상위 K개(기본 5, 최대 20)** 원문을 PostView에서 파싱해 `fullText` 동봉. K 상한 하드코딩(과도 요청 방지).
  - 응답 스키마 = 파트 1 스키마와 동일 형태(`posts[]`) + `totalCount`, `page`.
  - CORS: 기존 Worker CORS 정책(허용 오리진) 재사용. 읽기 전용 GET.
  - 에러: 네이버 비정상 응답 시 5xx + `{error}` JSON(날조 금지).
  - 레이트/남용: 기존 rate-limit 미들웨어 적용. full 파싱은 K로 제한.
- **배포**: `cd cloudflare-worker && npx wrangler deploy` 1회(wrangler는 baldr0001@gmail.com 로그인됨). git push로는 배포 안 됨.

## 파트 3 — 프론트 UI (`index.html`)

- **새 페이지/패널** 「📝 메르 블로그 검색」 — 라우트 `?p=merblog`, `showPage('merblog')`. 메뉴에 항목 추가.
- **검색창**: 키워드 입력 + 검색 버튼(Enter). 옵션: "전체 기간 검색(라이브)" 체크박스 — 끄면 스냅샷만(즉시), 켜면 Worker 호출.
  - 기본 동작: 먼저 `merblog.json` 스냅샷을 클라이언트 필터(제목+발췌 부분일치)로 즉시 표시. 결과 부족/전체기간 원하면 Worker 라이브.
- **결과 리스트**: 카드/행 = 제목 · 날짜 · 카테고리 · 발췌(하이라이트). 정렬 토글(관련도/최신).
- **「원문 보기」**: 각 항목 펼침. 스냅샷 최근 20개는 즉시(fullText 내장), 그 외엔 Worker `full` 호출로 온디맨드 로드.
- **「JSON 다운로드」**(최종 산출물): 현재 검색결과를 JSON 파일로 저장. 옵션 = "원문 포함(상위 N개)". 파일명 `merblog_<키워드>_<날짜>.json`.
  - 클라이언트 `Blob` + `a.download`. 원문 포함 시 Worker `full` 호출로 상위 N개 원문 확보 후 조립.
- 스타일: 기존 대시보드 카드/테마 토큰 재사용. 접근성 aria 라벨(기존 repo 관행).

## 스코프 / YAGNI

- **포함**: 텍스트 원문, 하이브리드 검색, JSON 다운로드.
- **제외(초판)**: 이미지/표 원문 재현, 댓글 수집, 로그인 필요한 비공개글, 감상 분석/요약, 전체 과거글 일괄 아카이브(용량). 필요 시 후속.

## 검증 방법

- `fetch_merblog.py`: 로컬 실행 → `merblog.json` 스키마·건수·원문 존재 확인.
- Worker: 로컬/배포 후 `curl "<worker>/merblog?q=환율&full=1&fullK=2"` → JSON·원문 확인.
- 프론트: headless Chrome 렌더 0에러(기존 repo 검증 관행), 검색→다운로드 라운드트립.

## 위험 / 한계

- 네이버가 API 스펙/차단 정책 변경 가능 → Worker에 명확 에러, 스냅샷이 폴백 역할.
- 검색 API `sortType`/날짜정렬 파라미터 미확정 → 구현 첫 스텝에서 실측.
- Worker 경유 대량 PostView 파싱은 느림/부하 → K 상한으로 관리.
