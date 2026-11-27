$ErrorActionPreference = "Stop"
$Url = "http://127.0.0.1:8765"
$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (!(Test-Path $Edge)) { $Edge = "C:\Program Files\Google\Chrome\Application\chrome.exe" }
$Browser = [System.IO.Path]::GetFileNameWithoutExtension($Edge)

if (-not ("JarvisAppWindow" -as [type])) {
  Add-Type @"
using System;
using System.Text;
using System.Diagnostics;
using System.Runtime.InteropServices;
public class JarvisAppWindow {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr extra);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

  // Only the browser app window counts: it must use the browser's window class,
  // be owned by the browser process, and be titled exactly "JARVIS". Console
  // windows such as "JARVIS Core API" therefore never match.
  public static IntPtr Find(string browserProcess) {
    IntPtr found = IntPtr.Zero;
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h)) return true;
      StringBuilder cls = new StringBuilder(256);
      GetClassName(h, cls, cls.Capacity);
      if (!string.Equals(cls.ToString(), "Chrome_WidgetWin_1", StringComparison.Ordinal)) return true;
      StringBuilder title = new StringBuilder(512);
      GetWindowText(h, title, title.Capacity);
      if (!string.Equals(title.ToString(), "JARVIS", StringComparison.Ordinal)) return true;
      uint pid;
      GetWindowThreadProcessId(h, out pid);
      try {
        if (!string.Equals(Process.GetProcessById((int)pid).ProcessName, browserProcess, StringComparison.OrdinalIgnoreCase)) return true;
      } catch { return true; }
      found = h;
      return false;
    }, IntPtr.Zero);
    return found;
  }

  public static void Close(IntPtr hWnd) { PostMessage(hWnd, 0x0010, IntPtr.Zero, IntPtr.Zero); }
}
"@
}

$existing = [JarvisAppWindow]::Find($Browser)
if ($existing -ne [IntPtr]::Zero) {
  # Replace the window instead of focusing it, so the page reloads and picks up
  # the current stylesheet.
  [JarvisAppWindow]::Close($existing)
  Start-Sleep -Milliseconds 700
}
Start-Process -FilePath $Edge -ArgumentList "--app=$Url"
