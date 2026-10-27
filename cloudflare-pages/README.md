# cloudflare-pages — ecom-terminal.pages.dev 넘김 장치

`_worker.js` 하나가 전부다. `https://ecom-terminal.pages.dev/…` 요청을 옛 원본
`https://0101-commits.github.io/economic-site/…` 으로 그대로 넘겨 응답을 돌려준다(GET/HEAD 만,
요청 머리는 accept·accept-language·if-none-match·if-modified-since 만, 원본 리다이렉트는 상대 경로로,
응답에 `X-Robots-Tag: noindex`). 화면·데이터는 계속 GitHub Pages 가 만든다.

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
