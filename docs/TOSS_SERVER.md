# 토스 스냅샷 서버 수집기 (Oracle Cloud 무료 서버)

## 1. 목적

- 토스증권 Open API는 등록된 IP에서 온 요청만 응답하는 구조
- 현재 수집기는 집 PC 한 대뿐이며, PC가 꺼지면 토스 데이터 공급 중단
- Oracle Cloud 무료 서버(고정 공인 IP)를 두 번째 수집기로 추가하여, PC가 꺼져도 데이터 공급 유지
- 두 수집기가 동시에 돌아도 무방함. 데이터가 같으면 커밋이 생기지 않고, 다르면 더 새 파일이 채택됨
- 서버가 만든 파일은 `host` 항목이 `oracle`, PC가 만든 파일은 `pc`로 표시됨

## 2. 체크리스트

| 순서 | 할 일 | 소요 | 완료 |
|---|---|---|---|
| 1 | Oracle Cloud 계정 가입 (신용카드 필요, 무료 범위 내 과금 없음) | 20분 | [ ] |
| 2 | 서버(VM) 만들기, SSH 키 파일 보관 | 15분 | [ ] |
| 3 | 서버 공인 IP 확인 | 1분 | [ ] |
| 4 | 토스증권 허용 IP에 서버 IP 추가 | 3분 | [ ] |
| 5 | GitHub 토큰 만들기 | 5분 | [ ] |
| 6 | 서버 접속 후 설치 명령 한 줄 실행 | 5분 | [ ] |
| 7 | 상태 확인 명령으로 정상 동작 확인 | 1분 | [ ] |
| 8 | 회수 정책 대응 (10항) | 5분 | [ ] |

## 3. 준비물

