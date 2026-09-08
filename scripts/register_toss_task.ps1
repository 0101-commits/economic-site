# 토스 스냅샷 수집 작업 등록/재등록 (Windows 작업 스케줄러)
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_toss_task.ps1
#
# 이 PC 는 24시간 켜져 있지 않다. 정시 트리거만으로는 구멍이 생기므로 네 겹으로 덮는다:
#   · 로그온 +3분   — 켤 때마다 한 번. 지연은 네트워크가 올라올 시간을 준다.
#   · 평일 09~20시 15분 간격 — 켜져 있는 동안 장중 시세를 따라간다
#     (2026-08-20 토스 전면 적용 기획 옵션 A: 매시간 → 15분. 커밋은 payloadHash
#      가드가 무변동을 걸러 주고, 토스 rate limit 은 회당 ~70콜이라 여유가 크다).
#   · 평일 15:45    — 장 마감 직후 확정 등락 상위·종가.
#   · StartWhenAvailable — 꺼져 있어 놓친 실행을 켜질 때 따라잡는다(핵심).
# 배터리에서도 돌고, 실패하면 10분 뒤 3회까지 재시도한다(부팅 직후 네트워크 지연 대비).
#
# 데이터가 안 바뀌면 fetch_toss_snapshot.py 가 파일·커밋을 건너뛴다 → 잦은 실행이
# 커밋 스팸이 되지 않는다.
#
# ⚠ New-ScheduledTaskTrigger 는 Windows PowerShell 5.1 에서 로그온 트리거의 Delay 와
#   반복(Repetition)을 제대로 못 실어 준다. 그래서 작업 정의 XML 을 직접 등록한다.

$ErrorActionPreference = 'Stop'
$TaskName = 'EconSite-TossSnapshot'
$Cmd = Join-Path $PSScriptRoot 'run_toss_snapshot.cmd'
if (-not (Test-Path $Cmd)) { throw "실행 파일 없음: $Cmd" }
# 액션은 .cmd 가 아니라 wscript 래퍼다 — 아래 <Actions> 주석 참고.
$Vbs = Join-Path $PSScriptRoot 'run_hidden.vbs'
if (-not (Test-Path $Vbs)) { throw "래퍼 없음: $Vbs" }
$User = "$env:USERDOMAIN\$env:USERNAME"

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>economic-site: Toss Securities snapshot (allowlisted IP) -> toss_snapshot.json -> git push</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$User</UserId>
      <Delay>PT3M</Delay>
    </LogonTrigger>
    <CalendarTrigger>
      <StartBoundary>2026-01-05T09:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT15M</Interval>
        <Duration>PT11H</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <ScheduleByWeek>
        <DaysOfWeek><Monday/><Tuesday/><Wednesday/><Thursday/><Friday/></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
    <CalendarTrigger>
      <StartBoundary>2026-01-05T15:45:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek><Monday/><Tuesday/><Wednesday/><Thursday/><Friday/></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$User</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <Enabled>true</Enabled>
    <!-- ⚠ Hidden 은 '스케줄러 UI 목록에서 감추기'일 뿐 콘솔 창과 무관하다.
         창을 없애는 건 아래 Actions 의 wscript 래퍼다. -->
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT10M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <!-- .cmd 를 직접 액션으로 두면 InteractiveToken 세션에 콘솔 창이 뜬다(하루 45회).
         wscript //B 는 창을 만들지 않고, 래퍼가 종료 코드를 그대로 돌려주므로
         RestartOnFailure 도 그대로 작동한다. 창을 보며 디버깅할 땐 .cmd 를 직접 실행. -->
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>//B //Nologo "$Vbs" run_toss_snapshot.cmd</Arguments>
    </Exec>
  </Actions>
</Task>
"@

try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop } catch {}
Register-ScheduledTask -TaskName $TaskName -Xml $xml -User $User | Out-Null

Write-Output "등록 완료: $TaskName"
(Get-ScheduledTask -TaskName $TaskName).Triggers |
  Select-Object @{n='종류';e={$_.CimClass.CimClassName -replace 'MSFT_Task',''}},
                StartBoundary, Delay,
                @{n='반복';e={$_.Repetition.Interval}}, @{n='기간';e={$_.Repetition.Duration}}
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime,LastTaskResult,NextRunTime
