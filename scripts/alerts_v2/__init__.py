"""알림 v2 — 사건 사전(events.yml) · 원장(events/) · 등급 · 편성 · 발송.

계약서: docs/superpowers/plans/2026-10-05-alerts-v2.md
기획서: https://claude.ai/artifact/93GornDyzLc6rfrZcu4QXV
"""
LEVELS = ("alarm", "alert", "notice", "record")       # 경보 · 알림 · 안내 · 기록
PACKAGES = ("quiet", "normal", "many")                # 꾸러미
STRENGTHS = ("normal", "big", "huge", "value")        # 2.0σ · 2.5σ · 3.0σ · 직접 값
RUNS = ("light", "full", "settle", "daily", "eve")    # 평가 런
FAMILIES = ("A", "B", "C", "D", "E", "F", "G", "H")   # 급변 · 기록 · 임계 · 수급 · 일정 · 공시 · 렌즈 · 실물
SIGMA = {"normal": 2.0, "big": 2.5, "huge": 3.0}
