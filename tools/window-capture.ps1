<#
.SYNOPSIS
  List visible top-level windows, or capture one window / the whole screen to a PNG.
.EXAMPLE
  powershell -File window-capture.ps1 -List
  powershell -File window-capture.ps1 -Title "DeepSeek" -Out D:\shots\dsh.png
  powershell -File window-capture.ps1 -Foreground -Out D:\shots\fg.png
  powershell -File window-capture.ps1 -FullScreen -Out D:\shots\screen.png
#>
param(
  [string]$Title = "",
  [int]$ProcessId = 0,
  [string]$Out = "",
  [switch]$List,
  [switch]$Foreground,
  [switch]$FullScreen
)

# The bot decodes stdout as UTF-8; Windows PowerShell would otherwise emit the
# ANSI/OEM code page and mangle Chinese window titles.
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class QWin {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int value);
}
"@ -ErrorAction SilentlyContinue

try { [QWin]::SetProcessDpiAwareness(2) | Out-Null } catch { }

function Get-TopWindows {
  $result = @()
  foreach ($proc in Get-Process) {
    $handle = $proc.MainWindowHandle
    if ($handle -eq [IntPtr]::Zero) { continue }
    if (-not [QWin]::IsWindowVisible($handle)) { continue }
    $rect = New-Object QWin+RECT
    [QWin]::GetWindowRect($handle, [ref]$rect) | Out-Null
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -le 0 -or $height -le 0) { continue }
    $result += [pscustomobject]@{
      Pid = $proc.Id; Title = $proc.MainWindowTitle; Width = $width; Height = $height;
      Left = $rect.Left; Top = $rect.Top; Handle = $handle
    }
  }
  return $result
}

if ($List) {
  # One 'pid<TAB>title' line per window: the table layout wraps into noise in chat.
  Get-TopWindows | Where-Object { $_.Title -ne '' } | Sort-Object Title |
    ForEach-Object { "$($_.Pid)" + [char]9 + $_.Title }
  return
}

if ($Out -eq "") { Write-Error "-Out <path.png> is required"; exit 2 }
$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

$handle = [IntPtr]::Zero
$label = ""
$bmp = $null

if ($FullScreen) {
  $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bmp.Size)
  $g.Dispose()
  $label = "screen"
}
elseif ($Foreground) {
  $handle = [QWin]::GetForegroundWindow()
  $label = "foreground"
}
else {
  $targets = Get-TopWindows
  if ($ProcessId -ne 0) { $targets = $targets | Where-Object { $_.Pid -eq $ProcessId } }
  if ($Title -ne "") { $targets = $targets | Where-Object { $_.Title -like "*$Title*" } }
  $target = $targets | Sort-Object Width -Descending | Select-Object -First 1
  if ($null -eq $target) { Write-Error "no visible window matched (Title=$Title, ProcessId=$ProcessId)"; exit 3 }
  $handle = $target.Handle
  $label = $target.Title
}

if ($null -eq $bmp -and $handle -ne [IntPtr]::Zero) {
  if ([QWin]::IsIconic($handle)) { [QWin]::ShowWindow($handle, 9) | Out-Null; Start-Sleep -Milliseconds 400 }
  [QWin]::SetForegroundWindow($handle) | Out-Null
  Start-Sleep -Milliseconds 300

  $rect = New-Object QWin+RECT
  [QWin]::GetWindowRect($handle, [ref]$rect) | Out-Null
  $width = $rect.Right - $rect.Left
  $height = $rect.Bottom - $rect.Top
  if ($width -le 0 -or $height -le 0) { Write-Error "window has an empty rect"; exit 4 }

  $bmp = New-Object System.Drawing.Bitmap $width, $height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  $ok = [QWin]::PrintWindow($handle, $hdc, 2)
  $g.ReleaseHdc($hdc)
  $g.Dispose()
  if (-not $ok) {
    $bmp.Dispose()
    $bmp = New-Object System.Drawing.Bitmap $width, $height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bmp.Size)
    $g.Dispose()
  }
}

if ($null -eq $bmp) { Write-Error "nothing captured"; exit 5 }

$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$size = "{0}x{1}" -f $bmp.Width, $bmp.Height
$bmp.Dispose()
$info = Get-Item $Out
Write-Output ("CAPTURED " + $info.FullName)
Write-Output ("LABEL " + $label)
Write-Output ("SIZE " + $size)
Write-Output ("BYTES " + $info.Length)