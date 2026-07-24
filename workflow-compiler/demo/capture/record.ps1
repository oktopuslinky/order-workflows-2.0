# Screen-record the take with ffmpeg gdigrab.
#
#   .\record.ps1 -Name app      # start; writes raw-app.mp4 + raw-app.start.json
#   .\record.ps1 -Stop          # stop cleanly (sends 'q' to ffmpeg's stdin)
#
# Records the FULL desktop rather than a window title: Chrome's title changes on
# every route ("Compile - ..." -> "Project ..."), which would break `-i title=`
# mid-take. We crop to the browser viewport later in Remotion, using the rect
# measured over CDP -- which also gives us zooms for free.
#
# The .start.json epoch timestamp is the coarse clock zero. The magenta
# clapperboard flash (see sync-flash) refines it to the exact frame.

param(
    [string]$Name = "app",
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$OutDir = $PSScriptRoot
$PidFile = Join-Path $OutDir ".ffmpeg-$Name.pid"

if ($Stop) {
    if (-not (Test-Path $PidFile)) { throw "Not recording (no $PidFile)" }
    $ffpid = [int](Get-Content $PidFile)
    $out = Join-Path $OutDir "raw-$Name.mp4"
    Write-Host "Stopping ffmpeg (pid $ffpid)..."

    # The mp4 index (moov atom) is held in memory and written only on a clean exit.
    # `taskkill` does NOT deliver that: it killed ffmpeg mid-take once and left a
    # 152 MB file that no player would open ("moov atom not found"). ffmpeg exits
    # cleanly on Ctrl-C, so attach to its console and raise CTRL_C_EVENT there.
    # We must disable Ctrl-C handling in *this* process first, or we kill ourselves.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class FfStop {
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool AttachConsole(uint pid);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool FreeConsole();
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool SetConsoleCtrlHandler(IntPtr h, bool add);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool GenerateConsoleCtrlEvent(uint ev, uint group);
  public static string Send(uint pid) {
    FreeConsole();
    if (!AttachConsole(pid)) return "attach failed " + Marshal.GetLastWin32Error();
    SetConsoleCtrlHandler(IntPtr.Zero, true);
    bool ok = GenerateConsoleCtrlEvent(0, 0);   // CTRL_C_EVENT
    return ok ? "ok" : ("ctrl-c failed " + Marshal.GetLastWin32Error());
  }
  public static void Detach() { SetConsoleCtrlHandler(IntPtr.Zero, false); FreeConsole(); }
}
'@
    Write-Host "  ctrl-c: $([FfStop]::Send([uint32]$ffpid))"
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        if (-not (Get-Process -Id $ffpid -ErrorAction SilentlyContinue)) { break }
    }
    [FfStop]::Detach()

    if (Get-Process -Id $ffpid -ErrorAction SilentlyContinue) {
        throw "ffmpeg (pid $ffpid) did not exit. Do NOT taskkill it -- that loses the moov atom and the take. Send it 'q' or Ctrl-C by hand."
    }
    Remove-Item $PidFile -Force

    # Prove the file finalised while the app is still open and re-recordable.
    # A take is only real once ffprobe can read it back.
    $probe = & ffprobe -v error -show_entries format=duration -of csv=p=0 $out 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $probe) {
        throw "raw-$Name.mp4 has no readable index -- the take did not finalise. Recover with recover_mdat.py before re-recording (it will be overwritten)."
    }
    $mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host "Wrote $out ($mb MB, $([math]::Round([double]$probe, 1))s) -- index verified."
    exit 0
}

$Out = Join-Path $OutDir "raw-$Name.mp4"
if (Test-Path $Out) { Remove-Item $Out -Force }

# 15, not 30. gdigrab could not sustain 30 fps on this machine: a 3120-second take
# yielded only 2483 seconds of video (~23.9 fps effective). Dropped frames are stamped
# as if they were consecutive, so the file silently becomes a non-uniform time-lapse and
# every mark->frame mapping drifts -- by ten minutes at the end of that take.
# 15 fps is comfortably inside what the grabber sustains, and the edit speed-ramps the
# long LLM waits anyway, so nothing on screen needs the extra temporal resolution.
# If you change this, re-check: video_duration must equal wall-clock duration.
$Fps = 15

$ffArgs = @(
    "-f", "gdigrab",
    "-framerate", "$Fps",
    "-draw_mouse", "0",          # CDP clicks don't move the real cursor; a stale
                                 # pointer parked mid-screen would be a lie.
    "-i", "desktop",
    "-c:v", "libx264",
    "-preset", "ultrafast",      # cheap encode; we re-encode once in Remotion
    "-crf", "20",
    "-pix_fmt", "yuv420p",
    # Write a FRAGMENTED mp4. A normal mp4 keeps its index (the moov atom) in memory and
    # writes it only on a clean exit -- so any ungraceful stop yields a 100+ MB file that
    # no player will open. That ate take 1. The documented fix (send CTRL_C instead of
    # taskkill) was never actually re-tested, and it does NOT work: ffmpeg takes the
    # CTRL_C and dies without writing the trailer. Verified again on 2026-07-13.
    # Fragmented mp4 writes a self-contained index as it goes, so the file on disk is
    # already playable at every instant and NO stop path can lose the take.
    "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
    "-flush_packets", "1",       # also makes the "is it growing?" check below honest
    # MUST be quoted: Start-Process does not quote -ArgumentList elements, and this
    # repo's path contains spaces and parens ("Code (local)"). Unquoted, ffmpeg
    # gets a mangled path, exits -22, and writes nothing -- silently, because it
    # is spawned detached. That cost a two-hour take once. Do not "simplify" this.
    "-y", "`"$Out`""
)

# Record clock-zero as close to spawn as possible.
$startEpochMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$proc = Start-Process -FilePath "ffmpeg" -ArgumentList $ffArgs -PassThru -WindowStyle Minimized
$proc.Id | Out-File -Encoding ascii $PidFile

# Prove it is actually capturing before the caller commits to a long take.
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 250
    if ($proc.HasExited) {
        throw "ffmpeg exited immediately (code $($proc.ExitCode)). Nothing is being recorded."
    }
    if ((Test-Path $Out) -and ((Get-Item $Out).Length -gt 0)) { $ok = $true; break }
}
if (-not $ok) { throw "ffmpeg produced no bytes after 5s. Nothing is being recorded." }

# Be patient here. A still desktop encodes to almost nothing under x264 ultrafast, and the
# writer flushes in blocks -- so "no growth after 1 second" was a FALSE alarm that aborted a
# perfectly good recorder (and, worse, aborted before start.json was written, losing clock
# zero). Poll until it actually grows.
$size1 = (Get-Item $Out).Length
$size2 = $size1
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { throw "ffmpeg exited (code $($proc.ExitCode)). Nothing is being recorded." }
    $size2 = (Get-Item $Out).Length
    if ($size2 -gt $size1) { break }
}
if ($size2 -le $size1) { throw "Output file stopped growing after 20s. Nothing is being recorded." }

@{
    name          = $Name
    startEpochMs  = $startEpochMs
    fps           = $Fps
    output        = $Out
} | ConvertTo-Json | Out-File -Encoding utf8 (Join-Path $OutDir "raw-$Name.start.json")

Write-Host "Recording CONFIRMED -> $Out  (pid $($proc.Id), t0=$startEpochMs, ${Fps}fps, growing $size1 -> $size2 bytes)"
Write-Host "Leave the machine alone. Stop with: .\record.ps1 -Name $Name -Stop"
