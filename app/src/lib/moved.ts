// 옛 주소(github.io)로 들어온 사람에게 새 주소를 알리는 띠의 판단 — 컴포넌트 밖에 둬서 시험할 수 있게 했다.
export const OLD_HOST = '0101-commits.github.io'
export const NEW_URL = 'https://ecom-terminal.pages.dev/'

export function movedInfo(hostname: string, hash: string): { show: boolean; newUrl: string } {
  return { show: hostname === OLD_HOST, newUrl: NEW_URL + (hash || '') }
}
