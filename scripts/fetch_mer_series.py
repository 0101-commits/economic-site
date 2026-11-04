"""메르 리스크 렌즈 — 공백 시계열 4종(JGB 1/10/30Y·NPS·SCFI 등 운임·LME 재고) → mer_series.json.
   개별 항목 실패 시 기존 값 보존(날조 금지). 전체 실패해도 exit 0."""
import os, sys, re, csv, json
from datetime import datetime, timedelta, timezone, date
import requests

KST = timezone(timedelta(hours=9))
ROOT = os.path.join(os.path.dirname(__file__), '..')
OUT = os.path.join(ROOT, 'mer_series.json')
DATA_JSON = os.path.join(ROOT, 'data.json')

MOF_ALL_URL = 'https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv'  # 전월까지 전량
MOF_CUR_URL = 'https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv'           # 당월분(all 에는 없음)
JGB_TENORS = {'1年': '1Y', '10年': '10Y', '30年': '30Y'}
JGB_MAX = 400          # 최근 400영업일만 보관(원본이 권위 있는 전량 파일이라 누적 불필요)
SERIES_CAP = 800       # 자가축적 배열 상한

_ERA_BASE = {'S': 1925, 'H': 1988, 'R': 2018}  # 쇼와/헤이세이/레이와 원년 서기 환산


def parse_wareki(s):
    """일본 연호 날짜(예: 'R8.9.1', 'H31.4.30', 'S49.9.24') → 'YYYY-MM-DD'. 불인식 시 None."""
    if not isinstance(s, str):
        return None
    m = re.match(r'^\s*([SHR])(\d+)\.(\d+)\.(\d+)\s*$', s)
    if not m:
        return None
    era, n, mo, dd = m.groups()
    y = _ERA_BASE[era] + int(n)
    try:
        return date(y, int(mo), int(dd)).isoformat()
    except ValueError:
        return None


def parse_mof_csv(text):
    """MOF 국채금리 CSV 전문(디코드된 str, 1행=제목/2행=헤더/3행~=데이터)
       → {'1Y': [{date,value}...], '10Y': [...], '30Y': [...]} (빈 값/'-' 행은 해당 열만 스킵)."""
    lines = text.splitlines()
    if len(lines) < 3:
        return {}
    header = next(csv.reader([lines[1]]))
    col_idx = {key: header.index(jp) for jp, key in JGB_TENORS.items() if jp in header}
    out = {k: [] for k in JGB_TENORS.values()}
    for line in lines[2:]:
        if not line.strip():
            continue
        row = next(csv.reader([line]))
        if not row:
            continue
        d = parse_wareki(row[0])
        if not d:
            continue
        for key, idx in col_idx.items():
            if idx >= len(row):
                continue
            raw = row[idx].strip()
            if not raw or raw == '-':
                continue
            try:
                val = float(raw)
            except ValueError:
                continue
            out[key].append({'date': d, 'value': val})
    return {k: v[-JGB_MAX:] for k, v in out.items()}


