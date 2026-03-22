$python = 'C:\Users\jkw88\miniconda3\envs\volumequant\python.exe'
$script = 'C:\dev\claude-code\quant_py-main\run_daily.py'
$workdir = 'C:\dev\claude-code\quant_py-main'

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $workdir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '06:00'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive

Register-ScheduledTask -TaskName 'QuantDaily' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force

Write-Host "QuantDaily registered!"
Get-ScheduledTask -TaskName 'QuantDaily' | Format-List TaskName, State
