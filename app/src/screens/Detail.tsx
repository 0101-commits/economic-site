import { useParams } from 'react-router-dom'
import { SegBar, Card } from '../components/ui'
import { useViewParam } from '../lib/useViewParam'

const PERIODS = [{ key: '1d', label: '1일' }, { key: '1w', label: '1주' }, { key: '1m', label: '1달' }, { key: '1y', label: '1년' }, { key: '5y', label: '5년' }] as const
type Period = typeof PERIODS[number]['key']

export default function Detail() {
  const { id = '' } = useParams()
  const [p, setP] = useViewParam<Period>('p', '1m', PERIODS.map(o => o.key))
  return (
    <div className="flex flex-col gap-3">
      <h1 className="m-0 text-24 font-bold ellipsis-ok">{id}</h1>
      <SegBar label="기간" options={PERIODS} value={p} onChange={setP} />
      <Card><p className="m-0 text-13 text-ink-3">이 자리에 지표 상세가 들어옵니다.</p></Card>
    </div>
  )
}
