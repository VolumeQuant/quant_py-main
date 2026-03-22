$python = 'C:\Users\jkw88\miniconda3\envs\volumequant\python.exe'
$script = 'C:\dev\claude-code\quant_py-main\run_daily.py'
$workdir = 'C:\dev\claude-code\quant_py-main'

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $workdir
$trigger = New-ScheduledTaskTrigger -Once -At '17:40'
$settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive

Register-ScheduledTask -TaskName 'QuantDailyTest' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force

Write-Host "Task registered!"
Get-ScheduledTask -TaskName 'QuantDailyTest' | Format-List TaskName, State
