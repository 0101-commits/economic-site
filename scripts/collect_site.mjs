// 공개 배포 산출물 수집 + 위생 검사 — .github/workflows/pages.yml 이 부른다.
// 종전(Pages build_type=legacy)은 저장소 루트 전체가 공개 URL 이었다(CLAUDE.md·docs·scripts·tests …).
// 이제 아래 허용 목록만 _site/ 로 복사하고, 금지 패턴이 하나라도 섞이면 배포를 멈춘다.
//
// 목록 = 화면이 실제로 부르는 파일(fetch · <script>/<link> · 로더 · CSS url()). 새 파일을 화면이
// 부르게 되면 여기에 추가해야 사이트에 뜬다(안 하면 404 로 바로 보인다).
// 일부러 뺀 것: alerts_config.json(관심종목·알림 조건 — 화면은 Worker /portfolio 로만 읽는다),
// toss_snapshot.json · mer_series.json · mer_extract_cache.jsonl · halts_state.json ·
// releases_state.json(봇 전용), root-site/(다른 저장소용 원본).
//
// 실행: node scripts/collect_site.mjs   → _site/ 생성, 위반 시 exit 1
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const SITE = path.join(ROOT, '_site');

const FILES = [
  'index.html', 'go.html', 'og-cover.png',
  'data.json', 'data_meta.json', 'merblog.json', 'mer_signals.json',
  'fundamentals.json', 'link_status.json', 'alerts_state.json', 'history.json',
];
// bundles/ = 화면 묶음(scripts/build_bundles.py, fetch-data.yml 이 매 런 만든다) — 새 화면 층이 화면 단위로 읽는 JSON.
const DIRS = { js: ['.js'], css: ['.css', '.woff2'], bundles: ['.json'] };
// 새 화면 층: app/dist(빌드 산출물) → _site/next/. pages.yml 이 이 스크립트보다 먼저 빌드한다.
const APP_DIST = 'app/dist';
const APP_OUT = 'next';
const APP_EXTS = ['.js', '.css', '.html', '.svg', '.png', '.woff2'];   // .png = 푸시 알림 아이콘(app/public/icon.png)

const FORBIDDEN = [
  /\.(md|py|pyc|sql|sh|ps1|bat|ya?ml|toml|jsonc|jsonl|mjs|env|pem|key)$/i,
  /(^|\/)\.(omc|github|claude|git|wrangler|env|dev\.vars)/i,
  /(^|\/)(docs|tests|scripts|node_modules|cloudflare-worker|root-site)\//i,
  /(^|\/)(alerts_config|toss_snapshot|package(-lock)?)\.json$/i,
];
const SECRET = [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, /\bgh[pousr]_[A-Za-z0-9]{36}\b/, /\bgithub_pat_\w{22,}/, /\bAKIA[0-9A-Z]{16}\b/];
const MAX_BYTES = 20 * 1024 * 1024;

const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => {
  const p = path.join(dir, e.name);
  return e.isDirectory() ? walk(p) : [p];
});
const rel = (p, base) => path.relative(base, p).split(path.sep).join('/');

function collect() {
  fs.rmSync(SITE, { recursive: true, force: true });
  const out = [...FILES];
  for (const [dir, exts] of Object.entries(DIRS)) {
    if (dir === 'bundles' && !fs.existsSync(path.join(ROOT, dir))) continue;   // 첫 수집 런 전에는 아직 없다
    out.push(...walk(path.join(ROOT, dir)).map(p => rel(p, ROOT))
      .filter(r => exts.includes(path.extname(r).toLowerCase())));
  }
  for (const r of out) {
    const src = path.join(ROOT, r);
    if (!fs.existsSync(src)) throw new Error(`허용 목록 파일 없음: ${r}`);   // 반쪽 사이트를 올리느니 직전 배포를 둔다
    fs.mkdirSync(path.dirname(path.join(SITE, r)), { recursive: true });
    fs.copyFileSync(src, path.join(SITE, r));
  }
  const dist = path.join(ROOT, APP_DIST);
  if (!fs.existsSync(path.join(dist, 'index.html'))) throw new Error(`${APP_DIST} 없음 — npm run build --prefix app 먼저`);
  const app = walk(dist).map(p => rel(p, dist)).filter(r => APP_EXTS.includes(path.extname(r).toLowerCase()));
  for (const r of app) {
    fs.mkdirSync(path.dirname(path.join(SITE, APP_OUT, r)), { recursive: true });
    fs.copyFileSync(path.join(dist, r), path.join(SITE, APP_OUT, r));
  }
  return out.length + app.length;
}

function check() {
  const bad = [];
  for (const p of walk(SITE)) {
    const r = rel(p, SITE);
    if (FORBIDDEN.some(re => re.test(r))) bad.push(`금지 경로: ${r}`);
    if (fs.statSync(p).size > MAX_BYTES) bad.push(`20MB 초과: ${r}`);
    if (/\.(html|js|json|css)$/i.test(r)) {
      const text = fs.readFileSync(p, 'utf8');
      const hit = SECRET.find(re => re.test(text));
      if (hit) bad.push(`비밀값 의심(${hit.source.slice(0, 24)}…): ${r}`);
    }
  }
  return bad;
}

// 자가 점검 — 금지 패턴이 실제로 막아야 할 것을 막고, 허용 목록은 통과시키는지.
for (const r of ['CLAUDE.md', 'docs/IMPROVEMENTS.md', 'tests/ui/shots.mjs', 'scripts/check_alerts.py',
                 '.omc/state/x.json', 'alerts_config.json', 'x.sql', '.env.local', 'js/README.md']) {
  if (!FORBIDDEN.some(re => re.test(r))) throw new Error(`자가 점검 실패 — 막혀야 함: ${r}`);
}
for (const r of [...FILES, 'js/app1.min.js', 'css/seed/seed.css', 'css/fonts/pretendard/a.woff2', 'bundles/home.json',
                 'next/index.html', 'next/assets/index-a1B2.js', 'next/assets/index-a1B2.css', 'next/sw.js', 'next/icon.png']) {
  if (FORBIDDEN.some(re => re.test(r))) throw new Error(`자가 점검 실패 — 통과해야 함: ${r}`);
}

const n = collect();
const bad = check();
if (bad.length) {
  console.error('배포 위생 검사 실패:\n  - ' + bad.join('\n  - '));
  process.exit(1);
}
console.log(`_site/ 수집 완료 — ${n}개 파일, 위생 검사 통과`);
