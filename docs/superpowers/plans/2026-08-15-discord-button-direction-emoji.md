# 디스코드 버튼 방향 이모지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 디스코드 알림 링크 버튼 라벨에 방향 이모지(`📈/📉/⏫/⏬/➖`)를 붙여 방향·강도를 스캔 없이 읽히게 한다. 카카오 경로는 건드리지 않는다.

**Architecture:** 공통 헬퍼 `direction_emoji(c)` + `dir_label(name, c)` 를 `notify_discord.py`(모든 발신 스크립트가 이미 import 하는 공용 모듈)에 단일 정의하고, 각 발신 지점의 라벨 생성만 교체한다. `notify_discord.send()`·웹훅 폴백·카드 렌더러·버튼 배열(행/열·URL)은 무변경.

**Tech Stack:** Python 3.11 (GitHub Actions), 표준 라이브러리만. 테스트는 repo 관행대로 pytest 없이도 `python scripts/tests/test_x.py` 로 실행 가능한 형태.

## Global Constraints

- **디스코드 전용** — 카카오톡 발송 경로(`kakao.send_memo`, 카카오 메시지 형식) 변경 금지 (사용자 지시).
- **E2 강도 표준 공유** — `≥ +2.0` → `⏫`, `≤ -2.0` → `⏬`, `|c| < 0.05` 또는 `None` → `➖`, 그 외 `📈`/`📉`.
- **라벨 형식 단일 규칙** — `{이모지} {이름}{퍼센트}`, 퍼센트는 보합(`➖`)이면 생략, 아니면 ` {c:+.1f}%`.
- 기존 `▲/▼` 텍스트 마커는 제거(이모지로 대체). 버튼 라벨 ≤ 80자 제한.
- **행/열 배열·URL·딥링크 무변경** — 다이제스트 4열 그리드(≤5행), 유틸 행, 마감 nav 1행.
- `notify_discord.send()`·웹훅 폴백("바로가기" 필드 변환)·`discord_card` 카드 로직 무변경 — 라벨이 그대로 전달되므로 폴백에도 이모지 유지.
- 헬퍼는 `notify_discord`에 **단일 정의**, 발신 스크립트에서 복제하지 않음.
- Python 3.11 (workflow), 추가 의존성 없음. 테스트는 `python -m pytest scripts/tests/test_x.py` **또는** `python scripts/tests/test_x.py` 로 실행 가능해야 함.

---

### Task 1: `direction_emoji`/`dir_label` 헬퍼 + 단위 테스트

**Files:**
- Modify: `scripts/notify_discord.py:37` (BOT_NAME 아래, NAVER_LINKS 주석 블록 앞)
- Create: `scripts/tests/test_direction_emoji.py`

**Interfaces:**
- Produces: `notify_discord.direction_emoji(c) -> str`, `notify_discord.dir_label(name, c) -> str` — 이후 모든 Task 가 사용.

- [ ] **Step 1: 헬퍼를 `notify_discord.py`에 추가**

`BOT_NAME = "ecom"` (L37) 바로 아래, `# ── 네이버 증권 딥링크` 주석 블록(L39) 앞에 삽입:

```python
# ── 버튼 라벨 방향 이모지(기획 2026-08-15) ────────────────────────────────
# 디스코드 네이티브 버튼은 색/이미지가 고정이라 방향·강도를 라벨 이모지로 표현.
# E2 표준(±2%) 임계를 공유 — 텍스트 embed 의 _dc_intensity 와 같은 판정.

def direction_emoji(c):
    """등락률 → 방향 이모지. None/|c|<0.05=➖(보합), ±2% 이상=⏫/⏬, 그 외 📈/📉."""
    try:
        c = float(c)
    except (TypeError, ValueError):
        return "➖"
    if abs(c) < 0.05:
        return "➖"
    if c >= 2.0:
        return "⏫"
    if c <= -2.0:
        return "⏬"
    return "📈" if c > 0 else "📉"


def dir_label(name, c):
    """버튼 라벨 — 이모지 + 이름 + 등락률(보합·무데이터는 퍼센트 생략).

    예: dir_label("코스피", 1.8) == "📈 코스피 +1.8%"
        dir_label("구리", None)  == "➖ 구리"
    """
    emoji = direction_emoji(c)
    pct = "" if emoji == "➖" else f" {c:+.1f}%"
    return f"{emoji} {name}{pct}"
```

- [ ] **Step 2: 테스트 파일 작성**

`scripts/tests/test_direction_emoji.py`:

