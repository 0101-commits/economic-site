import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import check_notices as cn

HTML = """<a href="/m">홈</a><a href="javascript:x">메뉴 바로가기 이동</a>
<a href="/n/1" onclick="fnDetailView(this)"><b>API 도메인 변경 안내</b> 2026-09-01</a>
<a href="/n/2" onclick="fnDetailView(this)">정기 점검 안내 드립니다</a>
<a href="/other">서비스 소개 페이지</a>"""


def test_parse_hint_and_links():
    t = cn.parse_titles(HTML, "https://x.kr", hint="fnDetailView")
    assert [i["title"] for i in t] == ["API 도메인 변경 안내 2026-09-01", "정기 점검 안내 드립니다"]
    assert t[0]["link"] == "https://x.kr/n/1"
    assert len(cn.parse_titles(HTML)) == 4      # 힌트 없으면 한 단어 메뉴만 빠진다


def test_new_items_baseline_and_diff():
    items = [{"title": "a b c d e f", "link": ""}, {"title": "g h i j k l", "link": ""}]
    assert cn.new_items(None, items) == []       # 첫 실행은 기준선만
    assert cn.new_items({"titles": ["a b c d e f"]}, items) == items[1:]
    assert cn.digest(items) == cn.digest(list(items)) != cn.digest(items[:1])


def test_keyword_filter():
    c = [{"title": "API 도메인 변경 안내"}, {"title": "설문조사 참여 안내"}, {"title": "Endpoint Deprecation"}]
    assert [x["title"] for x in cn.keyword_filter(c)] == ["API 도메인 변경 안내", "Endpoint Deprecation"]


def test_format_message_and_fallback_footer():
    body, title = cn.format_message([{"org": "KOSIS", "title": "점검", "link": "http://l", "url": "u"}], False)
    assert title == "📋 원천 공지 감시 — 영향 후보 1건"
    assert body.startswith("KOSIS · 점검 · http://l") and "키워드 필터만" in body
    assert "키워드" not in cn.format_message([{"org": "A", "title": "t", "url": "u"}], True)[0]


def test_no_gemini_key_uses_keywords(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cn, "STATE", str(tmp_path / "s.json"))
    monkeypatch.setattr(cn, "NOTICE_SOURCES", [("T", "https://t.kr/x", None)])
    (tmp_path / "s.json").write_text('{"T": {"titles": ["예전 공지 제목 입니다"]}}', encoding="utf-8")
    monkeypatch.setattr(cn, "fetch", lambda u: '<a href="/1">주소 변경 안내 드립니다</a><a href="/2">설문 조사 안내 입니다</a>')
    called = []
    monkeypatch.setattr(cn, "gemini_pick", lambda *a: called.append(1))
    cn.main(dry=True)
    assert not called
