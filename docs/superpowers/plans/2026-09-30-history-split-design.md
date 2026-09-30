# A14 이력 파일 분리 + 하루 1번 스냅샷 보관 — 설계

작성 2026-09-30 · 상태: 설계만(코드 미변경) · 기준 HEAD `1fc9f069` + 작업트리 편집 중 상태

> `scripts/fetch_data.py`·`js/app1.js` 는 이 설계를 쓰는 동안 다른 작업이 편집 중이라 줄 번호가
> 움직인다. **앵커는 함수 이름·코드 모양이 기준**이고, 괄호 속 줄 번호는 작성 시점 작업트리 값이다.

## 0. 결론

- data.json 에서 **`history` 블록 하나만** `history.json` 으로 옮긴다(33계열: fx 5·indices 8·commodities 19(Dubai 포함)·crypto 1).
- data.json 에는 계열마다 **끝 400점(`HISTORY_TAIL = 400`)** 을 남긴다. 60점은 조용한 오류를 낸다(§1.3).
- 1.5MB 목표는 **압축 직렬화**(`separators=(",", ":")`)까지 해야 닿는다. 들여쓰기 유지 시 이력을 통째로 빼도 1.60MB.
- 프런트는 첫 화면을 data.json 만으로 그리고, 직후 `history.json?v=<historyVersion>` 을 한 번 받아
  **날짜 기준으로 꼬리 앞부분만** 이어 붙인다. 겹치는 구간은 data.json(더 새것)이 이긴다.
- history.json 은 **일일 런(AV_FETCH_FULL=1)에서만** 다시 쓴다(+파일 없음·버전 없음 부트스트랩). 캐시가 하루 종일 맞는다.
- 스냅샷은 **GitHub Release `snapshots`** 에 `data-YYYY-MM-DD.json.gz` 로 덮어쓰기 업로드, 400일 보관(약 100MB).
- 부수 발견: 커밋 재시도 루프가 **바뀌지 않은 산출물까지 백업했다가 되돌려 쓰는 기존 결함** — 한 줄 수정 포함(§4).

## 1. 무엇을 옮기고 얼마나 줄어드나 (Q1·Q2)

### 1.1 키별 크기 (실측, 압축 직렬화 기준 json.dumps 길이)

| 키 | 크기 | 비고 |
|---|---|---|
| `history` | 1,706KB(들여쓰기 시 약 3.3MB) | fx/indices/commodities/crypto 5년 일봉, 약 40,700점 |
| `yieldCurve` | 319KB | `series` 약 1년(269점) — 이미 짧음 |
| `economicIndicators` | 241KB | 그중 `.history` 231KB(월·분기, 11,804점) |
| `realestate` | 73KB | 그중 `.history` 64KB |
| `investorTrading` | 36KB | `daily` 400행 |
| `sentiment` | 15KB | 거의 전부 `.history` |

### 1.2 전후 크기

| 구성 | 원본 | gzip |
|---|---|---|
| 현재 data.json (indent=2) | 4.86MB | 461KB |
| 꼬리 400 + 들여쓰기 유지 | 2.63MB | 269KB |
| **꼬리 400 + 압축 직렬화 (권고)** | **1.27MB** | **249KB** |
| history.json (압축, 전체 5년) | 1.54MB | 260KB |
| 참고: 이력 전부 제거 + 들여쓰기 | 1.60MB | 181KB |
| 참고: 꼬리 60 + 들여쓰기 | 1.76MB | 195KB |

이 PC 체크아웃은 CRLF 라 5.09MB 로 보인다. CI(LF) 기준 4.86MB.

**남기는 키와 이유** — `economicIndicators.*.history`·`realestate.*.history`·`sentiment.*.history` 는
`_preserve_indicators_deep`·`_accumulate_short_histories`·VKOSPI 병합이 **직전 data.json 에서** 읽고,
`data_sla`·`check_releases`·`mer_aggregate(map/sentiment)`·`ai_briefing` 도 읽는다. 약 310KB 를 덜려고
이 경로들을 흔들 이유가 없다. `yieldCurve.series`(약 1년)·`investorTrading.daily`(400행)도 유지.

