// 웹 푸시 전용 서비스 워커 — 범위는 이 파일이 있는 폴더(/economic-site/next/).
// 캐시는 하지 않는다. 화면 묶음은 매번 새로 받아야 하므로 fetch 이벤트를 아예 받지 않는다.
// 보내는 쪽: scripts/send_push.py. 내용 모양 = { id, title, body, url, ts }.

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()))

// 알림을 누르면 열 주소. 같은 출처가 아니면 앱 첫 화면으로 둔다(내용이 바뀌어도 남의 사이트로 보내지 않게).
function target(url) {
  const scope = self.registration.scope
  try {
    const u = new URL(url || './', scope)
    return u.origin === self.location.origin ? u.href : scope
  } catch {
    return scope
  }
}

self.addEventListener('push', e => {
  let d = {}
  try { d = e.data ? e.data.json() : {} } catch { d = { body: e.data ? e.data.text() : '' } }
  const title = String(d.title || 'ecom 알림').slice(0, 120)
  e.waitUntil(self.registration.showNotification(title, {
    body: String(d.body || '').slice(0, 400),
    tag: d.id ? String(d.id) : undefined,   // 같은 조건의 알림은 새 것으로 바꿔 쌓이지 않게
    data: { url: target(d.url) },
    icon: new URL('icon.png', self.registration.scope).href,
  }))
})

self.addEventListener('notificationclick', e => {
  e.notification.close()
  const url = (e.notification.data && e.notification.data.url) || self.registration.scope
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const mine = wins.find(w => w.url.startsWith(self.registration.scope))
    if (mine) {
      await mine.focus()
      if (mine.url !== url && 'navigate' in mine) { try { await mine.navigate(url) } catch { /* 제어 밖 창은 navigate 가 막힌다 — 앞으로 가져오기만 */ } }
      return
    }
    await self.clients.openWindow(url)
  })())
})
