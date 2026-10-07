// isOffHoursFetchTick 자가 점검 — 장외 보강 dispatch 가 '매시 :35 한 번'인지.
//
// 이 창이 넓어지면 장외에 GitHub 을 매분 두들기게 되고, 좁아지거나 장중까지 번지면
// 2026-09-08 진단의 원인(장외 공백 최장 324분)이 그대로 돌아온다.
//
// 실행: node cloudflare-worker/test_offhours_tick.mjs
import { isOffHoursFetchTick, fullFetchMode, inMarketHours, isKrHoliday, v2Ticks } from './worker.js';

const at = (dowUtcDate, hUtc, mUtc) => new Date(Date.UTC(2026, 8, dowUtcDate, hUtc, mUtc));
// 2026-09: 07일=월 … 11일=금, 12일=토, 13일=일
const MON = 7, FRI = 11, SAT = 12, SUN = 13;

let fails = 0;
const check = (label, got, want) => {
  if (got === want) { console.log(`  OK   ${label}`); return; }
  fails++;
  console.log(`  FAIL ${label}: ${got} (기대 ${want})`);
};

// 평일 장중(UTC 00–06 = KST 09–16, UTC 13–21 = KST 22–07) — :35 여도 발화하지 않는다.
check('평일 UTC 02:35 (한국장 중)', isOffHoursFetchTick(at(MON, 2, 35)), false);
check('평일 UTC 15:35 (미국장 중)', isOffHoursFetchTick(at(MON, 15, 35)), false);

// 평일 장외(UTC 07–12 = KST 16–21) — :35/:36 만 발화.
check('평일 UTC 09:34 (장외)', isOffHoursFetchTick(at(MON, 9, 34)), false);
check('평일 UTC 09:35 (장외)', isOffHoursFetchTick(at(MON, 9, 35)), true);
check('평일 UTC 09:36 (장외, 백업 틱)', isOffHoursFetchTick(at(MON, 9, 36)), true);
check('평일 UTC 09:37 (장외)', isOffHoursFetchTick(at(MON, 9, 37)), false);
check('평일 UTC 12:35 (장외 끝)', isOffHoursFetchTick(at(FRI, 12, 35)), true);

// 주말은 하루 전체가 장외 — 장중 시각대에도 발화해야 한다.
check('토요일 UTC 02:35', isOffHoursFetchTick(at(SAT, 2, 35)), true);
check('일요일 UTC 15:35', isOffHoursFetchTick(at(SUN, 15, 35)), true);
check('일요일 UTC 15:00', isOffHoursFetchTick(at(SUN, 15, 0)), false);

// 풀/일일 런 틱 — 매시 :07·:08 만, UTC 0·7·13시는 daily(KST 09·16·22시 일일 갱신).
check('UTC 03:07 → full', fullFetchMode(at(MON, 3, 7)), 'full');
check('UTC 03:08 → full(드롭 보강)', fullFetchMode(at(MON, 3, 8)), 'full');
check('UTC 03:09 → 없음', fullFetchMode(at(MON, 3, 9)), null);
check('UTC 00:07 → daily', fullFetchMode(at(MON, 0, 7)), 'daily');
check('UTC 13:07 → daily', fullFetchMode(at(SUN, 13, 7)), 'daily');
check('UTC 07:06 → 없음', fullFetchMode(at(MON, 7, 6)), null);

// 하루 발화 횟수 = 장외 시간 수. 평일 장중은 UTC 00–06(7h) + 13–21(9h) = 16h 이므로
// 장외는 UTC 07–12(= KST 16–21시)와 22–23(= KST 07–08시) 여덟 시각이다. 주말은 24시각.
// → 장외 최대 공백은 60분(시간당 1회). 종전 실측 최장 324분을 이 값으로 대체하는 것이 목표.
const countDay = (date) => {
  let n = 0;
  for (let h = 0; h < 24; h++) if (isOffHoursFetchTick(at(date, h, 35))) n++;
  return n;
};
check('평일 하루 발화 시각 수', countDay(MON), 8);
check('주말 하루 발화 시각 수', countDay(SAT), 24);

