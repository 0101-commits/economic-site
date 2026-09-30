#!/usr/bin/env bash
# Oracle Cloud Ubuntu(22.04/24.04) 에 토스 스냅샷 수집기를 설치한다. 여러 번 실행해도 안전하다.
#   curl -fsSL https://raw.githubusercontent.com/0101-commits/economic-site/main/scripts/server/setup_toss_collector.sh | bash
# 필요한 값(TOSS_CLIENT_ID, TOSS_CLIENT_SECRET, GH_TOKEN)은 환경변수로 미리 주거나, 없으면 물어본다.
set -euo pipefail

[ "$(id -u)" -ne 0 ] || { echo "root 가 아닌 일반 사용자(ubuntu)로 실행하세요."; exit 1; }
REPO_URL=https://github.com/0101-commits/economic-site.git
ME=$(id -un)
DIR=$HOME/economic-site
ENV_DIR=/etc/economic-site
ENV_FILE=$ENV_DIR/toss.env
LOG=/var/log/toss-snapshot.log

echo "[1/6] 패키지"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3 curl

echo "[2/6] 비밀값 -> $ENV_FILE"
sudo mkdir -p "$ENV_DIR"; sudo chown "$ME" "$ENV_DIR"
# 이미 있는 값은 그대로 쓴다(재실행 시 다시 묻지 않음).
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
ask() {  # ask 변수명 [secret]
  local n=$1 v=${!1:-}
  if [ -z "$v" ]; then
    [ -r /dev/tty ] || { echo "$n 가 없고 입력 창도 없습니다. 환경변수로 넘기세요."; exit 1; }
    if [ "${2:-}" = secret ]; then read -r -s -p "$n (입력은 화면에 안 보임): " v </dev/tty; echo >/dev/tty
    else read -r -p "$n: " v </dev/tty; fi
  fi
  [ -n "$v" ] || { echo "$n 비어 있음"; exit 1; }
  printf -v "$n" %s "$v"
}
ask TOSS_CLIENT_ID; ask TOSS_CLIENT_SECRET secret; ask GH_TOKEN secret
TOSS_SNAPSHOT_HOST=${TOSS_SNAPSHOT_HOST:-oracle}
TOSS_SNAPSHOT_ROLE=${TOSS_SNAPSHOT_ROLE:-primary}
( umask 077
  printf 'TOSS_CLIENT_ID=%q\nTOSS_CLIENT_SECRET=%q\nGH_TOKEN=%q\nTOSS_SNAPSHOT_HOST=%q\nTOSS_SNAPSHOT_ROLE=%q\n' \
    "$TOSS_CLIENT_ID" "$TOSS_CLIENT_SECRET" "$GH_TOKEN" "$TOSS_SNAPSHOT_HOST" "$TOSS_SNAPSHOT_ROLE" >"$ENV_FILE" )
chmod 600 "$ENV_FILE"

# 깃 인증: 토큰은 URL 에 넣지 않고, 위 env 파일을 읽는 도우미가 필요할 때만 꺼내 준다.
cat >"$ENV_DIR/git-cred.sh" <<'EOF'
#!/bin/sh
[ "$1" = get ] || exit 0
. /etc/economic-site/toss.env
echo username=x-access-token
echo "password=$GH_TOKEN"
EOF
chmod 700 "$ENV_DIR/git-cred.sh"

echo "[3/6] 저장소"
CRED="credential.helper=$ENV_DIR/git-cred.sh"
if [ -d "$DIR/.git" ]; then git -C "$DIR" -c "$CRED" pull --rebase --autostash -q
# 왜: 이 저장소는 커밋 14,500개(data.json 매시 커밋)라 전체 복제는 1vCPU 서버에서 index-pack 만 10분+ 걸려
#   설치가 3/6 에서 멈춘 것처럼 보였다(2026-09-30 실측). 스냅샷 푸시엔 최신 1커밋만 있으면 된다.
else git -c "$CRED" clone -q --depth 1 --single-branch --branch main "$REPO_URL" "$DIR"; fi
git -C "$DIR" config credential.helper "$ENV_DIR/git-cred.sh"
git -C "$DIR" config user.name ecom-collector
git -C "$DIR" config user.email ecom-collector@users.noreply.github.com
git -C "$DIR" config pull.rebase true
chmod +x "$DIR"/scripts/server/*.sh 2>/dev/null || true

echo "[4/6] 로그 + logrotate"
sudo touch "$LOG"; sudo chown "$ME" "$LOG"
sudo tee /etc/logrotate.d/toss-snapshot >/dev/null <<EOF
$LOG {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
EOF

echo "[5/6] 15분 타이머 (평일 KST 09:00~20:45)"
# 한국은 서머타임이 없어 KST 09~20시 = UTC 00~11시(같은 요일). 시간대 문법 없이도 정확하다.
CAL='Mon..Fri *-*-* 00..11:00/15:00 UTC'
if systemd-analyze calendar "$CAL" >/dev/null 2>&1; then
  sudo tee /etc/systemd/system/toss-snapshot.service >/dev/null <<EOF
[Unit]
Description=Toss snapshot collector
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$ME
ExecStart=/bin/bash $DIR/scripts/server/run_toss_snapshot.sh
TimeoutStartSec=600
EOF
  sudo tee /etc/systemd/system/toss-snapshot.timer >/dev/null <<EOF
[Unit]
Description=Toss snapshot every 15 min (weekdays, KST 09-20)

[Timer]
OnCalendar=$CAL
AccuracySec=10s

[Install]
WantedBy=timers.target
EOF
  sudo rm -f /etc/cron.d/toss-snapshot
  sudo systemctl daemon-reload
  sudo systemctl enable --now toss-snapshot.timer
else
  echo "systemd 달력 문법 미지원 - cron 으로 대체"
  sudo apt-get install -y -qq cron
  echo "*/15 0-11 * * 1-5 $ME /bin/bash $DIR/scripts/server/run_toss_snapshot.sh" | sudo tee /etc/cron.d/toss-snapshot >/dev/null
  sudo systemctl enable --now cron
fi

echo "[6/6] 첫 실행 시험"
echo "이 서버의 공인 IP: $(curl -fsS -m 5 https://api.ipify.org || echo '확인 실패')  <- 토스증권 허용 IP 에 등록돼 있어야 합니다"
RC=0; bash "$DIR/scripts/server/run_toss_snapshot.sh" || RC=$?
bash "$DIR/scripts/server/healthcheck.sh"
[ "$RC" -eq 0 ] || echo "첫 실행 종료코드 $RC - 로그: tail -n 30 $LOG"
