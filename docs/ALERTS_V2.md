# 알림 v2 운영서 — 사건 사전 · 원장 · 등급 · 카톡 · 편성표

기획서: https://claude.ai/artifact/93GornDyzLc6rfrZcu4QXV · 계약서: `docs/superpowers/plans/2026-10-05-alerts-v2.md`

## 한눈에

```
수집 런 ─▶ 사건 추출기(scripts/alerts_v2/run.py --mode …)
             사전 events.yml × 번들 값 → 원장 events/YYYY-MM-DD.json(멱등) + events/latest.json(7일)
             └ ALERTS_V2=1 이면: 구독(subscribe) → 편성(schedule) → 발송(deliver: 푸시 · 카톡 · 디스코드)
화면: app 받은 알림 = events/latest.json · 사건 탭 = app/src/lib/alerts/dict.json(사전 내보내기)
```

| 런 | 어디서 | 언제(KST) | 사건 |
|---|---|---|---|
| light | `stock-alerts.yml` | 평일 09:00~15:59 · 22:00~06:59 매분(값은 5분) | A1~A3 급변 · A5 서킷 · B2 마디 · U1 · U2 |
| full | `fetch-data.yml` 풀 런 끝 | 매시 :11 | A4 BTC · C1~C8 임계 · 단계 · E2 결과 · E3 · E4 · G2~G5 |
| daily | `fetch-data.yml` 일일 런 끝 | 09:15 · 16:20 · 22:15 | D5 · E5 · F1 · F2 · G1 · H1~H4 + 이력 적재(history_sink) |
| settle | `alerts-v2.yml` | 평일 18:05 | D1~D4 수급 확정 · B1 52주 |
| eve | `alerts-v2.yml` | 매일 21:00 | E1 발표 전날 예고 |
| brief | `briefing.yml` | 07:30 · 16:30 · 토 09:00(+선택 12:00 · 18:30 · 22:40) | 브리핑 6슬롯 |

등급 `alarm`(경보 · 즉시 · @everyone) / `alert`(알림 · 하루 상한 6 · 조용한 시간 보류) / `notice`(안내 · 디스코드 · 마감 카드 묶음) / `record`(화면만).
꾸러미 `quiet` · `normal`(기본) · `many`. 세기 `normal` 2σ · `big` 2.5σ · `huge` 3σ · `value`.

## 전환 순서(사용자가 하는 일)

### 1. 시크릿 6종 — 이것이 없으면 새 화면 조건 · 푸시는 한 건도 안 나간다
```
python scripts/gen_vapid.py mailto:<내 메일>        # VAPID 키 쌍 · subject 안내 출력
python -c "import secrets;print(secrets.token_hex(32))"   # ALERTS_STATE_SALT (동기화 키와 다른 값!)
gh secret set ALERTS_STATE_SALT    # 위에서 만든 값
gh secret set PUSH_READ_KEY        # Worker 와 같은 값 — 구독 목록 · /prefs 읽기(CI 는 동기화 키를 갖지 않는다)
gh secret set VAPID_PRIVATE_KEY
gh secret set VAPID_SUBJECT        # mailto:…
```
Worker 쪽(저장소 루트에서, 승인 뒤): `VAPID_PUBLIC_KEY` · `PUSH_READ_KEY` 두 시크릿을 Worker 에 넣고 다시 배포한다. Workers Builds 가 main 푸시를 자동 배포하므로 시크릿만 넣으면 된다.
확인: 새 화면 알림 › 채널 › 「폰 알림」 켜기 → 503 이 아니면 성공. `stock-alerts` 런 로그에 「[prefs] ALERTS_STATE_SALT 없음」이 없어야 한다.

### 2. 카톡 친구 모드(10분) — `docs/KAKAO_SETUP.md ⑤`
보조 계정 만들기 → 본 계정과 친구 → developers 앱 멤버 추가 → 동의항목 `friends` → 보조 계정으로 토큰 발급 → `gh secret set KAKAO_REFRESH_TOKEN` → 저장소 변수 `KAKAO_FRIENDS=1`.
친구 모드가 아니면(`KAKAO_FRIENDS=0` · 친구 목록 403) v2 는 **디스코드로 가는 것을 전부 메모(나에게 보내기)로 따라 보낸다** — 「나와의 채팅」에 쌓이지만 카카오 정책상 소리는 안 난다(2026-10-07 사용자 결정. 그 전엔 카톡을 통째로 멈춰 「안 온다」가 됐다).

