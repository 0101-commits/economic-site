// 옛 주소(github.io)로 들어온 사람에게만 보이는 안내 띠 — 새 주소로 가는 링크(현재 화면 유지) + 기록 옮기는 법.
// 닫기 없음: 이 기기에만 있던 기록은 옛 주소 저장소에 있어 새 주소로 자동으로 따라가지 않는다.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { movedInfo } from '../lib/moved'

export function MovedBanner() {
  const [how, setHow] = useState(false)
  const { show, newUrl } = movedInfo(location.hostname, location.hash)
  if (!show) return null
  return (
    <div className="bg-card border-b border-line">
      <div role="status" className="mx-auto max-w-[1200px] px-4 py-2 text-13 text-ink-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 flex-1">주소가 ecom-terminal.pages.dev 로 바뀌었습니다. 이 기기에만 있던 기록은 옮겨 가야 합니다.</span>
          <a href={newUrl} className="h-8 px-3 inline-flex items-center rounded-btn text-13 font-bold bg-accent text-on-accent border border-accent no-underline">새 주소로</a>
          <button type="button" aria-expanded={how} onClick={() => setHow(v => !v)} className="h-8 px-3 rounded-btn text-13 border border-line bg-card text-ink-2 hover:text-ink-1 cursor-pointer">기록 옮기는 법</button>
        </div>
        {how && (
          <p className="mt-2 mb-0 text-ink-2">
            이 주소의 <Link to="/settings" className="text-ink-1 underline">설정</Link> 에서 「내 자료 내려받기」 로 파일을 받은 뒤, 새 주소의 설정에서 「내 자료 올리기」 로 올립니다.
          </p>
        )}
      </div>
    </div>
  )
}
