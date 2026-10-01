import { PinGate } from '../components/PinGate'
import { Card } from '../components/ui'

// 내 자산 자료(보유·평가액)를 읽는 코드는 반드시 Holdings 안에 둔다 — PinGate 가 열기 전엔 만들어지지 않는다.
function Holdings() {
  return (
    <Card title="총평가">
      <p className="m-0 text-13 text-ink-3">이 자리에 총평가 금액이 들어옵니다.</p>
    </Card>
  )
}

export default function My() {
  return <PinGate><Holdings /></PinGate>
}
