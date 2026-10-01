import { SegBar, Card } from '../components/ui'
import { useViewParam } from '../lib/useViewParam'

const ASSETS = [
  { key: 'kr', label: '국내' }, { key: 'global', label: '해외' }, { key: 'fxrate', label: '환율금리' },
  { key: 'commod', label: '원자재' }, { key: 'macro', label: '거시' }, { key: 'flow', label: '수급' }, { key: 'estate', label: '부동산' },
] as const
const VIEWS = [{ key: 'sum', label: '요약' }, { key: 'table', label: '표' }, { key: 'chart', label: '차트' }] as const
type Asset = typeof ASSETS[number]['key']
type View = typeof VIEWS[number]['key']

export default function Market() {
  const [a, setA] = useViewParam<Asset>('a', 'kr', ASSETS.map(o => o.key))
  const [v, setV] = useViewParam<View>('v', 'sum', VIEWS.map(o => o.key))
  return (
    <div className="flex flex-col gap-3">
      <SegBar label="자산군" options={ASSETS} value={a} onChange={setA} />
      <SegBar label="보기" options={VIEWS} value={v} onChange={setV} />
      <Card title={`${ASSETS.find(o => o.key === a)!.label} · ${VIEWS.find(o => o.key === v)!.label}`}>
        <p className="m-0 text-13 text-ink-3">이 자리에 자산군별 첫 블록이 들어옵니다.</p>
      </Card>
    </div>
  )
}
