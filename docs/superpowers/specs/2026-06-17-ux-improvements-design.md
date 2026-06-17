# UX 개선 5종 설계 스펙

**작성일:** 2026-06-17  
**범위:** index.html 단독 편집, 빌드 없음

---

## 1. 키보드 단축키

**대상 키:**

| 키 | 동작 |
|----|------|
| `1`–`8` | 대시보드→캘린더 순서 페이지 이동 |
| `9` | 분석 노트 |
| `0` | 설정 |
| `r` / `R` | `loadRealData()` + `loadRealtimeFx()` + `loadRealtimeMarket()` 즉시 실행 |
| `?` | 단축키 도움말 모달 토글 |
| `Esc` | `kbShortcutModal` 닫기 |

**가드 조건:** `INPUT / TEXTAREA / SELECT` 포커스 중, `isContentEditable`, `Ctrl/Alt/Meta` 수식어 키 → 즉시 리턴.

**구현:** `document.addEventListener('keydown', ...)` 전역 핸들러를 스크립트 말미에 추가. 페이지 이동은 `.menu-item[onclick*="'id'"]` 조회 후 `showPage(id, el)` 호출.

**모달:** `id="kbShortcutModal"` div — `display:none` 초기, `display:flex`로 토글. 배경 클릭 시 닫힘. `</body>` 직전에 삽입.

---

## 2. 수동 새로고침 버튼

**위치:** `#globalDelayChip` (사이드바, line 936) 바로 아래.

**버튼 ID:** `globalRefreshBtn`  
**아이콘 ID:** `globalRefreshIcon` (Material Icons `refresh` 글리프)

**동작:**
1. 클릭 → `manualRefreshData()` 호출
2. 아이콘에 `spin-anim` CSS 클래스 추가 → 회전 애니메이션
3. 버튼 `disabled + opacity:0.5`
4. `loadRealData()` + `loadRealtimeFx()` + `loadRealtimeMarket()` 병렬 실행
5. 완료 후 "새로고침 완료" 텍스트 3초 표시, 아이콘 정지
6. **30초 쿨다운** — 30초 후 버튼 재활성

**CSS:** `@keyframes _spin { to { transform: rotate(360deg); } }` + `.spin-anim { animation: _spin .8s linear infinite; display:inline-block; }` 추가.

---

## 3. URL 딥링크

**`showPage()` 내부 수정 (line 3733 직전):**
```javascript
try { history.replaceState(null, '', location.pathname + '?p=' + id); } catch(_) {}
```
→ 페이지 전환마다 URL에 `?p=<id>` 반영.

**초기 로드 (`window.load` 추가 핸들러):**
```javascript
const p = new URLSearchParams(location.search).get('p');
if(p && VALID_PAGES.includes(p) && p !== 'dashboard') showPage(p, menuEl);
```

**`popstate` 핸들러:** 브라우저 뒤로/앞으로 시 URL `?p=` 읽어 `showPage()` 재호출.

**VALID_PAGES:** `['dashboard','portfolio','equity','macro','market','investor','realestate','calendar','notes','settings']`

---

## 4. 포트폴리오 CSV 내보내기

**버튼:** `↻ 시세 새로고침` 버튼 옆에 `⬇ CSV 저장` 버튼 추가 (line 1332 이후).

**함수:** `pfExportCsv()` — 스크립트 말미에 추가.

**CSV 컬럼:**
`종목코드, 종목명, 시장, 유형, 통화, 평단가, 보유수량, 현재가, 평가금액(원), 매입금액(원), 평가손익(원), 수익률(%), 그룹`

**데이터 소스:** `pfState.items` × `pfQuotes[it.id]`. 환산: `pfUsdKrw()`.

**다운로드:** `Blob + createObjectURL`, UTF-8 BOM 포함 (Excel 한글 호환). 파일명: `portfolio_YYYY-MM-DD.csv`.

---

## 5. 백로그 trivial 3종

코드 검사 결과 이미 구현됨 — 별도 작업 불필요.

| ID | 항목 | 확인 위치 |
|----|------|----------|
| U1 | 버튼 font-weight | line 446-447: `.tab-btn { font-weight: 600 }` |
| U3 | 도넛 borderWidth:0 | line 11357, 11433, 16495 |
| U4 | 투자자 1W 기본 기간 | line 7826-7841: `_investorDefaultApplied` 가드 |
