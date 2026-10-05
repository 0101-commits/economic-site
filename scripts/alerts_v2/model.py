"""구독 · 편성 · 발송이 주고받는 자료 모양 — 한 곳에."""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_SETTINGS = {
    "package": "normal",            # quiet | normal | many
    "ringChannel": "push",          # kakao | push | both  (카톡 친구 모드가 켜지면 kakao 가 기본)
    "dailyCap": 6,                  # 하루 울림 상한(경보 제외), 넘으면 묶음
    "quiet": {"from": "23:00", "to": "07:00"},
    "quietAlarm": False,            # 경보가 조용한 시간을 뚫는가
    "kakaoQuota": 20,               # 쌍당 일 20(공식), 18부터 묶음
    "kakaoBundleAt": 18,
    "briefings": {"morning": True, "close": True, "noon": False, "evening": False, "us": False, "weekly": True},
    "families": {f: True for f in "ABCDEFGH"},
}
PACKAGE_CAP = {"quiet": 3, "normal": 6, "many": 12}


@dataclass
class Decision:
    """구독 결과 — 원장 행 하나를 누구에게 어떤 등급으로."""
    row: dict
    level: str                      # alarm | alert | notice | record (사용자 조정 반영)
    ring: bool                      # 울림 대상인가(꾸러미 · 갈래 · 별표 · 조건)
    reason: str = ""                # 「기본 켜짐」 「관심」 「내 조건」 「꾸러미 밖」 …
    cond_id: str | None = None      # 사용자 조건이면 그 id


@dataclass
class Send:
    """편성 결과 — 발송기가 그대로 보낸다."""
    row: dict
    level: str
    push: bool = False
    kakao: bool = False
    discord: bool = True
    held: bool = False              # 조용한 시간 보류(아침 카드에 합류)
    bundled: bool = False           # 상한 초과 묶음에 들어감
    bundle: list = field(default_factory=list)   # 묶음 통이면 안의 행들
    kind: str = "event"             # event | bundle

    def __str__(self) -> str:
        ch = "+".join(k for k, v in (("push", self.push), ("kakao", self.kakao), ("discord", self.discord)) if v)
        tag = " 보류" if self.held else (" 묶음" if self.bundled else "")
        return f"[{self.level}] {self.row.get('title')} → {ch or '없음'}{tag}"
