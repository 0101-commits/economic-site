// isOffHoursFetchTick 자가 점검 — 장외 보강 dispatch 가 '매시 :35 한 번'인지.
//
// 이 창이 넓어지면 장외에 GitHub 을 매분 두들기게 되고, 좁아지거나 장중까지 번지면
// 2026-09-08 진단의 원인(장외 공백 최장 324분)이 그대로 돌아온다.
//
// 실행: node cloudflare-worker/test_offhours_tick.mjs
import { isOffHoursFetchTick } from './worker.js';

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

console.log(fails ? `실패 ${fails}건` : '실패 0건');
process.exit(fails ? 1 : 0);
