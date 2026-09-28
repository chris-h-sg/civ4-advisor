<#
.SYNOPSIS
Screenshot the Civ IV window to a PNG, without bringing it to the front.

.DESCRIPTION
Uses PrintWindow with PW_RENDERFULLCONTENT, which captures the game's DirectX
surface even while the window is behind others. The image covers the whole
window rect (title bar included), so coordinates read off it are what
post_input.ps1 expects.

.EXAMPLE
.\capture_window.ps1 -Out shot.png
#>
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$ProcId = 0
)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class CivCapture {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
}
"@
$p = if ($ProcId) { Get-Process -Id $ProcId } else { Get-Process Civ4BeyondSword -ErrorAction Stop | Select-Object -First 1 }
$h = $p.MainWindowHandle
$r = New-Object CivCapture+RECT
[CivCapture]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.R - $r.L; $ht = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[CivCapture]::PrintWindow($h, $hdc, 2) | Out-Null   # 2 = PW_RENDERFULLCONTENT
$g.ReleaseHdc($hdc); $g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
"$Out ${w}x${ht}"