### 3. 켜기
```
gh variable set ALERTS_V2 --body 1
```
- 현행 발송 단계가 건너뛰어진다: 종목 조건(check_alerts) · 서킷(check_halts) · 급변(check_swings) · 발표 결과(check_releases) · 메르 임계(check_mer_thresholds) · 정기 시황 6통(kakao-daily 게이트).
- 대신 돈다: 사건 추출 · 발송(run.py) · 브리핑(briefing.yml).
- 되돌리기: `gh variable set ALERTS_V2 --body 0`. 원장은 계속 쓰인다(화면 「받은 알림」은 그대로).

### 4. 첫날 확인
- `events/latest.json` 이 커밋되는지(`stock-alerts` 「Commit … events/」 단계, `alerts-v2.yml` settle 런).
- 디스코드 #종목-알림(알림 · 안내) · #급변-속보(경보 @everyone) · #시황-다이제스트(브리핑)에 소리와 함께 나가는지(2026-10-07 무음 해제). 카톡은 친구 모드가 아니면 「나와의 채팅」에 메모로 따라오는지.
- 통수: 평일 울림 3~4 안팎(브리핑 2 + 사건 1~2). 넘으면 설정 꾸러미 `quiet` 로.

## 설정은 어디에
- 사용자: 새 화면 알림 › 사건 탭(꾸러미 · 갈래 · 사건 낱개 · 내 조건) · 채널 탭(폰 · 카톡 · 울림 채널 · 조용한 시간 · 상한 · 브리핑). Worker KV `/prefs`(v2).
- 운영: 저장소 변수 `ALERTS_V2` · `KAKAO_FRIENDS`, 시크릿 위 6종 + 디스코드 웹훅 4 + 카카오 2.
- 사전: `scripts/alerts_v2/events.yml` — 사건을 더하거나 임계를 바꾸는 유일한 자리. 바꾼 뒤 `python scripts/alerts_v2/export_dict.py` 로 화면 사전을 다시 내보내고 커밋(파리티 검사 `test_v2_parity.py` 가 어긋남을 잡는다).

## 원장 읽는 법
`events/2026-10-02.json` 한 행 = 한 사건. `key` 가 멱등 열쇠(`사건:대상:방향:기준일`), `sent` 가 채널별 결과(`push` 큐 건수 · `kakao` · `discord` · `bundled` 묶음 · `held` 조용한 시간 보류). 사용자 조건 행은 `cond`(조건 id)만 있고 임계값은 없다.
드라이런: `ALERTS_V2=1 python scripts/alerts_v2/run.py --mode light --dry-run --now 2026-10-02T22:16+09:00`.

## 왜 안 울렸나(자주 묻는 것)
| 증상 | 원인 | 확인 |
|---|---|---|
| 아무것도 안 옴 | `ALERTS_V2` 가 0 | `gh variable list` |
| 디스코드만 오고 폰 · 카톡 없음 | 시크릿 6종 · 친구 모드 | 런 로그 「[v2] 카톡 …」 「PUSH_READ_KEY」 |
| 조건을 만들었는데 안 옴 | 동기화 꺼짐(이 기기에만) · 사전이 그 대상에 그 사건을 허용하지 않음 | 조건 행 상태 「이 기기에만」 |
| 같은 사건이 두 번 | 원장 key 가 다름(기준일 다른 두 값) | `events/` 두 행의 `asOf` |
| 밤에 안 오고 아침에 묶여 옴 | 조용한 시간 23:00~07:00 보류(설계) | 아침 카드 「밤사이 알림 N건」 |
| 서킷이 울렸는데 추정 표시 | 지수 대리 추정(선물 없음) | 제목 「(추정)」 |

## 게이트
`python -m pytest scripts/tests -q`(CI 세 워크플로 + alerts-v2 + briefing 이 발송 앞에서 돌린다 · 통과 마커 캐시) — v2 검사는 `test_v2_*.py`.
