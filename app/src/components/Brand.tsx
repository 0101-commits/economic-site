import { BRAND } from '../lib/brand'

type K = 'mark' | 'word' | 'logo' | 'lockup'

function Svg({ k, className, title, decorative }: { k: K; className?: string; title?: string; decorative?: boolean }) {
  const a = decorative ? { 'aria-hidden': true as const } : { role: 'img' as const, 'aria-label': title ?? 'ECOM' }
  return (
    <svg viewBox={BRAND[k].viewBox} className={className} focusable="false" {...a}>
      <path fill="currentColor" fillRule="evenodd" d={BRAND[k].d} />
    </svg>
  )
}

export function BrandMark({ className, title }: { className?: string; title?: string }) {
  return <Svg k="mark" className={className} title={title} />
}
export function BrandWord({ className, title }: { className?: string; title?: string }) {
  return <Svg k="word" className={className} title={title} />
}
// 마크 + ECOM 한 덩어리(태그라인 없음) — 머리줄용. 줄어들지 않게 shrink-0.
export function BrandLockup({ className, title }: { className?: string; title?: string }) {
  return <Svg k="lockup" className={`shrink-0 ${className ?? ''}`} title={title} />
}
export function BrandLogo({ tagline, className }: { tagline?: boolean; className?: string }) {
  return tagline ? <Svg k="logo" className={className} /> : <BrandLockup className={className} />
}
