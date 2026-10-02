// 웹 푸시 — 서비스 워커 등록 · 이 기기 구독 · 해제. 서버는 Worker /push/key · /push/subscribe, 발송은 scripts/send_push.py.
// 서비스 워커(public/sw.js)는 푸시 전용이고 캐시를 하지 않는다. 범위 = 이 앱 폴더(/economic-site/next/).
// 동기화 키 해시는 여기 저장하지 않는다 — 부를 때마다 인자로 받은 함수(sync.ts 의 getKeyHash)에서 얻는다.

import { WORKER } from './personal/remote'

/** 동기화 키의 SHA-256 hex. 키가 없으면 null. */
export type GetKeyHash = () => Promise<string | null> | string | null

export const pushSupported = () =>
  typeof navigator !== 'undefined' && 'serviceWorker' in navigator && typeof window !== 'undefined' &&
  'PushManager' in window && typeof Notification !== 'undefined'

/** 서비스 워커를 등록한다. 지원하지 않거나 실패하면 null. */
export async function registerSW(): Promise<ServiceWorkerRegistration | null> {
  if (!pushSupported()) return null
  try { return await navigator.serviceWorker.register(new URL('sw.js', document.baseURI)) } catch { return null }
}

/** 이 기기가 지금 구독 중인지(허락 + 구독 객체가 둘 다 있어야 참). */
export async function pushSubscribed(): Promise<boolean> {
  if (!pushSupported() || Notification.permission !== 'granted') return false
  const reg = await navigator.serviceWorker.getRegistration()
  return !!(await reg?.pushManager.getSubscription())
}

const MSG: Record<number, string> = {
  401: '동기화 키가 맞지 않습니다. 설정에서 다시 넣으세요.',
  429: '요청이 많습니다. 잠시 뒤 다시 하세요.',
  503: '서버에 푸시가 아직 준비되지 않았습니다.',
}
async function call(method: string, path: string, hash: string | null, body?: unknown) {
  const headers: Record<string, string> = {}
  if (hash) headers['X-Sync-Key-Hash'] = hash
  if (body !== undefined) headers['content-type'] = 'application/json'
  const r = await fetch(WORKER + path, { method, headers, cache: 'no-store', body: body === undefined ? undefined : JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(MSG[r.status] ?? `서버 오류(${r.status})`)
  return j
}

const b64uToBytes = (s: string) => {
  const b = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4))
  return Uint8Array.from(b, c => c.charCodeAt(0))
}
const sameKey = (a: ArrayBuffer | null | undefined, b: Uint8Array) =>
  !!a && a.byteLength === b.length && new Uint8Array(a).every((x, i) => x === b[i])

/** 이 기기를 구독해 서버에 저장한다. 실패하면 화면에 그대로 적을 우리말 메시지로 던진다. */
export async function subscribePush(getKeyHash: GetKeyHash): Promise<void> {
  if (!pushSupported()) throw new Error('이 브라우저는 웹 푸시를 지원하지 않습니다.')
  const hash = await getKeyHash()
  if (!hash) throw new Error('설정에서 동기화 키를 먼저 넣으세요.')
  if ((await Notification.requestPermission()) !== 'granted') throw new Error('알림이 막혀 있습니다. 브라우저 사이트 설정에서 허락하세요.')
  if (!(await registerSW())) throw new Error('서비스 워커를 등록하지 못했습니다.')
  const reg = await navigator.serviceWorker.ready
  const { vapidPublicKey } = await call('GET', '/push/key', null)
  const key = b64uToBytes(String(vapidPublicKey || ''))
  let sub = await reg.pushManager.getSubscription()
  // 서버 공개키가 바뀌었으면 옛 구독으로는 발송이 403 이 된다 — 다시 구독한다.
  if (sub && !sameKey(sub.options.applicationServerKey, key)) { await sub.unsubscribe(); sub = null }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }).catch((e: unknown) => {
    console.warn('[push] 구독 실패', e)   // 브라우저 원문(영문)은 콘솔에만
    throw new Error('이 브라우저에서 푸시 구독을 만들지 못했습니다. 시크릿 창이면 일반 창에서 여세요.')
  })
  await call('PUT', '/push/subscribe', hash, sub.toJSON())
}

/** 이 기기 구독을 끊는다. 서버에서 못 지워도 끊긴 주소는 발송기가 410 을 받고 정리한다. */
export async function unsubscribePush(getKeyHash: GetKeyHash): Promise<void> {
  if (!pushSupported()) return
  const sub = await (await navigator.serviceWorker.getRegistration())?.pushManager.getSubscription()
  if (!sub) return
  const hash = await getKeyHash()
  if (hash) await call('DELETE', '/push/subscribe', hash, { endpoint: sub.endpoint }).catch(() => {})
  await sub.unsubscribe()
}