def _fetch_csv_text(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content.decode('shift_jis', errors='replace')


def merge_jgb(base, current):
    """날짜 기준 병합 — 같은 날짜는 `current`(당월분) 값이 이긴다. 병합 후 최근 400영업일 유지."""
    out = {}
    for k in JGB_TENORS.values():
        by_date = {e['date']: e['value'] for e in (base.get(k) or [])}
        by_date.update({e['date']: e['value'] for e in (current.get(k) or [])})
        out[k] = sorted(({'date': d, 'value': v} for d, v in by_date.items()),
                         key=lambda e: e['date'])[-JGB_MAX:]
    return out


def fetch_jgb():
    """jgbcm_all.csv(전월까지 전량, 권위 소스) + jgbcm.csv(당월분, all 에는 없음) 병합.
       all 실패 = 전체 실패(과거 400영업일을 보장 못 함 → 상위에서 기존 값 보존).
       당월분만 실패하면 전량 파일 결과만으로 진행."""
    base = parse_mof_csv(_fetch_csv_text(MOF_ALL_URL))
    try:
        current = parse_mof_csv(_fetch_csv_text(MOF_CUR_URL))
    except Exception as e:
        print(f'[fetch_mer_series] jgbcm(당월) 실패: {e} — 전량 파일로 진행', file=sys.stderr)
        current = {}
    return merge_jgb(base, current)


def _today_kst():
    return datetime.now(KST).strftime('%Y-%m-%d')


def append_dated(arr, entry, cap=SERIES_CAP):
    """entry['date'] 가 이미 있으면 덮어쓰기, 없으면 append. 날짜순 정렬 후 상한 적용."""
    arr = [e for e in (arr or []) if e.get('date') != entry.get('date')]
    arr.append(entry)
    arr.sort(key=lambda e: e.get('date') or '')
    return arr[-cap:]


def renormalize_nps(arr):
    """과거분 보정 — 수집일로 쌓인 NPS 항목을 as_of(분기 기준일) 키로 되돌려 중복을 접는다."""
    out = {}
    for e in arr or []:
        if not isinstance(e, dict):
            continue
        d = e.get('as_of') or e.get('date')
        out[d] = {**e, 'date': d}
    return [out[k] for k in sorted(out) if k]


_LME_FIELDS = [('Copper', 'LME_Cu_cash'), ('Aluminum', 'LME_Al_cash'), ('Zinc', 'LME_Zn_cash'),
               ('Nickel', 'LME_Ni_cash'), ('Lead', 'LME_Pb_cash'), ('Tin', 'LME_Sn_cash')]   # fetch_data._LME_FIELDS 와 같은 차례
LME_BACKFILL_DAYS = 365


def _lme_year_rows(field, year, get=requests.get):
    """Westmetall 연도 표 → [(YYYY-MM-DD, 재고 톤)]. 4번째 열이 재고(fetch_data.fetch_lme_inventory 와 같은 파싱)."""
    from bs4 import BeautifulSoup
    r = get('https://www.westmetall.com/en/markdaten.php',
            params={'action': 'table', 'field': field, 'year': year},
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}, timeout=20)
    r.raise_for_status()
    table = BeautifulSoup(r.text, 'html.parser').find('table')
    out = []
    for tr in (table.find_all('tr') if table else []):
        tds = [td.get_text(strip=True) for td in tr.find_all('td')]
        if len(tds) < 4:
            continue
        try:
            d = datetime.strptime(tds[0], '%d. %B %Y').date()
            out.append((d.isoformat(), round(float(tds[3].replace(',', '')))))
        except (ValueError, IndexError):
            continue
    return out


def backfill_lme(arr, today=None, get=requests.get):
    """LME 재고 자가축적이 1년이 안 되면 Westmetall 연도 표(올해 · 작년)로 앞을 채운다.

    2026-09 중순에야 쌓기 시작해 메르 렌즈 차트가 두 달치뿐이었다. 1년이 차면 다시 부르지 않는다(금속 6 × 2해 = 12콜, 한 번).
    이미 있는 날짜의 값은 건드리지 않는다 — 날마다 쌓은 값이 원본이고 표는 빈 날만 메운다.
    """
    today = today or datetime.now(KST).date()
    floor = (today - timedelta(days=LME_BACKFILL_DAYS)).isoformat()
    dates = sorted(e.get('date') for e in arr or [] if e.get('date'))
    # 창 끝이 주말 · 휴장이면 첫 거래일이 floor 보다 며칠 뒤라 — 여유 7일을 둬야 다 찬 뒤 매 런 12콜을 다시 하지 않는다
    if dates and dates[0] <= (today - timedelta(days=LME_BACKFILL_DAYS - 7)).isoformat():
        return arr
    by_date = {e['date']: dict(e.get('items') or {}) for e in arr or [] if e.get('date')}
    got = 0
    for name, field in _LME_FIELDS:
        for year in (today.year - 1, today.year):
            try:
                for d, stock in _lme_year_rows(field, year, get=get):
                    if d >= floor:
                        by_date.setdefault(d, {}).setdefault(name, stock)
                        got += 1
            except Exception as e:
                print(f'[fetch_mer_series] LME 백필 {name} {year} 실패: {e}', file=sys.stderr)
    if not got:
        return arr
    merged = [{'date': d, 'items': by_date[d]} for d in sorted(by_date)]
    print(f'[fetch_mer_series] LME 백필 {got}칸 → {len(merged)}일', file=sys.stderr)
    return merged[-SERIES_CAP:]


