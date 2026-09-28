<#
.SYNOPSIS
Send a click or Enter key to the Civ IV window in the background.

.DESCRIPTION
Posts window messages straight to the game window. The real mouse cursor does
not move and focus does not change, so it is safe while someone is using the
machine. A fallback for dismissing an unexpected popup - anything the mod can
do from Python should be done there instead, since this depends on screen
layout.

Click coordinates are in the frame of a capture_window.ps1 screenshot (window
rect, title bar included) and are converted to client coordinates here.

.EXAMPLE
.\post_input.ps1 -X 643 -Y 553

.EXAMPLE
.\post_input.ps1 -Enter
#>
param(
    [int]$X = -1,
    [int]$Y = -1,
    [switch]$Enter,
    [int]$ProcId = 0
)
Add-Type @"
using System; using System.Runtime.InteropServices;
public class CivInput {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
}
"@
$p = if ($ProcId) { Get-Process -Id $ProcId } else { Get-Process Civ4BeyondSword -ErrorAction Stop | Select-Object -First 1 }
$h = $p.MainWindowHandle

if ($Enter) {
    [CivInput]::PostMessage($h, 0x100, [IntPtr]0x0D, [IntPtr]0x001C0001) | Out-Null   # WM_KEYDOWN VK_RETURN
    Start-Sleep -Milliseconds 60
    [CivInput]::PostMessage($h, 0x101, [IntPtr]0x0D, [IntPtr]0xC01C0001) | Out-Null   # WM_KEYUP
    "posted Enter"
    return
}
if ($X -lt 0 -or $Y -lt 0) { throw "Give -X and -Y, or -Enter." }

$r = New-Object CivInput+RECT; [CivInput]::GetWindowRect($h, [ref]$r) | Out-Null
$o = New-Object CivInput+POINT; [CivInput]::ClientToScreen($h, [ref]$o) | Out-Null
$cx = $X - ($o.X - $r.L); $cy = $Y - ($o.Y - $r.T)
$l = [IntPtr](($cy -shl 16) -bor ($cx -band 0xFFFF))
[CivInput]::PostMessage($h, 0x200, [IntPtr]0, $l) | Out-Null   # WM_MOUSEMOVE
Start-Sleep -Milliseconds 60
[CivInput]::PostMessage($h, 0x201, [IntPtr]1, $l) | Out-Null   # WM_LBUTTONDOWN
Start-Sleep -Milliseconds 60
[CivInput]::PostMessage($h, 0x202, [IntPtr]0, $l) | Out-Null   # WM_LBUTTONUP
"posted click at client ($cx,$cy)"