### 1.3 꼬리 길이 = 400 (60 이 안 되는 이유)

| 소비처 | 필요량 | 60점이면 | 400점이면 |
|---|---|---|---|
| `send_kakao_digest.range_pos` (52주 위치) | 365일 안 200점 | `""` 반환 → 52주 문구 조용히 사라짐 | 동일 |
| `discord_card` σ 배지·`anomaly`·`anomalies` (`volatility.zscore`, WINDOW=250·MIN_SAMPLES=60) | 251종가 | σ None 또는 값 변함 | 동일 |
| 프런트 `econRange52` (app1.js 5101) · `applyRealData` KPI 52주 막대(`z.slice(-252)`, ≥60) | 1년 날짜 컷 | **3개월 범위를 "52주"로 표시** | 동일 |
| `mer_aggregate.join_series(close)` → `history_1y` → MRI | 365일 | 1년 차트 3개월로 잘림, MRI 변함 | 동일 |
| `app6.js` 포트폴리오 신호 (`slice(-260)`) | 260점 | 부족 | 동일 |
| BTC (매일봉) | 365점 | 부족 | 400일 충족 |
| `build_weekly_parts`/`_wk_pct`, `daily_series(7)`, `_spark(7)`, `_dc_fields`, `discord_card._hist(30)` | 7~30점 | 정상 | 동일 |
| `validate_data` (KOSPI ≥5, 끝 30점 검사) | 소량 | 정상 | 동일 |
| `data_sla` `_extract_asof`/`infer_cadence`/`_history_dates` | 마지막 날짜·간격 | 정상 | 동일 |
| `merge_newer` (마지막 점 비교·덧붙임) | 끝점 | 정상 | 동일 |
| `fetch_data` VKOSPI `realized20d` (prev 폴백) | 21점 | 정상 | 동일 |
| `build_indicators` (crypto 키 목록) | 키 | 정상 | 동일 |
| `check_alerts`·`check_swings`(야후 closes)·`market_halts`(`marketHalts.history`, 별개)·`watchdog` | data.history 안 읽음 | 무관 | 무관 |

400점이면 **파이썬 소비처 출력이 비트 단위로 같다**(σ 251점·365일 창 모두 400 안). Dubai(월간 69점)는 통째로 남는다.
꼬리는 **개수 규칙**(`v[-400:]`)이라 결정적이고, 프런트는 N 을 몰라도 된다(날짜로 병합) → 값 드리프트 없음.

### 1.4 프런트에서 history.json 이 필요한 화면

| 화면 | 필요량 | 앵커 |
|---|---|---|
| 대시보드 메인 차트 단위 1M·1Q, 사용자 기간 지정 | 36×21=756점 · 20×63=1,260점 | `getPeriodData` (app1.js 3251), `unitDefaultCount` 3214 |
| 글로벌 지수 상세 모달 (기본 period `'all'`) | 5년 | `showGlobalIndexDetail` 3882, `_renderReHistChartIndex` 3909 |
| 환율 화면 2Y·5Y·전체 | 504점~전체 | `sliceByPeriod` 7528 (호출 4920·4939·4966) |
| 전년 비교(YoY) 토글, 표시 구간이 1년 넘게 과거일 때 | 표시+1년 | `yoyFromHistory` 1127, `applyYoY` |
| 포트폴리오 벤치마크(첫 스냅샷이 400거래일보다 오래된 경우) | 가변 | `_pfBenchSeriesDaily` (app2.js 633) |

나머지(카드·스파크라인·52주 범위·1D/1W 차트·원자재 90~252일·금속 90일)는 꼬리만으로 지금과 같다.

## 2. 구현 순서와 코드 조각 (Q2~Q5)

한 PR 로 끝낼 수 있다. 부트스트랩 history.json 을 함께 커밋하면 공백 시간이 없다(§2.4).

### 2.1 수집기 분리 — `scripts/fetch_data.py`

`fetch_all_historical_data`(5568 부근) 옆에 둔다.