```python
"""direction_emoji / dir_label 회귀 테스트 — 디스코드 버튼 라벨 방향 이모지.

실행: python -m pytest scripts/tests/test_direction_emoji.py  (또는 python scripts/tests/test_direction_emoji.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from notify_discord import direction_emoji, dir_label  # noqa: E402


def test_flat_and_missing():
    assert direction_emoji(None) == "➖"
    assert direction_emoji(0.0) == "➖"
    assert direction_emoji(0.049) == "➖"
    assert direction_emoji(-0.049) == "➖"


def test_normal_direction():
    assert direction_emoji(0.05) == "📈"
    assert direction_emoji(1.9) == "📈"
    assert direction_emoji(-0.05) == "📉"
    assert direction_emoji(-1.9) == "📉"


def test_intensity_threshold_e2():
    assert direction_emoji(2.0) == "⏫"
    assert direction_emoji(3.5) == "⏫"
    assert direction_emoji(-2.0) == "⏬"
    assert direction_emoji(-3.5) == "⏬"


def test_non_numeric_falls_back_flat():
    assert direction_emoji("1.8") == "📈"
    assert direction_emoji("abc") == "➖"


def test_dir_label_has_emoji_name_pct():
    assert dir_label("코스피", 1.8) == "📈 코스피 +1.8%"
    assert dir_label("S&P500", 2.0) == "⏫ S&P500 +2.0%"
    assert dir_label("코스닥", -2.3) == "⏬ 코스닥 -2.3%"


def test_dir_label_omits_pct_when_flat():
    assert dir_label("구리", None) == "➖ 구리"
    assert dir_label("나스닥", -0.04) == "➖ 나스닥"
    assert dir_label("N 삼성전자", 0.8) == "📈 N 삼성전자 +0.8%"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
            print(f"ok {_n}")
    print("OK: direction_emoji / dir_label")
```

- [ ] **Step 3: 테스트 실행 — 실패 확인 (신규 파일이므로 실패 확인은 생략 가능, 실행만으로 통과 확인)**

Run: `python scripts/tests/test_direction_emoji.py`
Expected: `OK: direction_emoji / dir_label`

- [ ] **Step 4: 모듈 docstring의 E2 표준 줄 갱신**

`scripts/notify_discord.py` L19:
```python
등락 강도(E2): ±2% 미만 ▲/▼ · 이상 ⏫/⏬ (변환은 send_kakao_digest._dc_intensity).
```
→
```python
등락 강도(E2): ±2% 미만 ▲/▼ · 이상 ⏫/⏬ (텍스트 embed 는 send_kakao_digest._dc_intensity,
  버튼 라벨은 direction_emoji / dir_label).
```

- [ ] **Step 5: Commit**

```bash
git add scripts/notify_discord.py scripts/tests/test_direction_emoji.py
git commit -m "feat: 디스코드 버튼 라벨 방향 이모지 헬퍼 direction_emoji/dir_label"
```

---

### Task 2: 다이제스트·마감·유틸 버튼 라벨 교체

**Files:**
- Modify: `scripts/send_kakao_digest.py:1316-1347` (`_dc_buttons`, `_dc_button_rows`)
- Modify: `scripts/send_kakao_digest.py:1409-1410` (`_send_close_report` nav)
- Create: `scripts/tests/test_dc_button_labels.py`

**Interfaces:**
- Consumes: `notify_discord.dir_label(name, c)` (Task 1)
- Produces: 다이제스트 그리드·마감 nav·유틸 행의 이모지 라벨. 행/열 개수와 URL은 기존과 동일.

- [ ] **Step 1: `_dc_buttons` 이모지 보강**

L1316-1319:
```python
def _dc_buttons():
    """다이제스트·마감 리포트 공통 버튼(E3) — 봇 토큰 있을 때만 실제로 붙는다."""
    return [("대시보드", DASHBOARD_URL), ("시장 지표", DASHBOARD_URL + "?p=market"),
            ("🔄 지금 시세", "id:refresh_quotes")]
```
→
```python
def _dc_buttons():
    """다이제스트·마감 리포트 공통 버튼(E3) — 봇 토큰 있을 때만 실제로 붙는다."""
    return [("🌐 대시보드", DASHBOARD_URL), ("📊 시장 지표", DASHBOARD_URL + "?p=market"),
            ("🔄 지금 시세", "id:refresh_quotes")]
```

- [ ] **Step 2: `_dc_button_rows` 라벨 교체**

L1340-1341:
```python
        arrow = "" if chg is None else (" ▲" if chg > 0 else " ▼") + f"{abs(chg):.1f}%"
        cur.append((f"{ko}{arrow}", url))
```
→
```python
        cur.append((notify_discord.dir_label(ko, chg), url))
```

- [ ] **Step 3: `_send_close_report` nav 라벨 교체**

