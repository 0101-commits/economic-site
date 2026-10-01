import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = fileURLToPath(new URL('..', import.meta.url))

// 개발 서버 전용: 저장소 루트의 자료를 배포 때와 같은 주소 모양으로 내준다.
// 배포에서는 /economic-site/next/ 의 한 단계 위(../data.json · ../bundles/ · ../css/fonts/)에 실제 파일이 있다.
const TYPES: Record<string, string> = { '.json': 'application/json', '.css': 'text/css', '.woff2': 'font/woff2' }
function repoData(): Plugin {
  return {
    name: 'repo-data',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url || '').split('?')[0])
        if (url.includes('..') || !/^\/(data\.json|bundles\/[\w.-]+\.json|css\/fonts\/[\w./-]+)$/.test(url)) return next()
        const file = path.join(REPO, url)
        if (!fs.existsSync(file)) { res.statusCode = 404; res.end(); return }
        res.setHeader('Content-Type', TYPES[path.extname(file)] || 'application/octet-stream')
        fs.createReadStream(file).pipe(res)
      })
    },
  }
}

// 배포 산출물에만 보안 정책을 넣는다(개발 서버는 React 새로고침용 인라인 스크립트가 있어 막히면 안 된다).
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self'",
  "img-src 'self' data:",
  "connect-src 'self' https://ecom-dashboard-proxy.e-hcg.workers.dev",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-src 'none'",
].join('; ')
const csp: Plugin = {
  name: 'csp',
  apply: 'build',
  transformIndexHtml: () => [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' }],
}

export default defineConfig(({ command }) => ({
  // 배포 주소가 /economic-site/next/ 라서 빌드는 상대 경로로 둔다. 개발 서버는 /next/ 에서 같은 모양으로 연다.
  base: command === 'build' ? './' : '/next/',
  plugins: [react(), tailwindcss(), repoData(), csp],
  build: { outDir: 'dist', emptyOutDir: true },
}))