```python
# data.json 에 남기는 일봉 수. 소비처 최대 요구: σ 251종가(volatility.WINDOW=250),
# 52주 365일(range_pos·econRange52·mer history1y), BTC 는 매일봉이라 365점.
HISTORY_TAIL = 400


def split_history(d, prev, daily):
    """d["history"](5년)를 history.json(전체) 과 data.json(끝 HISTORY_TAIL점) 으로 나눈다.
    직렬화 직전에 부른다. history.json 은 일일 런·파일 없음·버전 없음일 때만 다시 쓴다."""
    full = d.get("history") or {}
    d["history"] = {c: {k: v[-HISTORY_TAIL:] for k, v in m.items()} for c, m in full.items()}
    hv = (prev or {}).get("historyVersion")
    if full and (daily or not hv or not os.path.exists("history.json")):
        try:
            with open("history.json", encoding="utf-8") as f:
                old = json.load(f).get("history") or {}
        except (OSError, ValueError):
            old = {}
        for c, m in old.items():          # 이번 런에 빠졌거나 크게 짧아진 계열은 직전 파일 유지(5년 차트 보존)
            for k, ov in m.items():
                nv = full.setdefault(c, {}).get(k)
                if not nv or len(nv) < 0.9 * len(ov):
                    full[c][k] = ov
        hv = d["lastUpdated"]
        payload = json.dumps({"lastUpdated": hv, "history": full},
                             ensure_ascii=False, separators=(",", ":"))
        with open("history.json", "w", encoding="utf-8") as f:
            f.write(payload)
    if hv:
        d["historyVersion"] = hv
```

호출: `__main__` 풀 런 경로의 `_payload = json.dumps(d, ...)` **바로 앞**(8675 부근).
이 지점은 `build_data()` 안의 모든 preserve/merge·`_reconcile_history_with_spot`(끝점 동기화)이 끝난 뒤이고,
워크플로의 `Validate data.json` 스텝보다 앞이다.

```python
    split_history(d, _load_prev_data("data.json"),
                  os.environ.get("AV_FETCH_FULL", "").strip() in ("1", "true", "yes"))
```

- 꼬리는 **이번 런의 신선한 이력**으로 먼저 만든다. 직전 파일에서 되살린 계열은 history.json 에만 들어가고
  data.json 꼬리에는 넣지 않는다(오늘 없는 계열 = 없는 대로, 값 날조 금지 원칙 유지).
- 이번 런 이력이 통째로 비면(`full` 빈 dict) history.json 은 그대로 두고 버전만 이월한다.
  그 경우 data.json `history` 가 비어 `validate_data` 가 막는 것은 지금과 같다.
- `run_light_build`(8420 부근)는 **손대지 않는다**. 직전 dict 를 그대로 고쳐 쓰므로 `historyVersion` 이 저절로 이어지고,
  이미 꼬리라 다시 자를 일도 없다.
- 이후 스텝(`mer_aggregate`·`ai_briefing`·`check_releases`)은 꼬리 data.json 을 읽는다 — §1.3 대로 충분.

### 2.2 압축 직렬화 (선택, 1.5MB 목표에는 필수)

`indent=2` → `separators=(",", ":")` 다섯 곳. 하나만 어긋나도 효과가 사라진다
(정상 경로의 마지막 기록자는 `validate_data`, 재시도 경로는 `merge_newer`).

| 파일 | 위치 |
|---|---|
| `scripts/fetch_data.py` | `run_light_build` 의 `_payload = json.dumps(...)` (8605 부근) |
| `scripts/fetch_data.py` | `__main__` 의 `_payload = json.dumps(...)` (8675 부근) |
| `scripts/merge_newer.py` | 75 `payload = json.dumps(merged, ...)` |
| `scripts/validate_data.py` | 211 `json.dump(d, f, ...)` |
| `scripts/ai_briefing.py` | 352 `json.dump(d, f, ...)` |

패리티 테스트로 묶는다(§3.2). 부작용: data.json 줄 단위 diff 가 사라진다(4.86MB 파일은 이미 GitHub 가 diff 를 안 보여 준다).
워크플로는 텍스트 병합을 하지 않으므로(reset + 재적용) 기능 영향은 없다.

