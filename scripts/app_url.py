# -*- coding: utf-8 -*-
"""대시보드 주소 단일 원천 — 알림·카톡·중계 페이지가 모두 여기서 가져온다.

2026-10-27 주소를 github.io 에서 ecom-terminal.pages.dev 로 옮겼다(Cloudflare Pages 가
옛 GitHub Pages 원본을 그대로 넘겨 준다 — cloudflare-pages/README.md).
OLD_URL 은 옛 주소를 알아보는 용도로만 남긴다(링크로 쓰지 말 것).
"""
import os

NEW_URL = "https://ecom-terminal.pages.dev/"
OLD_URL = "https://0101-commits.github.io/economic-site/"
APP_URL = os.environ.get("APP_URL") or NEW_URL


def app_link(query: str = "") -> str:
    """APP_URL 뒤에 쿼리(`?p=market` 등)를 붙인다."""
    return APP_URL + (query or "")
