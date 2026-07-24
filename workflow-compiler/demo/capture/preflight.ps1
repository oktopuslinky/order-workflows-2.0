# Put the desktop into a recordable state, and prove it -- run before every take.
#
#   .\preflight.ps1
#
# gdigrab records whatever is on top of the whole desktop for ~50 minutes. Everything
# below is a lesson from a take that had to be thrown away:
#
#   * A second Chrome window from the demo profile existed, so CDP was driving one
#     surface while another was on screen. The calibration flash went to the hidden one.
#   * SetForegroundWindow returned $true and did nothing: Windows refuses foreground
#     steals from a background process unless you AttachThreadInput to the current
#     foreground thread first.
#   * ShowWindow is synchronous and hangs on a non-responding window (an Android
#     emulator hung it for two minutes). ShowWindowAsync/PostMessage cannot hang.
#   * Credentials were sitting in Notepad title bars, in frame.

# The demo Chrome is identified by a substring of its --user-data-dir. Which one depends on
# who is driving:
#   launch-chrome.ps1 + chrome-devtools MCP -> "wfc-demo-chrome-profile"  (CDP on :9222)
#   Playwright MCP                          -> "ms-playwright-mcp"        (its own profile,
#                                              driven over a debug *pipe*, so there is no
#                                              CDP port to point anything at -- drive it
#                                              through the MCP, not launch-chrome.ps1)
# Everything downstream (record/flash/calibrate) only cares that exactly one such browser
# is on screen and foreground, so the driver is a parameter, not a rewrite.
param(
    [string]$ProfileMatch = "wfc-demo-chrome-profile"
)

$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class Pre {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RC r);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [StructLayout(LayoutKind.Sequential)] public struct RC { public int L,T,Rt,B; }

  static bool Real(IntPtr h, out string title, out RC r) {
    title = null; GetWindowRect(h, out r);
    if (!IsWindowVisible(h) || IsIconic(h)) return false;
    var sb = new StringBuilder(300); GetWindowText(h, sb, 300);
    if (sb.Length == 0) return false;
    title = sb.ToString();
    if (title == "Program Manager" || title == "Windows Input Experience") return false;
    return (r.Rt - r.L) >= 200 && (r.B - r.T) >= 100;
  }

  /** Minimize every visible window except the keeper. PostMessage, never ShowWindow. */
  public static int ClearExcept(uint keepPid) {
    var hits = new System.Collections.Generic.List<IntPtr>();
    EnumWindows((h,l) => {
      string t; RC r;
      if (!Real(h, out t, out r)) return true;
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid != keepPid) hits.Add(h);
      return true;
    }, IntPtr.Zero);
    foreach (var h in hits) { PostMessage(h, 0x0112, (IntPtr)0xF020, IntPtr.Zero); }  // SC_MINIMIZE
    return hits.Count;
  }

  public static string Remaining() {
    var sb2 = new StringBuilder();
    EnumWindows((h,l) => {
      string t; RC r;
      if (!Real(h, out t, out r)) return true;
      uint pid; GetWindowThreadProcessId(h, out pid);
      sb2.Append(pid + "|" + r.L + "," + r.T + "," + r.Rt + "," + r.B + "|" + t + "\n");
      return true;
    }, IntPtr.Zero);
    return sb2.ToString();
  }

  /** Foreground for real. A bare SetForegroundWindow from a background process no-ops. */
  public static bool Raise(uint pid) {
    IntPtr target = IntPtr.Zero;
    EnumWindows((h,l) => {
      string t; RC r;
      if (!Real(h, out t, out r)) return true;
      uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid) { target = h; return false; }
      return true;
    }, IntPtr.Zero);
    if (target == IntPtr.Zero) return false;
    uint dummy = 0;
    uint fg = GetWindowThreadProcessId(GetForegroundWindow(), out dummy);
    uint me = GetCurrentThreadId();
    AttachThreadInput(me, fg, true);
    ShowWindowAsync(target, 9);              // SW_RESTORE: a maximized window cannot be resized by CDP
    SetForegroundWindow(target);
    AttachThreadInput(me, fg, false);
    return GetForegroundWindow() == target;
  }
}
'@

# --- exactly one Chrome on the demo profile -----------------------------------
$browsers = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -like "*$ProfileMatch*" -and $_.CommandLine -notlike "*--type=*" })

if ($browsers.Count -eq 0) { throw "No demo Chrome running (no browser with '$ProfileMatch' in its --user-data-dir). Start it with launch-chrome.ps1, or open the app through the Playwright MCP and pass -ProfileMatch ms-playwright-mcp." }
if ($browsers.Count -gt 1) {
    throw "$($browsers.Count) demo Chrome browser processes are running. CDP may drive a window that is not the one on screen -- that is exactly how the last take lost its calibration. Close all but one."
}
$chromePid = [uint32]$browsers[0].ProcessId
Write-Host "demo Chrome browser pid = $chromePid"

# --- clear the desktop --------------------------------------------------------
$n = [Pre]::ClearExcept($chromePid)
Write-Host "minimized $n other window(s)"
Start-Sleep -Milliseconds 1200

# --- foreground it, and verify ------------------------------------------------
if (-not [Pre]::Raise($chromePid)) { throw "Could not bring the demo Chrome to the foreground. Nothing else can proceed -- gdigrab records whatever is on top." }
Write-Host "demo Chrome is foreground (verified)"

# --- report anything still in frame -------------------------------------------
Start-Sleep -Milliseconds 800
$left = [Pre]::Remaining().Trim()
Write-Host ""
Write-Host "still visible:"
foreach ($line in ($left -split "`n" | Where-Object { $_ })) {
    $isChrome = $line -match "^$chromePid\|"
    if ($isChrome) { Write-Host "  [KEEP] $line" -ForegroundColor Green }
    else           { Write-Host "  [!!!!] $line" -ForegroundColor Yellow }
}
Write-Host ""
# NOTE on resizing under Playwright: browser_resize / setViewportSize does NOT resize the
# window -- it installs a device-metrics *emulation* (and forces dpr to 1) while the real
# window, which is what gdigrab records, stays put. Resize the actual window instead:
#   Browser.setWindowBounds {left:0, top:0, width:1520, height:900} on a raw CDP session.
Write-Host "Next: size the real window to 1520x900, inject instrument.js, __demoReset(),"
Write-Host "      start record.ps1, then __demoCalibrate(15000) and RUN check_flash.py."
Write-Host "      Do not start the take until check_flash.py prints ALL 4 MARKERS VISIBLE."
