# 메르 리스크 렌즈 — 추출 품질 사람 표본 검수 (P5-3)

`scripts/tests/test_mer_extract_quality.py` 가 기계로 검증 가능한 항목(인용 길이, enum 범위,
logNo 중복, 날짜 형식, risk_flags 허용 목록, econ 비율)은 이미 자동 검사한다. 이 문서는 **그
테스트가 검사할 수 없는 항목**만 다룬다.

## 커버리지 (2026-09-15 기준)

- 코퍼스 전체 810편 중 **376편**이 `mer_extract_cache.jsonl` 로 구조화 완료.
- 나머지 **434편**은 LLM 키(`ANTHROPIC_API_KEY` → `GEMINI_API_KEY`) 대기 — `scripts/mer_extract.py --limit N`
  으로 회차를 나눠 백필한다(`scripts/mer_extract.py` 상단 주석 참고).
- `econ=true` 326/376 (87%) — 자동 테스트가 70~95% 대역으로 고정한 수치와 일치.

## 사람이 30편 표본으로 확인해야 하는 항목

원문 자체는 이 저장소에 저장하지 않는다(공개 저장소 — `scripts/fetch_merblog.py` 주석 참고).
그래서 **인용이 원문에 실재하는지**는 코드로 재검증할 수 없다 — `scripts/mer_extract.py` 의
`quote_is_real()` 이 추출 시점에 한 번 원문과 대조해 걸러내지만, 그 이후 원문이 사라지므로
캐시 파일만 놓고는 "이 인용이 정말 그 글에 있었나"를 다시 확인할 방법이 없다.

사람이 직접 `https://blog.naver.com/ranto28/{logNo}` 원문을 열어 30편 표본(예: 날짜순 12편
간격 샘플링)에서 아래를 확인할 것:

1. **인용 실재성** — `indicators[].quote` / `thresholds[].quote` / `impacts[].quote` 가 해당 글에
   실제로 있는 문장인지(요약·창작이 아닌지).
2. **chain 의 개연성** — `chain` 필드(전이경로 한 줄)가 인용된 근거들로부터 합리적으로 도출되는지,
   아니면 근거와 무관한 문장이 붙었는지.
3. **stance.why 의 정합성** — `view` 값(−2~+2)과 `why` 서술이 방향상 일치하는지(예: view=+2 인데
   why 가 부정적 내용).
4. **one_liner 의 대표성** — 글 전체 논지를 한 줄이 왜곡 없이 요약하는지(추출 로직은
   `one_liner_last()` 로 "마지막 매치"만 신뢰하는데, 그 마지막 매치가 실제로 그 글의 결론인지는
   내용을 읽어야 판단 가능).

## 자동 검사에서 발견된 것 (참고 — 표본 검수 우선순위에 반영)

`test_mer_extract_quality.py` 를 376행 전체에 실측 실행한 결과(2026-09-15, 이 저장소가 다른
세션과 동시에 작업 중이던 시점 — `mer_extract_cache.jsonl` 은 공유 파일이라 재확인 시 값이
바뀔 수 있음에 유의):

- 이번 실측에서는 80자 인용, stance.view 범위, impacts.direction(`+`/`-`/`±`), strength(1~3),
  horizon(3종), risk_flags(10종 허용 목록), logNo 중복, 날짜 형식, econ 비율(87%) 전부
  376건 위반 0건.
- **직전 실측(같은 날)에서는 `impacts[].direction` 위반이 1건 있었다** — logNo `224339898546`
  (2026-07-08, `_meta.source: "research-backfill-376"`)의 한 impact 가 `direction: "0"` 을
  가졌다(허용값은 `+`/`-`/`±` 뿐, `scripts/mer_extract.py` 의 `_VALID_DIR` 가 이를 강제하지만
  이 레코드는 그 검증 경로를 거치지 않고 별도로 채워진 것으로 보인다). 두 번째 실측에서는 이
  레코드가 사라져 있었다 — 이 파일에 동시에 쓰고 있는 다른 파이프라인(백필/재집계)이 있다는
  뜻이다. 표본 검수 시 `224339898546` 을 먼저 열어 지금도 정상인지 확인할 것 — enum 위반이
  있었던 레코드는 다른 필드 품질도 함께 의심할 이유가 된다.
