#!/usr/bin/env bash
# 수집기 상태 점검: 마지막 스냅샷 시각, 마지막 실행 종료코드, 다음 실행 예정.
LOG=${TOSS_LOG:-/var/log/toss-snapshot.log}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)

echo "== 마지막 스냅샷 (toss_snapshot.json)"
python3 - "$ROOT/toss_snapshot.json" <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    print("generatedAt:", d.get("generatedAt"), "| host:", d.get("host", "(없음)"))
except Exception as e:
    print("읽기 실패:", e)
EOF
echo "마지막 커밋: $(git -C "$ROOT" log -1 --format='%cd %s' --date=iso -- toss_snapshot.json)"

echo "== 마지막 실행 종료코드 (0=정상, 1=키 없음, 2=수집 0건·IP 확인, 3=푸시 실패)"
grep -E '\] exit [0-9]+' "$LOG" | tail -1 || echo "로그 없음"

echo "== 최근 하트비트"
grep '\[heartbeat\]' "$LOG" | tail -1 || echo "없음"

echo "== 다음 실행"
systemctl list-timers toss-snapshot.timer --no-pager 2>/dev/null | head -3 || true
[ -f /etc/cron.d/toss-snapshot ] && echo "(cron 방식: /etc/cron.d/toss-snapshot)"
exit 0