### 2.3 워크플로 — `.github/workflows/fetch-data.yml`

1. `history.json` 을 세 목록에 추가:
   - 368 `WATCH="data.json data_meta.json ... releases_state.json"`
   - 380 JSON 무결성 루프 `for f in data.json data_meta.json merblog.json ...`
   - 386 `ARTIFACTS="data.json data_meta.json ... releases_state.json"`
2. 387 백업 루프를 **바뀐 파일만** 백업하도록(§4 기존 결함 수정). untracked(첫 생성) 도 잡히도록 `git status --porcelain` 사용:

```sh
for f in $ARTIFACTS; do [ -f "$f" ] && [ -n "$(git status --porcelain -- "$f")" ] && cp "$f" "/tmp/$f.run" || true; done
```

3. 커밋 스텝 뒤에 스냅샷 스텝(§2.7).

### 2.4 Pages 허용 목록 — `scripts/collect_site.mjs`

21 `FILES` 에 `'history.json'` 추가. `collect()` 는 목록 파일이 없으면 throw 해 배포를 멈춘다
(「허용 목록 파일 없음」). 그래서 **PR 에 부트스트랩 history.json 을 함께 커밋**한다:

```sh
python -c "import json;d=json.load(open('data.json',encoding='utf-8'));open('history.json','w',encoding='utf-8',newline='\n').write(json.dumps({'lastUpdated':d['lastUpdated'],'history':d['history']},ensure_ascii=False,separators=(',',':')))"
```

흐름: PR 머지 푸시 → Pages 배포(부트스트랩 파일로 통과, data.json 에 `historyVersion` 없음 → 프런트는 안 부름)
→ `fetch-data.yml` 의 `on: push paths`(fetch_data.py 변경) 풀 런 → prev 에 버전이 없으니 history.json 재작성 +
꼬리 data.json + `historyVersion` → 그 런 완료(workflow_run)로 Pages 재배포 → 프런트가 history.json 을 받는다.
data.json·history.json 은 같은 Pages 산출물로 **원자적으로** 배포된다.

### 2.5 프런트 로더 — `js/app1.js`

새 코드는 `loadRealData`(13589) 앞에 둔다.

```js
// 이력 분리(A14) — data.json 은 계열마다 끝 400점, 그 이전은 history.json.
// 겹치는 구간은 data.json 꼬리가 이긴다(더 새것). 꼬리 길이를 몰라도 날짜로 병합되므로 N 드리프트 없음.
window._historyFull = null;
function _mergeHistoryInto(d) {
  const full = window._historyFull;
  if (!full || !d || !d.history) return;
  Object.keys(full).forEach(cat => {
    const dc = d.history[cat] = d.history[cat] || {};
    Object.keys(full[cat]).forEach(k => {
      const tail = dc[k] || [];
      if (!tail.length) return;            // 이번 런에 없는 계열은 없는 대로 둔다
      dc[k] = full[cat][k].filter(p => p.date < tail[0].date).concat(tail);
    });
  });
}
let _histTried = null;
function loadHistoryData(ver) {
  if (!ver || _histTried === ver) return;  // 버전당 1회. 실패해도 재시도 폭주 없음(다음 버전에 재시도)
  _histTried = ver;
  fetch('./history.json?v=' + encodeURIComponent(ver))
    .then(r => r.ok ? r.json() : null)
    .then(h => {
      if (!h || !h.history) return;
      window._historyFull = h.history;
      window._lastRealDataTs = null;       // 캐시된 data.json 을 다시 적용 → 병합 + 활성 화면 재렌더(기존 경로 재사용)
      return loadRealData().then(() => {
        const k = _reHistState.key || '', m = document.getElementById('reHistoryChartModal');
        if (k.indexOf('__index_') === 0 && m && m.style.display === 'flex') _renderReHistChartIndex(k.slice(8));
      });
    })
    .catch(() => {});
}
```

`loadRealData` 안 훅 두 줄:

| 위치 | 넣을 것 | 이유 |
|---|---|---|
| 13616 `const data = await r.json();` 바로 뒤 | `_mergeHistoryInto(data);` | `applyRealData` 가 `history` 를 카테고리 단위 얕은 병합(`{...prev[k], ...v}`)해 새 꼬리가 전체를 덮는다. 갱신마다 다시 붙여야 긴 차트가 안 줄어든다. `applyRealData` 보다 먼저라 KOSPI 해시·`mainAllData` 도 전체 계열로 계산된다. |
| 활성 화면 재렌더 블록 끝(13638 `page-investor` 분기 뒤, try 안) | `loadHistoryData(data.historyVersion);` | 첫 화면을 그린 뒤 미리 받기. `historyVersion` 이 없으면(롤아웃 전) 아무것도 안 한다. |

동작 메모
- 두 번째 `loadRealData()` 는 `data.json?v=<lastUpdated>` 가 브라우저 HTTP 캐시(Pages `max-age=600`)에서 나와 네트워크가 없다. 재파싱 1.27MB(수십 ms 이하).
- 재진입 시 `loadHistoryData(같은 버전)` 은 `_histTried` 로 즉시 반환 → 루프 없음.
- `getHistoricalSeries`(7495)·`econRange52`·app2/app3/app6 의 `d.history` 직접 읽기는 수정 불필요 — 병합된 `_latestDataForIndicators.history` 를 그대로 본다.
- 호출 시점을 **필요 시점**이 아니라 **첫 화면 직후**로 권하는 이유: 첫 화면인 대시보드가 이미 1M·1Q 단위를 제공하고, 필요 시점 방식은 훅 4곳(`getPeriodData` 1M/1Q/사용자기간, `sliceByPeriod` 2Y/5Y/all, `showGlobalIndexDetail`, `applyYoY` on) + 모달·YoY 재렌더 코드가 더 든다. 모바일 데이터가 더 중요하면 `navigator.connection.saveData` 일 때만 필요 시점 방식으로 돌리는 선택지가 있다.
- CSP `connect-src 'self'` 안이라 추가 허용 불필요. min 파일은 `build-frontend.yml` 이 재생성(로컬 UI 게이트 전에는 수동 재생성).

### 2.6 검증·문서

- `scripts/validate_data.py`: **막지 않는 경고**만 추가(약 8줄). history.json 파싱 가능 / KOSPI ≥ 1,000점 / `d["historyVersion"] == history.json.lastUpdated` 패리티.
  깨진 history.json 은 커밋 스텝 무결성 루프가 `git checkout HEAD -- history.json` 으로 제외한다(목록 추가 후).
- `scripts/data_sla.py`: **변경 없음**. `infer_cadence`·`_extract_asof` 는 꼬리의 간격·마지막 날짜로 충분(일간 판정, TRADING_DAY_PATHS 동일).
- `CLAUDE.md` Data Pipeline 절 + Key Files 표: history.json·`HISTORY_TAIL`·`historyVersion`·「400점보다 긴 이력이 필요한 새 소비처는 history.json 을 읽는다」 약 6줄.

### 2.7 일일 스냅샷 — GitHub Release asset (권고)

| 선택지 | 판단 |
|---|---|
| **Release `snapshots` asset** | 기존 `permissions: contents: write` 로 가능, 저장소 크기 무영향, 지우기 쉬움. data.json 은 이미 Pages 공개 파일이라 새 노출 없음. **채택** |
| `snapshots/` 폴더 커밋 | 연 약 90MB 가 git 이력에 영구 누적, 얕은 체크아웃마다 최신 트리 100MB. 기각 |
| Actions artifact | 공개 저장소 보존 한도 90일. 기각 |
| Cloudflare R2 | 새 시크릿·바인딩·코드. 과함 |

커밋 스텝(`Commit and push data.json`) 뒤:

