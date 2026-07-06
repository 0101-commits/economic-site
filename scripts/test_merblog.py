import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import merblog_lib as M

def test_strip_html():
    got = M.strip_html('8월 <em class="highlight">물가</em>지수&nbsp;발표')
    assert got == '8월 물가지수 발표', repr(got)

def test_strip_html_zerowidth():
    assert M.strip_html('가​나  다') == '가나 다'

def test_extract_fulltext():
    html = ('<html><body><div class="se-main-container">'
            '<p>첫 문단.</p><p>둘째 <b>문단</b>.</p></div>'
            '<div class="wrap_postcomment">댓글영역</div></body></html>')
    got = M.extract_fulltext(html)
    assert '첫 문단.' in got and '둘째 문단.' in got, repr(got)
    assert '댓글영역' not in got, '본문 뒤 위젯은 잘라야 함'
    assert '<' not in got and '>' not in got, 'HTML 파편 누출: ' + repr(got)
    assert not got.strip().startswith('"'), '선행 속성파편 누출: ' + repr(got)

def test_extract_fulltext_none():
    assert M.extract_fulltext('<html><body>no container</body></html>') == ''

def test_norm_post_search():
    raw = {'logNo': 223967469436, 'title': '<em class="highlight">물가</em> 발표',
           'categoryName': '경제', 'addDate': 1783303800000,
           'contents': '발췌 <em>물가</em> 내용'}
    p = M.norm_post(raw, 'search')
    assert p['logNo'] == '223967469436'
    assert p['title'] == '물가 발표'
    assert p['excerpt'] == '발췌 물가 내용'
    assert p['category'] == '경제'
    assert p['url'] == 'https://blog.naver.com/ranto28/223967469436'
    assert p['date'].startswith('2026-07-06T11:10')  # KST

def test_norm_post_postlist():
    raw = {'logNo': 224337546731, 'titleWithInspectMessage': '청년미래적금',
           'categoryName': '경제', 'addDate': 1783303800000,
           'briefContents': '요약문', 'readCount': 12345}
    p = M.norm_post(raw, 'postlist')
    assert p['title'] == '청년미래적금'
    assert p['excerpt'] == '요약문'
    assert p['readCount'] == 12345

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn(); print('ok', name)
    print('ALL PASS')