L1409-1410:
```python
            arrow = "" if c is None else (" ▲" if c > 0 else " ▼") + f"{abs(c):.1f}%"
            nav.append((f"{lab}{arrow}", u))
```
→
```python
            nav.append((notify_discord.dir_label(lab, c), u))
```
(이 함수는 이미 `notify_discord.NAVER_LINKS`를 쓰므로 `import notify_discord`가 존재함 — 확인만.)

- [ ] **Step 4: 통합 테스트 작성**

`scripts/tests/test_dc_button_labels.py`:

```python
"""_dc_button_rows / _dc_buttons 라벨 통합 테스트 — 방향 이모지 + 4열 배열 유지.

실행: python -m pytest scripts/tests/test_dc_button_labels.py  (또는 python scripts/tests/test_dc_button_labels.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import discord_card  # noqa: E402  (matplotlib 는 지연 import — import 만으로는 안전)
import send_kakao_digest as skd  # noqa: E402


def _slot(ko):
    for ko_, en, cat, key in discord_card._ASSETS:
        if ko_ == ko:
            return cat, key
    raise AssertionError(f"asset not found: {ko}")


def _digest_data():
    data = {}
    for ko, chg in (("코스피", 1.8), ("코스닥", -2.3), ("S&P500", 2.0),
                    ("나스닥", -0.04), ("구리", None)):
        cat, key = _slot(ko)
        data.setdefault(cat, {})[key] = {"change": chg}
    return data


def test_digest_row_labels_have_direction_emoji():
    rows = skd._dc_button_rows(_digest_data())
    flat = [lab for row in rows for lab, _ in row]
    assert "📈 코스피 +1.8%" in flat
    assert "⏬ 코스닥 -2.3%" in flat
    assert "⏫ S&P500 +2.0%" in flat
    assert "➖ 나스닥" in flat
    assert "➖ 구리" in flat


def test_digest_grid_is_4_columns_with_util_row():
    rows = skd._dc_button_rows(_digest_data())
    assert len(rows) >= 2
    for row in rows[:-1]:
        assert len(row) == 4
    assert rows[-1] == [("🌐 대시보드", skd.DASHBOARD_URL),
                        ("📊 시장 지표", skd.DASHBOARD_URL + "?p=market"),
                        ("🔄 지금 시세", "id:refresh_quotes")]


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
            print(f"ok {_n}")
    print("OK: _dc_button_rows / _dc_buttons")
```

- [ ] **Step 5: 테스트 실행**

Run: `python scripts/tests/test_dc_button_labels.py`
Expected: `OK: _dc_button_rows / _dc_buttons`

- [ ] **Step 6: Commit**

```bash
git add scripts/send_kakao_digest.py scripts/tests/test_dc_button_labels.py
git commit -m "feat: 다이제스트·마감 버튼 라벨에 방향 이모지 적용"
```

---

### Task 3: 급변 속보 버튼 라벨 교체

**Files:**
- Modify: `scripts/check_swings.py:120-124` (`_btns`)

**Interfaces:**
- Consumes: `notify_discord.dir_label(name, c)` (Task 1)
- Produces: 급변 버튼 라벨 — `{이모지} N {이름} {등락률}`. `_btns[0]`("주식시장")은 무변경.

- [ ] **Step 1: 라벨 교체**

L120-124:
```python
        _btns = [("주식시장", "https://0101-commits.github.io/economic-site/?p=equity")]
        for _, _, nm, sym, _, pct, _ in hits[:4]:
            u = notify_discord.NAVER_LINKS.get(_sym2key.get(sym))
            if u:
                _btns.append((f"N {nm} {'▲' if pct > 0 else '▼'}{abs(pct):.1f}%", u))
```
→
```python
        _btns = [("주식시장", "https://0101-commits.github.io/economic-site/?p=equity")]
        for _, _, nm, sym, _, pct, _ in hits[:4]:
            u = notify_discord.NAVER_LINKS.get(_sym2key.get(sym))
            if u:
                _btns.append((notify_discord.dir_label(f"N {nm}", pct), u))
```

- [ ] **Step 2: 문법/import 확인**

Run: `python -m py_compile scripts/check_swings.py`
Expected: exit 0, no output.

- [ ] **Step 3: Commit**

```bash
git add scripts/check_swings.py
git commit -m "feat: 급변 속보 버튼 라벨에 방향 이모지 적용"
```

---

### Task 4: 시장중단 경보 버튼 라벨 교체

**Files:**
- Modify: `scripts/check_halts.py:99-110` (`_halt_buttons`)