```yaml
      # 📦 일일 스냅샷 — 그날 마지막 일일 런(KST 22:05)의 data.json 이 남는다(--clobber 덮어쓰기).
      #    400일 보관(약 100MB). 실패해도 데이터 커밋은 이미 끝났으므로 런을 실패로 만들지 않는다.
      - name: 일일 스냅샷 보관 (Release asset)
        if: github.event.client_payload.mode == 'daily'
        continue-on-error: true
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          D=$(TZ=Asia/Seoul date +%F); CUT=$(TZ=Asia/Seoul date -d '400 days ago' +%F)
          gh release view snapshots >/dev/null 2>&1 || gh release create snapshots \
            --title "일일 스냅샷" --notes "data-YYYY-MM-DD.json.gz = 그날 마지막 일일 런의 data.json" --prerelease
          gzip -9 -c data.json > "data-$D.json.gz"
          gh release upload snapshots "data-$D.json.gz" --clobber
          gh release view snapshots --json assets -q '.assets[].name' | while read -r n; do
            d=${n#data-}; d=${d%.json.gz}
            [[ "$d" < "$CUT" ]] && gh release delete-asset snapshots "$n" -y || true
          done
```

- 스냅샷은 data.json 만. 꼬리 400점으로 1.6년 차트까지 재현되고, 그보다 오래된 구간은 불변이라 **현재 history.json** 으로 채운다
  (보관 400일 안 스냅샷의 5Y 뷰는 왼쪽 끝이 최대 400일 비는 정도).
- `GITHUB_TOKEN` 으로 만든 태그·릴리스는 다른 워크플로를 깨우지 않는다. `--prerelease` 라 「Latest」 표시 안 됨.
- 크기: 약 250KB × 400 = 약 100MB.

**그날 화면 재현 (지금 가능한 방법, 코드 불필요)**

```sh
git worktree add ../econ-replay $(git rev-list -1 --before="2026-09-30 23:59 +0900" main)   # 그날 코드
gh release download snapshots -p data-2026-09-30.json.gz -O - | gunzip > ../econ-replay/data.json
cp history.json ../econ-replay/                                                              # 오래된 구간은 불변
cd ../econ-replay && python -m http.server 8000
```

브라우저 안 재현(후속): Worker 에 `/snapshot?d=YYYY-MM-DD` 경로(릴리스 asset 서버 측 조회 + CORS) +
`loadRealData` 가 `?asof=` 를 받아 데이터 URL 교체·자동 갱신 중지. 릴리스 다운로드는 CORS 헤더 없이
리다이렉트된다고 보고 Worker 경유로 설계했다(**미실측**).

## 3. 위험과 게이트 (Q6)

### 3.1 위험

- **경량 런(FETCH_LIGHT)**: history.json 을 쓰지 않고 이력을 다시 자르지도 않는다. `historyVersion` 은 직전 dict 로 이어진다. 위험 없음.
- **merge_newer**: data.json 꼬리 위에서 끝점 비교·덧붙임만 한다(꼬리가 401점이 될 수 있으나 무해). history.json 은 `ARTIFACTS` 재적용으로 복원된다.
- **재시도 루프 기존 결함 1 (스크립트 판독, 미실측)**: 387 백업 루프가 바뀌지 않은 산출물까지 `/tmp/*.run` 으로 백업하고
  reset 뒤 되돌려 쓴다. 경량 런이 재시도하면 그 사이 풀 런이 올린 merblog.json·mer_signals.json·mer_series.json·fundamentals.json
  (그리고 앞으로 history.json)이 옛것으로 되돌아간다. §2.3 의 한 줄로 막는다.
- **재시도 루프 기존 결함 2 (A14 범위 밖, 보고만)**: 풀 런의 `lastUpdated` 는 빌드 **시작** 시각이라, 경량 런이 풀 런 푸시 뒤에
  재시도하면 `merge_newer` 가 경량 런(옛 바탕 + 시세)을 통째로 채택해 풀 런의 지표·뉴스가 다음 풀 런까지 사라진다.
  해법 방향: 경량 런 재시도는 origin 을 바탕으로 경량 시세 잎만 덮는다.
  A14 는 이 결함에도 안전하다 — 버전 불일치는 캐시 키만 바꾸고, 내용 정합은 날짜 병합 규칙이 지킨다.
- **캐시(Pages CDN)**: `max-age=600`. `?v=historyVersion` 은 하루 최대 3번 바뀌므로 거의 적중. 옛 버전 URL 에 새 내용이 와도
  무해(history.json 에서는 꼬리보다 오래된 점만 가져온다).
