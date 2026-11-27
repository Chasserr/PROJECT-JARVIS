$ErrorActionPreference = "Stop"
$Url = "http://127.0.0.1:8765"
$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (!(Test-Path $Edge)) { $Edge = "C:\Program Files\Google\Chrome\Application\chrome.exe" }

if (-not ("JarvisWindowFocus" -as [type])) {
  Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class JarvisWindowFocus {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr extra);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int cmd);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
  public static bool CloseJarvis(IntPtr hWnd) { return PostMessage(hWnd, 0x0010, IntPtr.Zero, IntPtr.Zero); }
  public static IntPtr FindJarvis() {
    IntPtr found = IntPtr.Zero;
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h)) return true;
      StringBuilder s = new StringBuilder(512);
      GetWindowText(h, s, s.Capacity);
      if (s.ToString().IndexOf("JARVIS", StringComparison.OrdinalIgnoreCase) >= 0) { found = h; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
"@
}
$existing = [JarvisWindowFocus]::FindJarvis()
if ($existing -ne [IntPtr]::Zero) {
  # Replace the window instead of only focusing it. A reused Edge app window can
  # keep serving a cached stylesheet, which once hid the Agents rail-button fix
  # until a manual hard refresh.
  [void][JarvisWindowFocus]::CloseJarvis($existing)
  Start-Sleep -Milliseconds 700
}
$LaunchUrl = "$Url/?launch=$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
Start-Process -FilePath $Edge -ArgumentList "--app=$LaunchUrl"