// 🇰🇷 한국 휴장일 — KR 장중 창만 닫히고 US 창은 그대로
const HOL = new Date(Date.UTC(2026, 9, 5, 2, 0));      // 2026-10-05 대체공휴일 KST 11:00(월)
const HOL_US = new Date(Date.UTC(2026, 9, 5, 15, 0));  // 같은 날 KST 00:00 다음날 = US 장중(UTC 15시)
const WED = new Date(Date.UTC(2026, 9, 7, 2, 0));      // 2026-10-07 평일 KST 11:00
check('휴장일 KST 11:00 → 휴장일 판정', isKrHoliday(HOL), true);
check('휴장일 KR 창 → 장외', inMarketHours(HOL), false);
check('휴장일 US 창(UTC 15시) → 장중 유지', inMarketHours(HOL_US), true);
check('평일 KR 창 → 장중', inMarketHours(WED), true);
check('UTC 15:30 은 KST 다음날 00:30 — 날짜 경계가 KST 기준', isKrHoliday(new Date(Date.UTC(2026, 9, 4, 15, 30))), true);
check('휴장일 장외 보강 틱 :35 → 깨운다', isOffHoursFetchTick(new Date(Date.UTC(2026, 9, 5, 2, 35))), true);

// 🔔 알림 v2 정시 깨움 — 그 분(+1 보강)에만, 요일은 briefing.yml · alerts-v2.yml 의 cron 과 같다.
//   GHA schedule 은 5~7시간 늦게 발화했다(2026-10-06 실측) — 이 틱이 본선이다.
const tick = (d) => v2Ticks(d).map((t) => `${t.event}:${Object.values(t.payload)[0]}`).join(',');
const TUE = MON + 1;
check('화 UTC 22:30 → brief morning(수 아침)', tick(at(TUE, 22, 30)), 'brief:morning');
check('화 UTC 22:31 → brief morning(드롭 보강)', tick(at(TUE, 22, 31)), 'brief:morning');
check('화 UTC 22:32 → 없음', tick(at(TUE, 22, 32)), '');
check('금 UTC 22:30 → 없음(토 아침 없음)', tick(at(FRI, 22, 30)), '');
check('일 UTC 22:30 → brief morning(월 아침)', tick(at(SUN, 22, 30)), 'brief:morning');
check('토 UTC 00:00 → brief weekly', tick(at(SAT, 0, 0)), 'brief:weekly');
check('월 UTC 03:00 → brief noon', tick(at(MON, 3, 0)), 'brief:noon');
check('월 UTC 07:30 → brief close', tick(at(MON, 7, 30)), 'brief:close');
check('월 UTC 09:30 → brief evening', tick(at(MON, 9, 30)), 'brief:evening');
check('월 UTC 13:40 → brief us', tick(at(MON, 13, 40)), 'brief:us');
check('월 UTC 09:05 → alerts-v2 settle', tick(at(MON, 9, 5)), 'alerts-v2:settle');
check('토 UTC 09:05 → 없음(settle 평일만)', tick(at(SAT, 9, 5)), '');
check('일 UTC 12:00 → alerts-v2 eve(매일)', tick(at(SUN, 12, 0)), 'alerts-v2:eve');
check('key = UTC 날짜 + 항목', v2Ticks(at(MON, 7, 30))[0].key, '2026-09-07-brief-close');
const countV2 = (date) => { let n = 0; for (let h = 0; h < 24; h++) for (let m = 0; m < 60; m++) n += v2Ticks(at(date, h, m)).length; return n; };
check('평일 하루 깨움 분 수(7항목 × 2분)', countV2(MON), 14);
check('토요일 하루 깨움 분 수(weekly · eve × 2분)', countV2(SAT), 4);

console.log(fails ? `실패 ${fails}건` : '실패 0건');
process.exit(fails ? 1 : 0);
