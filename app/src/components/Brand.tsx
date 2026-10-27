import { BRAND } from '../lib/brand'

type K = 'mark' | 'word' | 'logo'

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
export function BrandLogo({ tagline, className }: { tagline?: boolean; className?: string }) {
  if (tagline) return <Svg k="logo" className={className} />
  return (
    <span role="img" aria-label="ECOM" className={`inline-flex items-center gap-1.5 ${className ?? ''}`}>
      <Svg k="mark" decorative className="h-[22px] w-auto" />
      <Svg k="word" decorative className="h-[15px] w-auto" />
    </span>
  )
}
