// T1 넘침 · T2 잘림 게이트 — 기획안 v4 10장 「화면 품질 게이트」.
// 실행: node tests/ui/overflow.mjs [--url http://127.0.0.1:5173/next/] [--paths "/,/market"]
//        [--widths 360,390,768,1440] [--themes light,dark] [--allow ".a,.b"] [--wait 2500]
//   주소는 환경변수 UI_URL 로도 받는다. 기존 사이트는 --url http://127.0.0.1:8080/ .
// 검사(폭 × 테마 × 경로마다)
//   ① 문서 scrollWidth > clientWidth 0건
//   ② 보이는 요소 중 scrollWidth > clientWidth+1 이고 overflow 가 visible 인 것 0건
//   ③ text-overflow:ellipsis 가 실제로 적용돼 잘린 요소 0건
//   ④ 숫자 글자([\d,.\-▲▼%]+ 만)가 두 줄로 꺾인 요소 0건
// 경로: 새 화면 층(5173)은 _lib.mjs 의 NEXT_PATHS — 홈 · 시장 · 렌즈 · 내 자산 · 알림(받은 알림 · 사건 · 채널) · 지표 상세(벨 시트 닫힘 · 연 채로).
// 허용: .ellipsis-ok 와 그 자손, 가로 스크롤 컨테이너 안쪽, --allow 로 준 선택자.
// 종료 코드: 위반 또는 실행 오류가 있으면 1.
import { sweep, report } from './_lib.mjs';

process.exit(report(await sweep(), 'overflow'));
