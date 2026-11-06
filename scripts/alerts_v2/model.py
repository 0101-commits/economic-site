"""구독 · 편성 · 발송이 주고받는 자료 모양 — 한 곳에."""
from __future__ import annotations

from dataclasses import dataclass, field

# 받는 곳 나누기(2026-11-06 알림 개편 기획 LFW8GXax, P1): 폰 알림 = 경보 · 주의(+ 아침 브리핑), 카톡 = 브리핑만,
# 알림 기록 = 전부. 하루 최대는 경보 · 아침 브리핑을 빼고 센다(사용자 결정 10통). 조용한 시간엔 경보만.
SETTINGS_V = 3                      # 설정 판 — 3 미만 문서는 subscribe.upgrade_prefs 가 한 번 옮긴다(화면 prefsV2 와 같은 규칙)
DEFAULT_SETTINGS = {
    "package": "normal",            # quiet(경보만) | normal(경보 · 주의) | many(경보 · 주의 · 안내)
    "ringChannel": "push",          # 옛 칸 — 읽지 않는다(카톡은 브리핑만, 2026-11-06)
    "dailyCap": 10,                 # 하루 최대 폰 알림(경보 · 아침 브리핑 제외), 넘으면 한 통으로 묶음
    "quiet": {"from": "23:00", "to": "07:00"},
    "quietAlarm": True,             # 조용한 시간에도 경보는 보낸다(나머지는 아침 브리핑에 합류)
    "kakaoQuota": 20,               # 쌍당 일 20(공식) — 브리핑만 보내니 닿지 않는다
    "kakaoBundleAt": 18,
    "briefings": {"morning": True, "close": True, "noon": False, "evening": False, "us": False, "weekly": True},  # 카톡 브리핑 시각
    "families": {f: True for f in "ABCDEFGH"},
    "sv": SETTINGS_V,
}
PACKAGE_CAP = {"quiet": 5, "normal": 10, "many": 15}
OLD_PACKAGE_CAP = {"quiet": 3, "normal": 6, "many": 12}   # 판 2 의 꾸러미 상한 — 그대로 둔 값은 새 상한으로 옮긴다
PACKAGE_BRIEFINGS = {
    "quiet": ("morning",),
    "normal": ("morning", "close", "weekly"),
    "many": ("morning", "close", "noon", "evening", "us", "weekly"),
}
BRIEF_PUSH_SLOTS = ("morning",)     # 폰 알림으로도 가는 브리핑(나머지는 카톡 · 알림 기록만)


@dataclass
class Decision:
    """구독 결과 — 원장 행 하나를 누구에게 어떤 등급으로."""
    row: dict
    level: str                      # alarm | alert | notice | record (사용자 조정 반영)
    ring: bool                      # 울림 대상인가(꾸러미 · 갈래 · 별표 · 조건)
    reason: str = ""                # 「기본 켜짐」 「관심」 「내 조건」 「꾸러미 밖」 …
    cond_id: str | None = None      # 사용자 조건이면 그 id
    on: bool = True                 # 켜진 대상인가(기본 켜짐 · 관심 · 내 설정) — 안내 · 보관도 켜진 것만 나간다
    uid: str | None = None          # 누구의 판정인가(사람 표 uid — 사람별 설정을 못 읽은 런은 None = 마스터)
    role: str | None = None         # owner | member — 카톡 · 공개 원장은 owner 만


@dataclass
class Send:
    """편성 결과 — 발송기가 그대로 보낸다."""
    row: dict
    level: str
    push: bool = False
    kakao: bool = False
    held: bool = False              # 조용한 시간 보류(아침 카드에 합류)
    bundled: bool = False           # 상한 초과 묶음에 들어감
    bundle: list = field(default_factory=list)   # 묶음 통이면 안의 행들
    kind: str = "event"             # event | bundle
    uid: str | None = None          # 받을 사람 — 푸시 큐 항목에 실린다(None = 옛 큐처럼 마스터에게만)

    def __str__(self) -> str:
        ch = "+".join(k for k, v in (("push", self.push), ("kakao", self.kakao)) if v)
        tag = " 보류" if self.held else (" 묶음" if self.bundled else "")
        return f"[{self.level}] {self.row.get('title')} → {ch or '없음'}{tag}"
