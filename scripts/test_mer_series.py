import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import fetch_mer_series as S

def test_parse_wareki_reiwa():
    assert S.parse_wareki('R8.9.1') == '2026-09-01'

def test_parse_wareki_heisei():
    assert S.parse_wareki('H31.4.30') == '2019-04-30'

def test_parse_wareki_showa():
    assert S.parse_wareki('S49.9.24') == '1974-09-24'

def test_parse_wareki_invalid():
    assert S.parse_wareki('2026-09-01') is None
    assert S.parse_wareki('') is None
    assert S.parse_wareki(None) is None

MOF_SAMPLE = (
    '基準日別利回り\n'
    '基準日,1年,2年,3年,4年,5年,6年,7年,8年,9年,10年,15年,20年,25年,30年,40年\n'
    'R8.9.1,0.800,0.850,0.900,0.950,1.000,1.050,1.100,1.150,1.200,1.641,-,-,-,4.131,-\n'
    'R8.8.29,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-\n'
    ',,,,,,,,,,,,,,,\n'
)

def test_parse_mof_csv_columns():
    out = S.parse_mof_csv(MOF_SAMPLE)
    assert out['1Y'] == [{'date': '2026-09-01', 'value': 0.8}]
    assert out['10Y'] == [{'date': '2026-09-01', 'value': 1.641}]
    assert out['30Y'] == [{'date': '2026-09-01', 'value': 4.131}]

def test_parse_mof_csv_skips_blank_and_dash():
    # 08-29 행은 전부 '-' 라 어느 텐서에도 값이 생기지 않아야 함. 빈 행은 아예 스킵.
    out = S.parse_mof_csv(MOF_SAMPLE)
    for k in ('1Y', '10Y', '30Y'):
        assert len(out[k]) == 1, (k, out[k])

MOF_CURRENT_SAMPLE = (
    '基準日別利回り\n'
    '基準日,1年,2年,3年,4年,5年,6年,7年,8年,9年,10年,15年,20年,25年,30年,40年\n'
    'R8.9.1,1.527,1.802,1.952,2.14,2.28,2.411,2.559,2.718,2.848,2.987,3.544,3.859,4.143,4.131,4.145\n'
    'R8.9.14,1.553,1.841,1.989,2.17,2.302,2.42,2.547,2.711,2.849,2.988,3.526,3.808,4.065,4.04,4.04\n'
    ',,,,,,,,,,,,,,,\n'
    '※最新のcsvデータが反映されるまで時間がかかる場合があります,,,,,,,,,,,,,,,\n'
)

def test_parse_mof_csv_skips_footer_note_row():
    # 안내문 행은 기준일 열이 연호 형식이 아니라 자동으로 스킵되어야 함(추가 가드 불필요)
    out = S.parse_mof_csv(MOF_CURRENT_SAMPLE)
    assert len(out['30Y']) == 2, out['30Y']

def test_merge_jgb_current_month_wins_same_date():
    base = {'30Y': [{'date': '2026-09-01', 'value': 999.0}]}   # 전량 파일의 낡은/다른 값(가정)
    current = {'30Y': [{'date': '2026-09-01', 'value': 4.131}, {'date': '2026-09-14', 'value': 4.04}]}
    merged = S.merge_jgb(base, current)
    assert merged['30Y'] == [{'date': '2026-09-01', 'value': 4.131}, {'date': '2026-09-14', 'value': 4.04}]

def test_merge_jgb_adds_new_dates_beyond_base():
    base = {'1Y': [{'date': '2026-08-31', 'value': 0.8}]}
    current = {'1Y': [{'date': '2026-09-01', 'value': 0.81}, {'date': '2026-09-14', 'value': 0.82}]}
    merged = S.merge_jgb(base, current)
    assert [e['date'] for e in merged['1Y']] == ['2026-08-31', '2026-09-01', '2026-09-14']

def test_merge_jgb_current_month_missing_falls_back_to_base():
    base = {'30Y': [{'date': '2026-08-31', 'value': 4.09}]}
    merged = S.merge_jgb(base, {})
    assert merged['30Y'] == [{'date': '2026-08-31', 'value': 4.09}]

def test_append_dated_no_duplicate_same_date():
    arr = [{'date': '2026-09-10', 'v': 1}]
    arr = S.append_dated(arr, {'date': '2026-09-10', 'v': 2})
    assert arr == [{'date': '2026-09-10', 'v': 2}]  # 덮어쓰기, 중복 아님

def test_append_dated_appends_new_date():
    arr = [{'date': '2026-09-10', 'v': 1}]
    arr = S.append_dated(arr, {'date': '2026-09-11', 'v': 2})
    assert [e['date'] for e in arr] == ['2026-09-10', '2026-09-11']

def test_append_dated_cap():
    arr = [{'date': f'2026-01-{d:02d}', 'v': d} for d in range(1, 6)]
    arr = S.append_dated(arr, {'date': '2026-01-06', 'v': 6}, cap=3)
    assert [e['date'] for e in arr] == ['2026-01-04', '2026-01-05', '2026-01-06']

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn(); print('ok', name)
    print('ALL PASS')

def test_renormalize_nps_folds_collection_dates_into_as_of():
    """분기 공시를 수집일로 쌓으면 같은 값이 매일 한 건씩 불어난다 — as_of 로 접는다."""
    arr = [{'date': '2026-09-15', 'as_of': '2026-06-01', 'alloc': {'국내주식': 29.1}},
           {'date': '2026-09-16', 'as_of': '2026-06-01', 'alloc': {'국내주식': 29.1}}]
    out = S.renormalize_nps(arr)
    assert len(out) == 1 and out[0]['date'] == '2026-06-01'

def test_renormalize_nps_keeps_entry_without_as_of():
    out = S.renormalize_nps([{'date': '2026-09-16', 'alloc': {'국내주식': 29.1}}])
    assert out == [{'date': '2026-09-16', 'alloc': {'국내주식': 29.1}}]
