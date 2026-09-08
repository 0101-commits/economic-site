# 파이프라인 수정 사후 관측 작업 등록/재등록 (Windows 작업 스케줄러)
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_verify_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_verify_task.ps1 -Remove
#
# 2026-09-08 수정(스테일 임계 시간대화·경량 자동복구·Worker 장외 보강·작업 창 숨김)이
# 실제로 먹었는지는 며칠에 걸친 관측으로만 확인된다. scripts\verify_pipeline_fix.py 가
# 실측을 재서 디스코드 #시스템 채널로 보고한다.
#
# 트리거 세 겹:
#   · 오늘 -FirstCheck 시각 — 배포 후 첫 장외 :35 보강(UTC 07:35 = KST 16:35)이 실제로
#     발화했는지 확인하는 단발. 기본 16:45 KST.
#   · 매일 09:10 — 지난 30시간 요약(월요일은 스크립트가 72시간으로 늘려 주말을 덮는다).
#   · StartWhenAvailable — PC 가 꺼져 있어 놓친 실행을 켜질 때 따라잡는다.
#
# 액션이 .cmd 가 아니라 run_hidden.vbs 인 이유는 register_toss_task.ps1 과 같다 —
# 작업 XML 의 <Hidden> 은 스케줄러 UI 목록 숨김이고 콘솔 창을 없애지 못한다.
#
# 관측이 끝나면 지운다: -Remove

param(
  [datetime] $FirstCheck = (Get-Date).Date.AddHours(16).AddMinutes(45),
  [switch] $Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = 'EconSite-FixVerify'

if ($Remove) {
  try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    Write-Output "삭제 완료: $TaskName"
  } catch { Write-Output "이미 없음: $TaskName" }
  return
}

$Cmd = Join-Path $PSScriptRoot 'run_verify_fix.cmd'
if (-not (Test-Path $Cmd)) { throw "실행 파일 없음: $Cmd" }
$Vbs = Join-Path $PSScriptRoot 'run_hidden.vbs'
if (-not (Test-Path $Vbs)) { throw "래퍼 없음: $Vbs" }
$User = "$env:USERDOMAIN\$env:USERNAME"
$First = $FirstCheck.ToString('yyyy-MM-ddTHH:mm:ss')

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>economic-site: 2026-09-08 pipeline fix observation -> Discord #system</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Enabled>true</Enabled>
      <StartBoundary>$First</StartBoundary>
    </TimeTrigger>
    <CalendarTrigger>
      <StartBoundary>2026-09-09T09:10:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
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
    <!-- ⚠ Hidden 은 스케줄러 UI 목록 숨김일 뿐 콘솔 창과 무관하다 — 창을 없애는 건
         아래 Actions 의 wscript 래퍼다(2026-09-08 진단). -->
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT10M</Interval>
      <Count>2</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>//B //Nologo "$Vbs" run_verify_fix.cmd</Arguments>
    </Exec>
  </Actions>
</Task>
"@

try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop } catch {}
Register-ScheduledTask -TaskName $TaskName -Xml $xml -User $User | Out-Null

Write-Output "등록 완료: $TaskName  (첫 확인 $First, 이후 매일 09:10)"
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime, LastTaskResult, NextRunTime
