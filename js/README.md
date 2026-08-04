# js/ — index.html 앱 스크립트 (옵션 A① 분리)

- `app1.js`(차트·페이지 렌더 본체) → `app2.js`(테마·포트폴리오·AI 브리핑) → `app3.js`(스터디·비교·홈 DnD) → `app4.js`(설정·프리셋·위젯 오류) → `app5.js`(시스템 진단). **로드 순서 = 선언 순서 — 바꾸지 말 것. defer/async/module 금지**(전역 `var` 공유·실행 타이밍 보존, body 끝 로드라 블로킹 무해).
- 파일 수정 시 index.html 의 해당 `?v=` 를 갱신(내용 md5 앞 8자: `python -c "import hashlib;print(hashlib.md5(open('js/app1.js','rb').read()).hexdigest()[:8])"`). 갱신 누락 = 사용자 캐시에 옛 코드.
- 빌드 없음 — 파일이 그대로 배포된다(CSP `script-src 'self'`).
