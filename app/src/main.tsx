import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ROOT } from './lib/bundle'
import { applyTheme, readTheme } from './lib/theme'
import { startSync } from './lib/personal/sync'
import './styles/app.css'

applyTheme(readTheme())
// 기기 간 동기화: 이 탭에 키 해시가 있으면 서버 내용을 받고 바뀐 것을 올린다(lib/personal/sync.ts)
startSync()

// 서체: 현행 사이트가 자체 호스팅하는 Pretendard(dynamic subset)를 그대로 불러 캐시를 같이 쓴다.
// index.html 에 적으면 Vite 가 글꼴 92벌을 dist 에 다시 복사하므로 여기서 붙인다.
const font = document.createElement('link')
font.rel = 'stylesheet'
font.href = new URL('css/fonts/pretendard-variable.css', ROOT).href   // 자료와 같은 사이트 루트(첫 주소·next/ 어디서 열려도)
document.head.appendChild(font)

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
