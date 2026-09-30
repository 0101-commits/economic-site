#!/usr/bin/env bash
# 토스 스냅샷 수집 1회 실행 (systemd 타이머 / cron 이 15분마다 호출).
# 하는 일: git pull -> fetch_toss_snapshot.py --push -> 로그. 파이썬은 표준 라이브러리만 쓴다.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LOG=${TOSS_LOG:-/var/log/toss-snapshot.log}
ENV_FILE=${TOSS_ENV_FILE:-/etc/economic-site/toss.env}
exec >>"$LOG" 2>&1

# 앞 실행이 안 끝났으면 겹치지 않는다.
exec 9>/tmp/toss-snapshot.lock
flock -n 9 || { echo "[$(date '+%F %T %Z')] skip (이전 실행 진행 중)"; exit 0; }

set -a; . "$ENV_FILE"; set +a
export PYTHONIOENCODING=utf-8
cd "$ROOT" || exit 1
echo "[$(date '+%F %T %Z')] run host=${TOSS_SNAPSHOT_HOST:-?}"

# 월 1회 하트비트: 이 인스턴스가 살아 있다는 기록(회수 정책 점검용). 달이 바뀐 첫 실행에서 남긴다.
MONTH=$(TZ=Asia/Seoul date +%Y-%m)
STAMP="$HOME/.toss_heartbeat"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$MONTH" ]; then
  echo "[heartbeat] $MONTH uptime=$(uptime -p) disk=$(df -h / | awk 'NR==2{print $5}') ip=$(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || echo ?)"
  echo "$MONTH" >"$STAMP"
fi

git pull --rebase --autostash -q || echo "[warn] git pull 실패 - 로컬 기준으로 계속"
python3 scripts/fetch_toss_snapshot.py --push
RC=$?
echo "[$(date '+%F %T %Z')] exit $RC"
exit $RC
