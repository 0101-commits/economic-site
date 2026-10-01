import { SegBar, Card } from '../components/ui'
import { useViewParam } from '../lib/useViewParam'

const MODES = [{ key: 'whatif', label: '만약에' }, { key: 'chain', label: '사슬' }, { key: 'flow', label: '흐름' }] as const
type Mode = typeof MODES[number]['key']

export default function Lens() {
  const [m, setM] = useViewParam<Mode>('m', 'whatif', MODES.map(o => o.key))
  return (
    <div className="flex flex-col gap-3">
      <SegBar label="렌즈 모드" options={MODES} value={m} onChange={setM} />
      <Card title={MODES.find(o => o.key === m)!.label}>
        <p className="m-0 text-13 text-ink-3">이 자리에 렌즈 첫 블록이 들어옵니다.</p>
      </Card>
    </div>
  )
}
