import { useState } from 'react'
import { SegBar, Card } from '../components/ui'
import { applyTheme, readTheme, type Theme } from '../lib/theme'
import { lock } from '../lib/pin'

const THEMES = [{ key: 'system', label: '기기 설정' }, { key: 'light', label: '밝게' }, { key: 'dark', label: '어둡게' }] as const

export default function Settings() {
  const [t, setT] = useState<Theme>(readTheme)
  const [locked, setLocked] = useState(false)
  return (
    <div className="flex flex-col gap-3">
      <Card title="화면">
        <SegBar label="화면 밝기" options={THEMES} value={t} onChange={k => { setT(k); applyTheme(k) }} />
      </Card>
      <Card title="잠금">
        <button type="button" onClick={() => { lock(); setLocked(true) }}
          className="h-8 px-3 rounded-btn text-13 bg-accent text-on-accent border border-accent">지금 잠그기</button>
        {locked && <p className="mt-2 mb-0 text-12 text-ink-3">잠갔습니다. 내 자산을 열면 PIN 을 묻습니다.</p>}
      </Card>
    </div>
  )
}
