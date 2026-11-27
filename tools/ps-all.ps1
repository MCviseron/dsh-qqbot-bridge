Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ForEach-Object {
  "pid=" + $_.ProcessId + " | " + ($_.CommandLine -replace '\s+', ' ')
}