- Oracle Cloud 계정 (https://www.oracle.com/kr/cloud/free/)
- 신용카드 (본인 확인용, Always Free 범위 안에서는 청구 없음)
- 토스증권 PC웹 로그인 권한 (허용 IP 관리)
- GitHub 계정 (저장소 economic-site 쓰기 권한)

## 4. 서버(VM) 만들기

Oracle Cloud 콘솔 접속 후 아래 순서로 진행함.

1. 왼쪽 위 메뉴(햄버거) → **Compute** → **Instances**
2. **Create instance** 클릭
3. 이름: `toss-collector` (임의)
4. **Image and shape** 영역에서 **Edit**
   - **Image**: Change image → **Ubuntu** → 22.04 또는 24.04 선택
   - **Shape**: Change shape → 아래 중 하나 선택. 반드시 "Always Free-eligible" 표시가 있는 것
     - `VM.Standard.E2.1.Micro` (AMD, 무료 상시 제공, 이 용도에 충분)
     - 또는 `VM.Standard.A1.Flex` (Ampere, 1 OCPU / 6GB 정도, 재고 부족 시 생성 실패 가능)
5. **Networking**: 기본값 유지, **Assign a public IPv4 address**가 켜져 있는지 확인
6. **Add SSH keys**: **Generate a key pair for me** 선택 후 **Save private key** 클릭
   - 내려받은 `.key` 파일은 분실 시 서버 접속 불가이므로 안전한 곳에 보관
   - 공개키(Save public key)도 받아 두면 좋음
7. **Create** 클릭 후 상태가 **Running**(초록)이 될 때까지 대기(1~3분)

## 5. 공인 IP 확인

- 콘솔 → **Compute** → **Instances** → 만든 인스턴스 클릭 → **Instance information** 탭의 **Public IP address**
- 서버 안에서 확인하는 방법: `curl https://api.ipify.org`
- 이 IP가 토스 허용 IP에 등록할 값이며, 인스턴스를 삭제하고 새로 만들면 IP가 바뀜(재등록 필요)
- 재부팅·중지 후 시작 정도로는 바뀌지 않음(임시 IP도 인스턴스 존속 중에는 유지)

## 6. 토스증권 허용 IP 등록

1. 토스증권 PC웹(WTS) 로그인
2. **설정** → **Open API** → **허용 IP 관리**
3. 5항에서 확인한 서버 IP 추가 (기존 집 IP는 삭제하지 않고 함께 유지)

주의: 토스 토큰은 클라이언트당 하나만 유효함. PC와 서버가 같은 클라이언트 키를 쓰면 한쪽이 토큰을 재발급할 때 상대 토큰이 무효화되나, 수집기가 401 응답 시 1회 자동 재발급하므로 결과적으로는 복구됨. 다만 두 수집기가 같은 시각에 돌면 드물게 한 번씩 실패할 수 있음(다음 15분 주기에 회복).

## 7. GitHub 토큰 만들기

1. GitHub 로그인 → 오른쪽 위 프로필 → **Settings**
2. 왼쪽 맨 아래 **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
3. **Generate new token**
   - Token name: `toss-collector`
   - Expiration: 1년 등 (만료 시 재발급 필요, 달력에 기록)
   - Repository access: **Only select repositories** → `economic-site`
   - Permissions → Repository permissions → **Contents: Read and write**
4. **Generate token** 후 표시되는 `github_pat_...` 값을 복사 (화면을 벗어나면 다시 볼 수 없음)

## 8. 서버 접속과 설치

PC의 터미널(PowerShell)에서 접속함. 키 파일 경로와 IP는 본인 값으로 교체.

```
ssh -i C:\경로\ssh-key.key ubuntu@서버공인IP
```

(키 파일 권한 오류가 나면 파일 속성 → 보안에서 본인 계정만 읽기 허용)

접속 후 아래 한 줄 실행. 토스 클라이언트 ID, 시크릿, GitHub 토큰을 차례로 묻고, 시크릿은 입력해도 화면에 보이지 않음.

```
curl -fsSL https://raw.githubusercontent.com/0101-commits/economic-site/main/scripts/server/setup_toss_collector.sh | bash
```

- 설치 전에 이 스크립트가 main 브랜치에 병합되어 있어야 함(아니면 404)
- 설치가 끝나면 공인 IP 표시, 첫 실행 시험, 상태 점검 결과가 출력됨
- 같은 명령을 다시 실행해도 안전함(이미 입력한 값은 다시 묻지 않음)

## 9. 확인 명령

```
bash ~/economic-site/scripts/server/healthcheck.sh     # 마지막 스냅샷 시각, 마지막 종료코드, 다음 실행
tail -n 30 /var/log/toss-snapshot.log                  # 최근 실행 기록
systemctl list-timers toss-snapshot.timer              # 다음 실행 예정
sudo systemctl start toss-snapshot.service             # 지금 즉시 1회 실행
```

종료코드 해석

| 코드 | 의미 | 조치 |
|---|---|---|
| 0 | 정상 | 없음 |
| 1 | 키(TOSS_CLIENT_ID/SECRET) 없음 | `/etc/economic-site/toss.env` 확인 |
| 2 | 수집 0건 | 서버 IP가 토스 허용 목록에 있는지 확인 |
| 3 | 푸시 실패 | GitHub 토큰 만료·권한 확인 |

실행 시각: 평일 한국시간 09:00~20:45, 15분 간격(주말·야간 미실행). 사이트 화면에서 토스 연결 표시가 정상(조용함)이면 수집이 이어지고 있는 상태.

## 10. 회수 정책 주의 (중요)

- Oracle은 Always Free 컴퓨트 인스턴스가 7일 동안 유휴 상태이면 회수(중지·삭제)할 수 있다고 안내함
- 유휴 기준(Oracle 공지 기준): CPU 사용률 95번째 백분위 20% 미만, 네트워크 사용률 20% 미만(A1 형은 메모리 20% 미만 포함)
- 이 수집기는 15분에 몇 초만 일하므로 기준상 유휴에 해당함. 회수 위험이 실제로 존재함
- 대응책 (권장 순서)
  1. 계정을 **Pay As You Go**로 업그레이드(콘솔 → Billing → Upgrade). 무료 범위 안에서는 청구가 없고, 업그레이드 계정은 유휴 회수 대상에서 제외된다는 것이 일반적인 안내이나 공식 문서에서 재확인 필요
  2. 회수되면 8항 절차를 새 서버에서 반복(허용 IP 재등록 필요). PC 수집기가 살아 있으면 서비스 공백은 없음
  3. 월 1회 하트비트: 실행 로그에 달이 바뀐 첫 실행 때 `[heartbeat]` 줄(가동 시간·디스크·공인 IP)이 남음. 이 줄이 끊기면 서버 이상 신호이며, 확인은 `grep heartbeat /var/log/toss-snapshot.log`
- 하트비트는 CPU 부하를 만들지 않으므로 회수 방지 효과는 없음. 기록·점검용임
- 상태 이상(스냅샷이 오래됨)은 사이트의 토스 연결 표시(STALE/OFFLINE)와 디스코드 감시 알림으로 확인

## 11. PC를 대기로 돌리기

- 토스는 클라이언트당 토큰이 하나뿐이라, PC와 서버가 모두 돌면 서로의 토큰을 무효화하는 다툼이 생김
- 해결: 서버는 주 수집기(`primary`), PC는 대기(`standby`)로 지정
- 대기 수집기는 실행 시작 때 GitHub의 최신 스냅샷을 확인하여, 다른 수집기가 40분 이내에 만든 파일이면 「다른 수집기 가동 중 — 건너뜀」 로그만 남기고 종료(토스 호출 없음)
- 서버가 멈춰 40분이 지나면 PC가 자동으로 수집을 이어받음
- 서버 설정: 설치 스크립트가 `/etc/economic-site/toss.env`에 `TOSS_SNAPSHOT_ROLE=primary`를 기록함
- PC 설정: PowerShell에서 아래 한 줄 실행 후 로그오프·로그온(또는 작업 스케줄러 재시작)

```
setx TOSS_SNAPSHOT_ROLE standby
```

- 되돌리기: `setx TOSS_SNAPSHOT_ROLE primary`
- 한계: 장 마감 후·주말처럼 데이터가 안 바뀌는 시간에는 스냅샷 시각이 갱신되지 않아 PC가 수집을 시도할 수 있음. 이 시간대는 호출량이 적고 무변동이라 커밋은 생기지 않음

## 12. 끄는 법

일시 중지(다시 켜기 가능)

```
sudo systemctl disable --now toss-snapshot.timer
```

다시 켜기

```
sudo systemctl enable --now toss-snapshot.timer
```

완전 제거

```
sudo systemctl disable --now toss-snapshot.timer
sudo rm /etc/systemd/system/toss-snapshot.{service,timer} /etc/logrotate.d/toss-snapshot
sudo rm -rf /etc/economic-site ~/economic-site
```

- cron 방식으로 설치된 경우 `sudo rm /etc/cron.d/toss-snapshot`
- 서버 자체 삭제: 콘솔 → Instances → 인스턴스 → **More actions** → **Terminate**
- 사용 후에는 GitHub 토큰(Settings → Fine-grained tokens)과 토스 허용 IP도 함께 삭제 권장

## 13. 참고

- 스케줄: systemd 타이머(UTC 00~11시 평일 = KST 09~20시, 한국은 서머타임 없음). 시간대 문법 미지원 서버는 설치 스크립트가 자동으로 cron으로 대체
- 비밀값 위치: `/etc/economic-site/toss.env`(소유자만 읽기, 권한 600). GitHub 토큰은 이 파일에서 필요할 때만 읽혀 저장소 주소에 저장되지 않음
- 로그: `/var/log/toss-snapshot.log`(주 1회 회전, 4주 보관)
- 파이썬 추가 설치 없음(표준 라이브러리만 사용)
