# js/ — index.html 앱 스크립트 (옵션 A① 분리 + B1 minify)

- `app1.js`(차트·페이지 렌더 본체) → `app2.js`(테마·포트폴리오·AI 브리핑) → `app3.js`(스터디·비교·홈 DnD) → `app4.js`(설정·프리셋·위젯 오류) → `app5.js`(시스템 진단). **로드 순서 = 선언 순서 — 바꾸지 말 것. defer/async/module 금지**(전역 `var` 공유·실행 타이밍 보존, body 끝 로드라 블로킹 무해).
- **?v= 수동 갱신은 폐지** — index.html 하단 로더가 dev(localhost)에서는 `appN.js?v=Date.now()`(항상 최신), 프로덕션에서는 `appN.min.js?v=BUILD_V` 를 로드한다.
- `appN.min.js` 와 `BUILD_V` 는 `.github/workflows/build-frontend.yml` 이 `js/app*.js` push 시 자동 생성·커밋한다. **min 파일을 손으로 편집하지 말 것** — 원본(appN.js)만 수정하면 된다.
- 로컬에서 min 경로를 확인하려면 `?bundle=1`. 로컬 재빌드: `npx esbuild js/appN.js --minify --charset=utf8 --target=es2017 --outfile=js/appN.min.js`.
- 파일별 개별 minify 유지 — 5개는 독립 스크립트 파싱 단위라 하나로 합치면(cat) 경계가 붕괴할 수 있다.
