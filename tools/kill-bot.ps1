# Stop every python process that runs this project's bot/main.py, plus the panel port owner.
$ErrorActionPreference = 'SilentlyContinue'
$killed = @()
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object {
  $killed += $_.ProcessId
  Stop-Process -Id $_.ProcessId -Force
}
# Anything still holding the panel port
$owners = Get-NetTCPConnection -LocalPort 39062 -State Listen | Select-Object -ExpandProperty OwningProcess
foreach ($pid in $owners) {
  if ($pid -and ($killed -notcontains $pid)) { $killed += $pid; Stop-Process -Id $pid -Force }
}
"killed: " + ($killed -join ',')