- **모바일 데이터**: 첫 방문 data.json 249KB + history.json 260KB = 약 509KB(지금 461KB 대비 약 +10%, 꼬리 중복분).
  탭 상시 오픈 갱신은 461KB → 249KB/회, history.json 은 하루 최대 3회. 첫 화면 파싱 4.86MB → 1.27MB.
- **롤아웃 순서**: §2.4 부트스트랩으로 404·꼬리 공백 시간 없음. 부트스트랩을 빼면 첫 Pages 배포가 한 번 실패한다(직전 배포 유지, watchdog 경보 가능).
- **작은 경합**: history.json 도착 전에 연 지수 모달은 도착 뒤 한 번 다시 그린다(§2.5 코드 포함).
  포트폴리오 화면은 재렌더 목록에 없어, 첫 스냅샷이 400거래일보다 오래된 경우 벤치마크가 다음 진입 때 채워진다.
- **직렬화 형식 드리프트**: 기록자 5곳 — 패리티 테스트로 고정(§3.2).

### 3.2 게이트

기존(분리된 data.json 으로 그대로 통과해야 함):
- `python -m pytest scripts/tests/test_history_acc.py` — 지표 짧은 이력 누적 테스트. 분리 대상 아님 → 무영향 확인용
- `python -m pytest scripts/tests/test_merge_newer.py scripts/tests/test_mer_aggregate.py`
- 실제 data.json 을 읽는 것: `test_discord_card.py`·`test_kakao_cards.py`·`test_card_layout.py`·`test_readability.py`·`test_alert_redesign.py`
- `python scripts/data_sla.py --demo` + 분리 전후 `python scripts/data_sla.py` 요약 동일
- `python scripts/validate_data.py`
- `node scripts/collect_site.mjs` (history.json 포함 확인)
- `python -m pytest scripts/tests/test_watchdog.py` (워크플로 이름 불변)
- `tests/ui/firstload.mjs`·`structure.mjs`·`components.mjs`·`readability2.mjs`·`uxgates.mjs` — **한 번에 하나씩**(메모리)

신규:
- `scripts/tests/test_history_split.py`
  1. `split_history` — data.json 꼬리 ≤ 400점, history.json 전체, 끝점 일치
  2. 빠진·크게 짧아진 계열은 직전 history.json 것 유지, data.json 꼬리엔 안 들어감
  3. 비일일 런은 `historyVersion` 이월·history.json 미변경 / 일일 런은 갱신 / 버전 없음이면 부트스트랩
  4. **동등성**: 실제 data.json 을 메모리에서 분리해 `range_pos`·`discord_card.anomaly`/`anomalies`/배지·`_wk_pct`·mer `history_1y` 가 분리 전후 동일
  5. **형식 패리티**: data.json 을 쓰는 5곳이 같은 separators 를 쓴다(소스 문자열 검사)
- `tests/ui/firstload.mjs` 확장: `**/history.json*` 을 4초 지연 → 도착 뒤 지수 모달이 1,000점 넘게 그리는지,
  history.json 404 일 때 콘솔 오류 없이 꼬리만으로 그리는지

### 3.3 변경량 추정

| 파일 | 변경 |
|---|---|
| `scripts/fetch_data.py` | +약 25줄(상수·`split_history`·호출 1줄), 직렬화 2곳 |
| `js/app1.js` | +약 30줄(병합·로더·모달 재렌더), 훅 2줄 |
| `.github/workflows/fetch-data.yml` | 목록 3줄, 백업 1줄, 스냅샷 스텝 약 16줄 |
| `scripts/validate_data.py` | 경고 약 8줄, 직렬화 1곳 |
| `scripts/merge_newer.py` · `scripts/ai_briefing.py` · `scripts/collect_site.mjs` | 각 1줄 |
| `scripts/tests/test_history_split.py` | 신규 약 50줄 |
| `tests/ui/firstload.mjs` | +약 15줄 |
| `CLAUDE.md` | +약 6줄 |
| `history.json` | 부트스트랩 생성 파일(코드 아님) |

합계 10개 파일, 추가 약 150줄, 수정 약 10줄.
