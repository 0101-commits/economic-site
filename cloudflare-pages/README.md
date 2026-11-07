# cloudflare-pages — ecom-terminal.pages.dev 넘김 장치

`_worker.js` 하나가 전부다. `https://ecom-terminal.pages.dev/…` 요청을 옛 원본
`https://0101-commits.github.io/economic-site/…` 으로 그대로 넘겨 응답을 돌려준다(GET/HEAD 만,
요청 머리는 accept·accept-language·if-none-match·if-modified-since 만, 원본 리다이렉트는 상대 경로로,
응답에 `X-Robots-Tag: noindex`). 화면(코드)은 GitHub Pages 가 만든다.

**숫자 파일은 배포 없이 저장소에서 바로 내준다(2026-11-07).** `scripts/collect_site.mjs` 허용 목록의 `.json`
(`DATA_FILES` · `DATA_DIRS`)은 ① `github.com/<repo>.git/info/refs`(토큰 없음, 20초 재사용)로 main 최신 커밋 번호를
알아내 ② `raw.githubusercontent.com/<repo>/<번호>/<경로>` 에서 꺼낸다. 안 되면 ③ raw 의 `main` 주소(최대 5분 늦음)
→ ④ GitHub Pages 원본(코드 배포 · 6시간마다 배포분) 차례. 응답 머리 `x-ecom-src` = `repo@번호` · `repo-main (…)` ·
`pages (…)`. watchdog 의 `check_site_lag` 가 사이트 숫자가 저장소보다 30분 넘게 늦으면 #시스템에 알린다.
새 숫자 파일을 화면이 읽게 되면 `collect_site.mjs` 와 `_worker.js` 두 목록에 같이 넣는다(시험이 맞춰 본다).

시험: `node cloudflare-pages/test_proxy.mjs`

## 프로젝트 만들기 (한 번만)

wrangler 의 `pages project create` 는 실패한 사례가 있어 API 로 만든다.

```
POST /accounts/{account_id}/pages/projects
{ "name": "ecom-terminal", "production_branch": "main" }
```

## 배포

```
npx wrangler pages deploy cloudflare-pages --project-name ecom-terminal --branch main
```

실패하면 `--force` 를 붙여 다시 한다.

## 되돌리기

Cloudflare 대시보드 → Pages → ecom-terminal → Deployments 에서 이전 배포를 롤백하거나,
`_worker.js` 를 이전 커밋으로 되돌려 다시 배포한다. 옛 주소(github.io)는 이 장치와 무관하게
계속 열린다.

이 폴더는 `scripts/collect_site.mjs` 의 FORBIDDEN 에 들어 있어 사이트 산출물에 섞이지 않는다.
