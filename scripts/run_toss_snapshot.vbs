' 창 없이 run_toss_snapshot.cmd 를 실행하고 종료 코드를 그대로 돌려준다.
'
' 왜 필요한가 (2026-09-08 진단):
'   작업 스케줄러의 <Hidden> 은 '작업이 스케줄러 UI 목록에 보이는지'를 정하는 값이고
'   콘솔 창과는 무관하다. 액션이 .cmd(콘솔 프로그램)이고 Principal 이 InteractiveToken
'   이면 로그인 세션에 반드시 창이 뜬다 — 평일 09~20시 15분 간격이라 하루 45번,
'   회당 22~30초씩 화면을 가렸다. 창을 만들지 않는 호스트(wscript)로 띄우는 것이
'   주기·푸시를 건드리지 않고 창만 없애는 유일한 방법이다.
'   (같은 패턴을 이 PC 의 Hermes_Gateway 작업이 이미 쓰고 있다.)
'
' 등록: powershell -ExecutionPolicy Bypass -File scripts\register_toss_task.ps1
' 수동 실행(창 보고 싶을 때)은 run_toss_snapshot.cmd 를 직접 돌리면 된다.
Option Explicit

Dim sh, fso, cmd, rc
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 경로는 이 스크립트 위치 기준 — 저장소를 옮겨도 작업 XML 만 갱신하면 된다.
cmd = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "run_toss_snapshot.cmd")
If Not fso.FileExists(cmd) Then
    ' 스케줄러에는 0 이 아닌 코드만 남기면 된다(대화상자를 띄우면 무인 실행이 멈춘다).
    WScript.Quit 9009
End If

' 0    = 창 숨김
' True = 종료까지 대기하고 종료 코드를 회수 → RestartOnFailure(10분×3회)가 계속 작동한다.
rc = sh.Run("""" & cmd & """", 0, True)
WScript.Quit rc
