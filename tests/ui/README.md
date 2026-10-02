# tests/ui 게이트 안내

기존 게이트(shots · readability · structure · components 등)의 실행법은 각 파일 머리 주석과 루트 CLAUDE.md 에 있다.
아래는 기획안 v4 10장 「화면 품질 게이트」 네 가지다. 한 번에 하나씩 순차로 돌린다(이 PC는 메모리가 적다).

## 공통 인자 (T1·T3·T5)

| 인자 | 기본 | 뜻 |
|---|---|---|
| `--url` 또는 환경변수 `UI_URL` | `http://127.0.0.1:5173/next/` | 새 화면 층 주소. 기존 사이트는 `http://127.0.0.1:8080/` |
| `--paths "/a,/b"` | 주소가 5173 이면 `/ /market /lens /my /alerts`, 그 밖이면 기존 `/?p=` 12종 | 기준 주소 아래 경로 목록 |
| `--widths` | `360,390,768,1440` | 뷰포트 폭 |
| `--themes` | `light,dark` | 에뮬레이션 + `localStorage.econ_theme` + `html[data-theme]` 를 함께 건다 |
| `--allow ".a,.b"` | 없음 | 추가 허용 선택자 |
| `--wait` | 2500 | 로드 뒤 기다리는 ms |

공용 부품은 `_lib.mjs` 한 곳이다. 인자는 `--키 값` 과 `--키=값` 둘 다 된다.

## T1·T2 넘침·잘림 — `npm run ui:overflow`

`node tests/ui/overflow.mjs [--url ...] [--paths ...]` — 위반이 있으면 종료 코드 1.
조합(폭 × 테마 × 경로)마다 다음이 0건이어야 한다.

1. 문서 가로 넘침 (`scrollWidth > clientWidth`)
2. 보이는 요소의 `scrollWidth > clientWidth + 1` 이면서 `overflow-x: visible` 인 것
3. `text-overflow: ellipsis` 가 실제로 걸려 잘린 요소
4. 숫자 글자(`[\d,.\-▲▼%]+` 만)가 두 줄로 꺾인 요소 (Range 사각형 수 > 1)

허용 목록: `.ellipsis-ok` 와 그 자손(2·3), 실제로 가로 스크롤이 되는 조상 안쪽(2), `--allow` 로 준 선택자.
잘려도 되는 글자는 코드에 `.ellipsis-ok` 를 달아 명시한다. 달지 않은 말줄임은 전부 위반이다.
위반은 `종류 | 선택자 경로 | 「앞 40자」 | 폭 크기` 로 나온다. 같은 위반은 처음 나온 조합에서만 자세히 적는다.

## T3 최장 데이터 주입 — `npm run ui:longdata`

`node tests/ui/longdata.mjs` — `data.json` 과 `bundles/*.json` 응답을 `page.route` 로 가로채 문자열 필드를
`longdata.json` 의 같은 분류 최장값으로, 숫자 필드를 최대 자릿수 값으로 바꾼 뒤 T1·T2 와 같은 검사를 한다.
키 이름 → 분류 규칙은 `longdata.mjs` 머리 주석에 있다. 새 최장값은 `longdata.json` 에 더한다.
식별자·주소·날짜류 키와 시계열 배열 안 숫자는 건드리지 않는다. 치환된 값이 0 이면 경고가 나온다.

## T4 길이 상한 — `npm run ui:textlimits`

`python scripts/check_text_limits.py` — 길이는 **표시 폭**(한글 1칸 · 영문·숫자·기호·공백 반 칸, `one_liners.width`)으로 잰다.
상한 표는 그 파일의 `LIMITS` 한 곳(모바일 / PC): 줄임 이름 `shortM` / `short` 8 / 12칸, 이유 한 줄 `reasonShort`·`line.mobile` /
`reason`·`line.pc` 24 / 44칸(+ `scripts/one_liners.py` 의 문장 상수), 버튼 바 항목 6칸 · 7개 이하, 알림 제목 `title_m` / `title` 18 / 30칸.
`one_liners`·`build_bundles` 는 이 표를 가져다 쓴다. 대상 파일이 아직 없으면 「대상 없음」을 찍고 통과한다.

## T5 자동 촬영 — `npm run ui:matrix`

`node tests/ui/matrix.mjs [--baseline <폴더>] [--max-diff 1.0]` — 폭 4 × 테마 2 × 경로를
`tests/ui/out/matrix/<폭>-<테마>-<경로>.png` 로 저장한다(전체 쪽 길이). `--baseline` 이 있으면 같은 이름 파일과
픽셀 차이율(%)을 표로 보고하고, `--max-diff` 를 넘는 파일이 있으면 종료 코드 1이다. 기준 폴더는 이전 촬영 폴더를 복사해 둔 것을 쓴다.
