"""메르 블로그(ranto28) 최근글 스냅샷 → merblog.json.
   네트워크 실패 시 기존 파일 보존(날조 금지)."""
import os, sys, json, time
import requests
sys.path.insert(0, os.path.dirname(__file__))
import merblog_lib as M

OUT = os.path.join(os.path.dirname(__file__), '..', 'merblog.json')
BLOG_ID = M.BLOG_ID
RECENT_TARGET = 150     # 메타 수집 목표
FULLTEXT_TOP = 20       # 원문 채울 최신 개수
PAGE_SIZE = 30
API_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'
POST_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

def _get(url, ua, referer=None, timeout=15):
    h = {'User-Agent': ua}
    if referer:
        h['Referer'] = referer
    r = requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()
    return r

def fetch_recent(target):
    """post-list 페이징으로 최근글 메타 target개."""
    posts, page = [], 1
    ref = f'https://m.blog.naver.com/{BLOG_ID}'
    while len(posts) < target and page <= 20:
        url = (f'https://m.blog.naver.com/api/blogs/{BLOG_ID}/post-list'
               f'?categoryNo=0&itemCount={PAGE_SIZE}&page={page}')
        data = _get(url, API_UA, ref).json()
        items = (data.get('result') or {}).get('items') or []
        if not items:
            break
        for it in items:
            if not it.get('logNo'):  # logNo 없는 항목은 스킵(.../None URL 방지)
                continue
            posts.append(M.norm_post(it, 'postlist'))
        page += 1
        time.sleep(0.3)
    return posts[:target]

def fill_fulltext(posts, top):
    for p in posts[:top]:
        try:
            url = f'https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={p["logNo"]}'
            html_str = _get(url, POST_UA).text
            p['fullText'] = M.extract_fulltext(html_str)
        except Exception as e:
            print(f'  fulltext 실패 logNo={p["logNo"]}: {e}', file=sys.stderr)
        time.sleep(0.4)
    return posts

def main():
    try:
        posts = fetch_recent(RECENT_TARGET)
        if not posts:
            raise RuntimeError('수집 0건 — 기존 파일 보존')
        posts = fill_fulltext(posts, FULLTEXT_TOP)
    except Exception as e:
        print(f'[fetch_merblog] 실패: {e} — merblog.json 보존', file=sys.stderr)
        return 0  # 커밋 스텝이 기존 파일 유지
    out = {
        'asOf': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime()),
        'blogId': BLOG_ID,
        'blogName': '메르의 블로그',
        'count': len(posts),
        'fullCount': sum(1 for p in posts if p.get('fullText')),
        'posts': posts,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'[fetch_merblog] {out["count"]}개(원문 {out["fullCount"]}) → merblog.json')
    return 0

if __name__ == '__main__':
    sys.exit(main())