def merge_freight(arr, items, today=None):
    """운임 항목을 **각자의 기준일** 행에 싣는다. 종전엔 첫 항목(SCFI, 주간) 날짜 한 행에 전 항목을 넣고 행째 덮어
    BDI 같은 일간 지수가 주간 날짜에 붙은 채 매 런 덮이고 일간 이력이 안 쌓였다(2026-11-04 검토). 같은 날 같은 지수는 새 값이 이긴다."""
    by = {}
    for it in items or []:
        if it.get('code') and it.get('price') is not None:
            by.setdefault(it.get('date') or today or _today_kst(), {})[it['code']] = it['price']
    for d, vals in by.items():
        ex = next((e for e in arr if e.get('date') == d), None)
        if ex is None:
            arr = append_dated(arr, {'date': d, 'items': vals})
        else:
            ex.setdefault('items', {}).update(vals)
    return arr


def backfill_freight_prev(arr, items):
    """운임 항목의 직전 주 값(SSE /currentIndex 의 lastContent)으로 빠진 주를 메운다. 있는 값은 안 바꾼다."""
    for it in items or []:
        pv = it.get('prev')
        if not (it.get('code') and isinstance(pv, dict) and pv.get('date') and pv.get('price') is not None):
            continue
        ex = next((e for e in arr if e.get('date') == pv['date']), None)
        if ex is None:
            arr = append_dated(arr, {'date': pv['date'], 'items': {it['code']: pv['price']}})
        else:
            ex.setdefault('items', {}).setdefault(it['code'], pv['price'])
    return arr


def _default():
    return {'jgb': {'1Y': [], '10Y': [], '30Y': []}, 'npsAllocation': [], 'freight': [], 'lmeInventory': []}


def load_existing():
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding='utf-8') as f:
                d = json.load(f)
                for k, v in _default().items():
                    d.setdefault(k, v)
                return d
        except (OSError, ValueError):
            pass
    return _default()


def main():
    out = load_existing()

    try:
        out['jgb'] = fetch_jgb() or out['jgb']
    except Exception as e:
        print(f'[fetch_mer_series] jgb 실패: {e} — 기존 값 보존', file=sys.stderr)

    try:
        with open(DATA_JSON, encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        print(f'[fetch_mer_series] data.json 로드 실패: {e} — 자가축적 3종 건너뜀', file=sys.stderr)
        d = None

    if d is not None:
        try:
            alloc = {a['asset']: a['pct'] for a in ((d.get('nps') or {}).get('allocation') or []) if a.get('asset')}
            if alloc:
                as_of = (d.get('nps') or {}).get('as_of')
                entry = {'date': as_of or _today_kst(), 'as_of': as_of, 'alloc': alloc}
                out['npsAllocation'] = append_dated(renormalize_nps(out['npsAllocation']), entry)
        except Exception as e:
            print(f'[fetch_mer_series] npsAllocation 실패: {e} — 기존 값 보존', file=sys.stderr)

        try:
            items = (d.get('freight') or {}).get('items') or []
            out['freight'] = merge_freight(out['freight'], items)
            out['freight'] = backfill_freight_prev(out['freight'], items)
        except Exception as e:
            print(f'[fetch_mer_series] freight 실패: {e} — 기존 값 보존', file=sys.stderr)

        try:
            lme = (d.get('lmeInventory') or {}).get('data') or []
            litems = {it['name']: it.get('cur') for it in lme if it.get('name')}
            ldate = (d.get('lmeInventory') or {}).get('as_of') or _today_kst()
            if litems:
                out['lmeInventory'] = append_dated(out['lmeInventory'], {'date': ldate, 'items': litems})
        except Exception as e:
            print(f'[fetch_mer_series] lmeInventory 실패: {e} — 기존 값 보존', file=sys.stderr)

    try:
        out['lmeInventory'] = backfill_lme(out['lmeInventory'])
    except Exception as e:
        print(f'[fetch_mer_series] LME 백필 실패: {e} — 기존 값 보존', file=sys.stderr)

    out['asOf'] = datetime.now(KST).strftime('%Y-%m-%dT%H:%M:%S+09:00')
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    j30 = out['jgb'].get('30Y') or []
    print(f"[fetch_mer_series] jgb.30Y latest={j30[-1] if j30 else None} "
          f"nps={len(out['npsAllocation'])} freight={len(out['freight'])} "
          f"lme={len(out['lmeInventory'])} → mer_series.json")
    return 0


if __name__ == '__main__':
    sys.exit(main())
