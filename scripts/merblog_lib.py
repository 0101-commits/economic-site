"""메르 블로그(ranto28) 파싱·정규화 순수 함수. 네트워크 없음(테스트 가능)."""
import re, html
from datetime import datetime, timezone, timedelta

BLOG_ID = 'ranto28'
KST = timezone(timedelta(hours=9))

def POST_URL(log_no):
    return f'https://blog.naver.com/{BLOG_ID}/{log_no}'

def strip_html(s):
    if not s:
        return ''
    # 블록 레벨 태그(단락 경계)는 공백으로 치환해 단어가 붙지 않게 하고,
    # 인라인 태그(em/b/span 등 서식용)는 그냥 제거한다(공백 삽입 시 단어가 쪼개짐).
    s = re.sub(r'</?(p|div|br|li|ul|ol|h[1-6]|tr|table)[^>]*>', ' ', s, flags=re.I)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = s.replace('​', '')                 # 제로폭공백(네이버 본문 다수)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def extract_fulltext(html_str):
    if not html_str:
        return ''
    # script/style 제거
    html_str = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html_str, flags=re.S | re.I)
    m = re.search(r'se-main-container', html_str)
    if not m:
        return ''
    body = html_str[m.end():]
    # 본문 뒤 페이지 위젯 절단(댓글·공감·추천·푸터)
    body = re.split(r'wrap_postcomment|area_sympathy|post_footer|revenue_share|floating_menu', body)[0]
    return strip_html(body)[:20000]

def _kst_iso(add_ms):
    if not add_ms:
        return None
    dt = datetime.fromtimestamp(int(add_ms) / 1000, tz=KST)
    return dt.strftime('%Y-%m-%dT%H:%M:%S+09:00')

def norm_post(raw, source):
    log_no = str(raw.get('logNo'))
    if source == 'postlist':
        title = strip_html(raw.get('titleWithInspectMessage') or raw.get('title'))
        excerpt = strip_html(raw.get('briefContents') or raw.get('contents'))
    else:  # search
        title = strip_html(raw.get('title'))
        excerpt = strip_html(raw.get('contents') or raw.get('briefContents'))
    rc = raw.get('readCount')
    return {
        'logNo': log_no,
        'title': title,
        'date': _kst_iso(raw.get('addDate')),
        'category': raw.get('categoryName') or '',
        'excerpt': excerpt,
        'url': POST_URL(log_no),
        'readCount': int(rc) if isinstance(rc, (int, float)) or (isinstance(rc, str) and rc.isdigit()) else None,
    }