**Interfaces:**
- Consumes: `notify_discord` (기존 import 그대로)
- Produces: `_halt_buttons(h) -> list[tuple[str, str]] | None` — 방향(direction) 기반 이모지. 라벨: `📊 시장 지표`, `{📈/📉/➖} N {시장}`.

- [ ] **Step 1: 라벨 교체**

L99-110:
```python
def _halt_buttons(h):
    """v3 — 발동 시장 지수의 네이버 증권 버튼(+시장 지표 딥링크). 실패는 None."""
    try:
        import notify_discord
        btns = [("시장 지표", "https://0101-commits.github.io/economic-site/?p=market")]
        key = "KOSDAQ" if h.get("market") == "KOSDAQ" else "KOSPI"
        u = notify_discord.NAVER_LINKS.get(key)
        if u:
            btns.append((f"N {h.get('market') or 'KOSPI'}", u))
        return btns
    except Exception:
        return None
```
→
```python
def _halt_buttons(h):
    """v3 — 발동 시장 지수의 네이버 증권 버튼(+시장 지표 딥링크). 실패는 None."""
    try:
        import notify_discord
        emoji = {"up": "📈", "down": "📉"}.get(h.get("direction"), "➖")
        btns = [("📊 시장 지표", "https://0101-commits.github.io/economic-site/?p=market")]
        key = "KOSDAQ" if h.get("market") == "KOSDAQ" else "KOSPI"
        u = notify_discord.NAVER_LINKS.get(key)
        if u:
            btns.append((f"{emoji} N {h.get('market') or 'KOSPI'}", u))
        return btns
    except Exception:
        return None
```

- [ ] **Step 2: 단위 테스트 추가**

`scripts/tests/test_direction_emoji.py` 마지막에 추가:

```python
def test_halt_buttons_direction_emoji():
    import check_halts
    down = check_halts._halt_buttons({"market": "KOSPI", "direction": "down"})
    assert down[0][0] == "📊 시장 지표"
    assert any(lab == "📉 N KOSPI" for lab, _ in down)
    up = check_halts._halt_buttons({"market": "KOSDAQ", "direction": "up"})
    assert any(lab == "📈 N KOSDAQ" for lab, _ in up)
    unknown = check_halts._halt_buttons({"market": "KOSPI"})
    assert any(lab.startswith("➖") for lab, _ in unknown)
```

- [ ] **Step 3: 테스트 실행**

Run: `python scripts/tests/test_direction_emoji.py`
Expected: `OK: direction_emoji / dir_label` (추가 테스트 포함 통과)

- [ ] **Step 4: Commit**

```bash
git add scripts/check_halts.py scripts/tests/test_direction_emoji.py
git commit -m "feat: 시장중단 경보 버튼 라벨에 방향 이모지 적용"
```

---

### Task 5: 문서 갱신 + 전체 검증

**Files:**
- Modify: `CLAUDE.md` (Key Files 표의 `scripts/notify_discord.py` 행)

**Interfaces:**
- Consumes: Task 1~4 의 모든 변경.

- [ ] **Step 1: CLAUDE.md 갱신**

Key Files 표에서:
```
| `scripts/notify_discord.py` | Discord webhook parallel channel (secret `DISCORD_WEBHOOK_URL`; digest/alerts/swings 병행 발송, 미설정 시 no-op) |
```
→
```
| `scripts/notify_discord.py` | Discord webhook parallel channel (secret `DISCORD_WEBHOOK_URL`; digest/alerts/swings 병행 발송, 미설정 시 no-op). 버튼 라벨 방향 이모지 `direction_emoji`/`dir_label` (E2 표준 ±2%) |
```

- [ ] **Step 2: 전체 테스트 실행**

Run: `python scripts/tests/test_direction_emoji.py; python scripts/tests/test_dc_button_labels.py`
Expected: 두 파일 모두 `OK:` 출력, exit 0.

- [ ] **Step 3: 전체 변경 파일 검토**

Run: `git diff --stat origin/main; git status --short`
Expected: 변경 파일 = `scripts/notify_discord.py`, `scripts/send_kakao_digest.py`, `scripts/check_swings.py`, `scripts/check_halts.py`, `scripts/tests/test_direction_emoji.py`, `scripts/tests/test_dc_button_labels.py`, `CLAUDE.md` 만.

- [ ] **Step 4: 라이브 환경 테스트 발송 (선택 — 워크플로)**

- 디스코드 실제 발송 확인: `Actions → kakao-daily.yml → Run workflow` (다이제스트/마감 버튼 라벨) 및 `halts-test.yml`/급변 테스트 (급변·경보 버튼 라벨). 시크릿이 필요하므로 로컬에선 건너뛴다.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: notify_discord 방향 이모지 헬퍼 문서화"
```