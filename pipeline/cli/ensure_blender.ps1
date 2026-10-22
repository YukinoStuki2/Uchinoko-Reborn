# ensure_blender.ps1 -- Fetch/extract/patch the Blender portable build (4.3.2 windows-x64).
#
# Background (u54 Blender unbundling): the bundled Blender portable (uncompressed
# ~989MB) made up about 90% of the distribution zip, and was the main driver of
# BOOTH storage limits and build time. Blender itself was removed from the
# distribution zip; this script fetches it from the official site
# (download.blender.org) on first launch instead.
# The injection work that build\make_dist.ps1 used to do at build time (copying
# ooz.pyd / pyooz dist-info / python3.dll into Blender's bundled Python, and the
# 3 VC++ runtime DLLs from blender.crt\ into python\bin\ and site-packages\) has
# moved to this fetch step (this is the only point in time where a
# freshly-downloaded Blender actually exists).
#
# Shared by both the GUI (app\DiveToPalworld.cs) and the CUI (pipeline\cli\convert.ps1).
# PowerShell edition: written for Windows PowerShell 5.1 compatibility, same as
# convert.ps1 (the distributed environment may not have pwsh, and convert.ps1
# falls back to powershell.exe; do not use PS7-only syntax such as the ternary
# or null-coalescing operators).
#
# Usage:
#   powershell -File ensure_blender.ps1 -AppRoot <distribution root (equiv. to _internal)>
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -SourceZip <path>  # offline/test use, skips download
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -Force            # re-fetch even if already present
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -DownloadUrlOverride <url>
#       # test-only: override the official-site fetch URL (used to confirm fail-closed
#       # behavior by injecting an invalid URL. Used by the negative control (a) in
#       # tests\shipcheck\dist_smoke.py. Do not set this in normal operation)
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -MirrorUrlOverride <url>
#       # test-only: override the R2 mirror fetch URL (dev#62, lets unit tests for the
#       # fallback path point at e.g. a local HTTP server. Do not set this in normal
#       # operation)
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -CheckOnly
#       # dev#230: run only Test-D2PMarkerValid (exe present + marker present +
#       # version/sha256/patched all match) and exit immediately (no download,
#       # extraction, or progress output at all).
#       # This lightweight path exists so the caller (app\DiveToPalworld.cs /
#       # convert.ps1) centralizes the validity decision here instead of reverting to
#       # the dead "skip full marker validation just because the exe already exists"
#       # repair logic. Exit code 0 = valid, non-zero = invalid (exe missing / marker
#       # missing / malformed / generation mismatch -- the exact reason is not
#       # reported; the caller should simply fall back to the full run [without
#       # -CheckOnly] on any non-zero result, so there is no need to branch on reason)
#
# dev#62 (source fallback): after a real user report (ZC87VNQX) that direct downloads
# from the official site (download.blender.org) return HTTP 403 in some regions, this
# script now automatically falls back to the R2 mirror (dl.osakishokai.com, the
# existing d2p-dist distribution backend) only if fetching from the official site
# fails. SHA256 verification (see $ExpectedSha256 below) is always enforced regardless
# of which source succeeded (defense against a compromised mirror; both sources share
# the same verification code path, so this stays consistent). If both sources fail,
# this shows guidance (Show-D2PFailureGuidance, including manual placement steps) and
# fails closed. Following the "three-point set" principle for external dependency
# paths (auto-discovery -> manual override -> logging), both which URL was tried and
# why it failed are always logged to stdout.
# Goal: <AppRoot>\assets\tools\blender-4.3.2-windows-x64\blender.exe exists, and the
# post-processing completion marker <same dir>\.d2p_patched.json is valid.
#
# Exit code: 0 = Blender is ready to use. Non-zero = failure
#   (on failure, guidance is printed. The guidance text includes the
#    machine-detectable marker string [D2P_BLENDER_SETUP_FAIL]).
# Progress: lines of the form `##PROGRESS## <0-100> <phase>` are streamed to stdout.
#   (app\DiveToPalworld.cs's AppendLog() already parses this same format to update
#    busyBar/statusLabel, so no new GUI-side parser was added -- this follows that
#    existing convention).
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -ShapeSelfTest
#       # test-only (dev#368): runs Get-D2PPathShape (a diagnostic helper that redacts
#       # a path down to its structure only) against a built-in table of inputs, and
#       # prints `SHAPE<TAB>name<TAB>result` lines to stdout, then exits immediately.
#       # A broken path string passed via the command line would get mangled by
#       # argument parsing before it could be unit tested, so the inputs live inside
#       # the script itself instead. The -AppRoot value is unused (a dummy value is
#       # enough to satisfy Mandatory). This follows the same "give the binary a
#       # headless self-check path" convention already used by
#       # app\DiveToPalworld.cs --check-blender-setup-decision.
param(
    [Parameter(Mandatory = $true)][string]$AppRoot,
    [string]$SourceZip,
    [switch]$Force,
    [string]$DownloadUrlOverride,
    [string]$MirrorUrlOverride,
    [switch]$CheckOnly,
    [switch]$ShapeSelfTest
)
$ErrorActionPreference = "Stop"
# Same fix as convert.ps1: when stdout is redirected from a GUI/subprocess, the
# default encoding becomes cp932, and even a single mis-decoded character can
# corrupt the caller's string matching (progress parsing, guidance display).
# Force UTF-8 explicitly (if this fails, just continue -- see convert.ps1's
# comments for the full background).
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$BlenderVersion = "4.3.2"
$BlenderDirName = "blender-$BlenderVersion-windows-x64"
# Confirmed to exist (directory listing at https://download.blender.org/release/Blender4.3/).
$DownloadUrl = "https://download.blender.org/release/Blender4.3/blender-4.3.2-windows-x64.zip"
if ($DownloadUrlOverride) { $DownloadUrl = $DownloadUrlOverride }
# dev#62: fallback target used when the official-site fetch fails (R2 mirror, the
# d2p-dist distribution backend. Served from the same bucket/Worker as
# devtools\dist_publish.py; the key is under deps\, same object as the official zip).
$MirrorDownloadUrl = "https://dl.osakishokai.com/deps/blender-$BlenderVersion-windows-x64.zip"
if ($MirrorUrlOverride) { $MirrorDownloadUrl = $MirrorUrlOverride }
# Pinned SHA256. Source: https://download.blender.org/release/Blender4.3/blender-4.3.2.sha256
# (a per-version manifest file rather than an individual .sha256, the
# blender-4.3.2-windows-x64.zip line). Also confirmed to match a self-computed sha256sum
# of the actual downloaded file (see work\u54_unbundle\wpA\REPORT.md for the real-download
# verification record).
# dev#62: this same hash is checked regardless of whether the source was the official
# site or the mirror (defense against a compromised mirror. After the "fetch zip" block
# below, a single verification code path is used no matter which source was used). The
# actual SHA256 of the object placed on the mirror was confirmed via a read-back check
# right after upload, equivalent to what devtools\dist_publish.py does.
$ExpectedSha256 = "933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6"
$RequiredFreeBytes = 2.5 * 1GB  # download zip (~390MB) + extracted (~1GB) + working-copy headroom

# dev#368: this sits outside the try{} below, so a failure here would die on a raw
# .NET exception with no [D2P_BLENDER_SETUP_FAIL] marker and no path-structure
# diagnostics at all (observed: passing a nonexistent drive like `Q:\...` makes
# Join-Path throw DriveNotFoundException immediately, leaving the user's log with
# nothing but a raw English exception line -- exactly the "can't get from the log to
# the cause" outcome this project tries hardest to avoid). Join-Path validates that the
# PSDrive actually exists, which makes it unsuitable here; use the pure string
# concatenation of [System.IO.Path]::Combine instead. Existence validation happens
# later inside the try{} block, where a failure is reported with both the marker and
# Get-D2PPathShape.
$ToolsDir = [System.IO.Path]::Combine($AppRoot, "assets\tools")
$TargetDir = [System.IO.Path]::Combine($ToolsDir, $BlenderDirName)
$MarkerFileName = ".d2p_patched.json"
$MarkerPath = [System.IO.Path]::Combine($TargetDir, $MarkerFileName)
# Injection materials bundled by make_dist.ps1 (ooz.pyd / pyooz dist-info / python3.dll).
# The VC++ runtime is not here (it is taken from the downloaded Blender's own blender.crt\).
$PatchMaterialsDir = [System.IO.Path]::Combine($AppRoot, "assets\blender_patch")

$FailMarker = "[D2P_BLENDER_SETUP_FAIL]"

function Write-D2PProgress {
    param([int]$Pct, [string]$Phase)
    Write-Host "##PROGRESS## $Pct $Phase"
}

# dev#199 workaround: setup-time extraction runs under Windows PowerShell 5.1 (.NET
# Framework)'s plain File/Directory APIs, which are bound by the classic Win32
# MAX_PATH (260 characters). dev#149 shortened the "invoke an already-extracted
# Blender at run time" path using an NTFS junction, but that fix only applies once the
# real thing already exists on disk -- it does not help with "the extraction itself",
# which is what this function handles (out of scope for dev#149). Here we prepend the
# `\\?\` long-path prefix (the Win32 Extended-Length Path syntax) so MAX_PATH is
# bypassed regardless of the registry's LongPathsEnabled setting. The .NET Framework
# APIs this script's extraction already uses (System.IO.Compression.ZipFileExtensions /
# System.IO.Directory) understand this prefix, so only the caller's path string needs
# to be converted (PowerShell's filesystem-provider cmdlets (New-Item/Copy-Item etc.)
# handle `\\?\` inconsistently, so this is applied only to the raw API calls that
# already exist in the extraction path).
function Get-D2PLongPath {
    param([string]$Path)
    if ($Path.StartsWith("\\?\")) { return $Path }
    if ($Path.StartsWith("\\")) { return "\\?\UNC\" + $Path.Substring(2) }
    return "\\?\" + $Path
}

# dev#368: a structure-preserving redaction helper that records "what shape of path was
# passed" on failure, without leaking personal information. It follows the same idea as
# the existing similar helpers (convert.ps1's Get-PathFacts / app\DiveToPalworld.cs's
# FactifyGenericPath / pipeline\py\path_privacy.py), but those only report up to
# length/non-ASCII/whitespace/UNC. In real user report HMZ87QGE (v2.2.11), the path
# inside the guidance text got collapsed all the way down to `<path len=120>`, and
# **the one thing we actually needed to know -- why the format was invalid -- was lost
# entirely**. This helper goes further: "diagnosable, but not personally identifying":
#   - reported: length / whitespace-only / root kind / separator count / leading and
#           trailing whitespace / wildcard characters and their positions / invalid
#           path-character codes and positions / whether it looks like an unexpanded
#           %VAR% / presence of non-ASCII or whitespace / whether it exists
#   - never reported: the contents of any segment (folder names, usernames), not even
#     one character. The only characters ever echoed back are symbols
#     (`[ ] * ?` and [System.IO.Path]::GetInvalidPathChars()), which are structural
#     symbols that cannot themselves be personal information as Windows folder names.
# The return value is a single ASCII-only line (so it never breaks the caller's log
# formatting or the GUI's string matching).
function Get-D2PPathShape {
    param($Path)
    if ($null -eq $Path) { return "len=null blank=True root=none" }
    $p = [string]$Path
    $parts = @()
    $parts += "len=$($p.Length)"
    $parts += "blank=$([bool]($p.Trim().Length -eq 0))"
    # Root kind (never report the raw drive letter -- whether it is C: or D: is not
    # diagnostically useful and could help identify the environment; we only say
    # "drive")
    $root = "relative"
    if ($p.Trim().Length -eq 0) { $root = "none" }
    elseif ($p.StartsWith("\\?\") -or $p.StartsWith("\\.\")) { $root = "extended" }
    elseif ($p.StartsWith("\\")) { $root = "unc" }
    elseif ($p -match '^[A-Za-z]:[\\/]') { $root = "drive" }
    elseif ($p -match '^[A-Za-z]:') { $root = "driveRelative" }
    elseif ($p.StartsWith("\") -or $p.StartsWith("/")) { $root = "rootRelative" }
    $parts += "root=$root"
    # (PS5.1's parser cannot use a nested double-quoted string inside $() within a
    #  double-quoted string, so this is assigned to a variable first and then embedded)
    $segCount = @($p -split '[\\/]+' | Where-Object { $_.Length -gt 0 }).Count
    $parts += "segs=$segCount"
    $parts += "nonAscii=$([bool](@($p.ToCharArray() | Where-Object { [int]$_ -gt 127 }).Count -gt 0))"
    $parts += "space=$($p.Contains(' '))"
    $parts += "leadWs=$([bool]($p.Length -gt 0 -and [char]::IsWhiteSpace($p[0])))"
    $parts += "trailWs=$([bool]($p.Length -gt 0 -and [char]::IsWhiteSpace($p[$p.Length - 1])))"
    $parts += "trailSep=$([bool]($p.EndsWith('\') -or $p.EndsWith('/')))"
    # Wildcard characters (trigger PowerShell's glob interpretation. This was the true
    # root cause of dev#368). Positions (0-based) are reported too. A position is a
    # number, never personal information.
    $wild = @()
    for ($i = 0; $i -lt $p.Length; $i++) {
        if ("[]*?".IndexOf($p[$i]) -ge 0) { $wild += ("" + $p[$i] + "@" + $i) }
    }
    if ($wild.Count -eq 0) { $parts += "wildcard=none" } else { $parts += "wildcard=" + ($wild -join ",") }
    # [System.IO.Path]::GetInvalidPathChars() (" < > | and control chars 0x00-0x1F).
    # Reported as a hex code rather than the raw character (so a raw newline etc. never
    # ends up mixed into the log).
    $invalidSet = [System.IO.Path]::GetInvalidPathChars()
    $bad = @()
    for ($i = 0; $i -lt $p.Length; $i++) {
        if ($invalidSet -contains $p[$i]) { $bad += ("0x{0:x2}@{1}" -f [int]$p[$i], $i) }
    }
    if ($bad.Count -eq 0) { $parts += "invalid=none" } else { $parts += "invalid=" + ($bad -join ",") }
    $parts += "quote=$($p.Contains('"'))"
    $parts += "env=$([bool]($p -match '%[A-Za-z_][A-Za-z0-9_()]*%'))"
    $ex = "?"
    try { $ex = [string](Test-Path -LiteralPath $p) } catch { $ex = "?" }
    if ($ex -eq "") { $ex = "?" }
    $parts += "exists=$ex"
    return ($parts -join " ")
}

# dev#368: -ShapeSelfTest (test-only). Broken path strings are kept in this in-script
# table because passing them through the command line would mangle them during
# argument parsing. Also includes a negative control (a well-formed path) and a
# "path containing something that looks like a real name" case (to demonstrate the
# redaction).
$script:ShapeSelfTestCases = [ordered]@{
    "empty"            = ""
    "space_only"       = "   "
    "tab_only"         = "`t"
    "newline_only"     = "`n"
    "wildcard_bracket" = "C:\Games\Uchinoko [v2]\_internal"
    "wildcard_star"    = "C:\Games\Uchi*noko"
    "wildcard_qmark"   = "C:\Games\Uchi?noko"
    "quoted"           = '"C:\Games\Uchinoko"'
    "trailing_quote"   = 'C:\Games\Uchinoko"'
    "trailing_newline" = "C:\Games\Uchinoko`n"
    "pipe_char"        = "C:\Games\Uchi|noko"
    "unexpanded_env"   = "%LOCALAPPDATA%\Uchinoko"
    "relative"         = "relative\path"
    "unc"              = "\\server\share\Uchinoko"
    "extended"         = "\\?\C:\Games\Uchinoko"
    "trailing_sep"     = "C:\Games\Uchinoko\"
    "leading_space"    = " C:\Games\Uchinoko"
    "name_like"        = "C:\Users\YamadaTaro\Documents\MyAvatars\Uchinoko"
    "valid_control"    = "C:\Games\Uchinoko\_internal"
}

if ($ShapeSelfTest) {
    foreach ($k in $script:ShapeSelfTestCases.Keys) {
        Write-Host ("SHAPE`t" + $k + "`t" + (Get-D2PPathShape $script:ShapeSelfTestCases[$k]))
    }
    # One more case for $null (what happens if the GUI never delivered a value)
    Write-Host ("SHAPE`tnull`t" + (Get-D2PPathShape $null))
    exit 0
}

function Test-D2PMarkerValid {
    param([string]$Dir, [string]$MarkerFile)
    if (-not (Test-Path -LiteralPath (Join-Path $Dir "blender.exe"))) { return $false }
    if (-not (Test-Path -LiteralPath $MarkerFile)) { return $false }
    try {
        # The marker is written as UTF-8 (no BOM) (see WriteAllText below). Read it back
        # with UTF-8 explicitly too (current content is ASCII-only, but this follows the
        # same "write UTF-8, read UTF-8" convention as job.json).
        $m = Get-Content -LiteralPath $MarkerFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($m.version -ne $BlenderVersion) { return $false }
        if ($m.sha256 -ne $ExpectedSha256) { return $false }
        if ($m.patched -ne $true) { return $false }
        return $true
    } catch {
        return $false
    }
}

function Invoke-D2PDownloadWithProgress {
    param([string]$Url, [string]$Dest)
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.UserAgent = "DiveToPalworld-ensure_blender/1.0"
    $req.Timeout = 120000
    $resp = $req.GetResponse()
    try {
        $total = $resp.ContentLength
        $inStream = $resp.GetResponseStream()
        $outStream = [System.IO.File]::Create($Dest)
        try {
            $buffer = New-Object byte[] (1024 * 1024)
            $readTotal = [long]0
            $lastPct = -1
            while ($true) {
                $read = $inStream.Read($buffer, 0, $buffer.Length)
                if ($read -le 0) { break }
                $outStream.Write($buffer, 0, $read)
                $readTotal += $read
                if ($total -gt 0) {
                    # Download progress is mapped onto the 10-60% range of the whole bar
                    $pct = 10 + [int](($readTotal / [double]$total) * 50)
                    if ($pct -ne $lastPct) {
                        $mbDone = [Math]::Round($readTotal / 1MB, 1)
                        $mbTotal = [Math]::Round($total / 1MB, 1)
                        Write-D2PProgress $pct "Downloading (${mbDone}MB / ${mbTotal}MB)"
                        $lastPct = $pct
                    }
                }
            }
        } finally {
            $outStream.Close()
            $inStream.Close()
        }
    } finally {
        $resp.Close()
    }
}

function Show-D2PFailureGuidance {
    param([string]$ReasonText)
    Write-Host ""
    Write-Host "$FailMarker Blender setup failed."
    Write-Host "Reason: $ReasonText"
    Write-Host ""
    Write-Host "What to try:"
    Write-Host "  1. Check your internet connection, then press `"Full Convert (Create MOD)`" or `"Update Preview`" again."
    Write-Host "  2. If automatic download keeps failing, you can also set it up manually:"
    Write-Host "       (1) Download the Windows x64 Portable (zip) build of Blender $BlenderVersion from https://www.blender.org/download/"
    Write-Host "       (2) Extract it, then copy the contents of the folder containing blender.exe directly into:"
    Write-Host "           $TargetDir"
    # dev#1608: this step used to be a dead end (the app never looked at what was placed here
    # and always re-downloaded, see the "adopt existing" block above). It now works: the next
    # full run applies the same verification a fresh download gets directly against what was
    # placed here, and uses it if it passes.
    Write-Host "       (3) Press `"Full Convert (Create MOD)`" or `"Update Preview`" again -- the app will verify what you placed and use it (no re-download)."
    # dev#1608: two independent real user reports (67H3ETNH / UDBBTGAA) hit a selective
    # disappearance of python.exe from a successful download+extraction, with security software
    # quarantine the most plausible unconfirmed cause (this project's distribution has a history
    # of AV false positives on the bundled Python, see dev#316/#533/#285). Point users at this
    # possibility directly rather than leaving them stuck retrying the same failure.
    Write-Host "  3. If a specific file is missing after extraction (for example python.exe), your security software may have quarantined it. Check your antivirus/security software's quarantine log and restore the file, or add an exclusion for the folder above, then try again."
    Write-Host ""
    # dev#368: always leave a record of "what shape of path was being handled" on
    # failure. In real user report HMZ87QGE (v2.2.11), $TargetDir inside the guidance
    # text got redacted by the GUI (FactifyGenericPath) down to `<path len=120>`, which
    # made it impossible to diagnose why the format was invalid. Printing the shape
    # separately here means the cause (a glob character, whitespace, an unexpanded
    # %VAR%, an invalid character...) can still be found even with the raw path
    # withheld. No folder name or username is ever included (see Get-D2PPathShape's
    # comments). This is placed after the guidance because the user should read the
    # remedy first.
    Write-Host "Diagnostic info (path structure only, no folder names included):"
    Write-Host "  [D2P_PATH_SHAPE] step=AppRoot(received as argument) $(Get-D2PPathShape $AppRoot)"
    Write-Host "  [D2P_PATH_SHAPE] step=TargetDir(built from AppRoot) $(Get-D2PPathShape $TargetDir)"
    Write-Host ""
}

# dev#1608: shared post-processing (patch materials injection + import-ooz functional
# verification + marker write) used by both the normal flow (BlenderRoot = the freshly
# extracted temp directory, before the atomic move into $TargetDir) and the manual-placement
# adoption flow added below (BlenderRoot = $TargetDir directly -- there is nothing to move,
# the user already placed the files there). This is a straight extraction of what used to be
# inline code in the main try{} block (dev#577's "verify import ooz before trusting the
# marker" logic); behavior for the normal flow is unchanged.
#
# Throws on any failure (same fail-closed contract as the rest of this script). $CleanupOnFailureDir
# (optional): recursively removed if a step below throws. Pass this for the normal flow's temp
# extraction directory (nothing valuable is lost -- it is about to be re-created by the next run
# anyway). Omit for the adoption flow: $BlenderRoot IS $TargetDir there, and a half-applied patch
# attempt left behind is harmless (this function only ever adds/overwrites files, never removes
# blender.exe or anything the user placed) -- the next full download replaces the whole directory
# anyway if adoption keeps failing.
function Invoke-D2PPatchAndVerify {
    param([string]$BlenderRoot, [string]$CleanupOnFailureDir = $null)

    function Fail-D2PPatch {
        param([string]$Msg)
        if ($CleanupOnFailureDir) {
            Remove-Item -LiteralPath $CleanupOnFailureDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw $Msg
    }

    # dev#368: $BlenderRoot may itself contain glob characters (the normal flow's temp dir is a
    # GUID so it never does, but $TargetDir -- used directly by the adoption path -- is built
    # from $AppRoot, which can). Escape only the base path; the trailing
    # "*\python\bin\python.exe" wildcard segment is intentional.
    $bpySearch = Join-Path ([System.Management.Automation.WildcardPattern]::Escape($BlenderRoot)) "*\python\bin\python.exe"
    $bpyExe = Get-ChildItem $bpySearch -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $bpyExe) {
        # dev#1608: leave a diagnostic trail of what actually landed on disk, to help tell apart
        # "AV quarantined just python.exe" from other causes on the next report (real user
        # reports 67H3ETNH / UDBBTGAA hit exactly this branch with nothing further to go on).
        # Only Blender's own bundled directory/file names are ever logged here (never anything
        # from the user's install path itself), staying within this project's
        # no-personal-data-in-logs convention (see Get-D2PPathShape's comments).
        $diagEntries = @(Get-ChildItem -LiteralPath $BlenderRoot -ErrorAction SilentlyContinue)
        $diagTopNames = @($diagEntries | ForEach-Object { $_.Name })
        $diagVerDirs = @($diagEntries | Where-Object { $_.PSIsContainer -and ($_.Name -match '^\d+\.\d+$') })
        $diagCheckedRel = @()
        $diagPythonBinFound = $false
        foreach ($vd in $diagVerDirs) {
            $rel = Join-Path $vd.Name "python\bin"
            $diagCheckedRel += $rel
            if (Test-Path -LiteralPath (Join-Path $BlenderRoot $rel)) { $diagPythonBinFound = $true }
        }
        $topSummary = "(none)"
        if ($diagTopNames.Count -gt 0) { $topSummary = ($diagTopNames -join ", ") }
        $checkedSummary = "(no version-numbered directory found)"
        if ($diagCheckedRel.Count -gt 0) { $checkedSummary = ($diagCheckedRel -join ", ") }
        Write-Host ("  [D2P_EXTRACT_DIAG] top_level_item_count=$($diagTopNames.Count) top_level_items=$topSummary")
        Write-Host ("  [D2P_EXTRACT_DIAG] python_bin_subdir_checked=$checkedSummary python_bin_subdir_present=$diagPythonBinFound")
        Fail-D2PPatch "python\bin\python.exe was not found inside the extracted Blender"
    }
    # (-Parent cannot be combined with -LiteralPath. This does not trigger glob interpretation.)
    $pyRoot = Split-Path (Split-Path $bpyExe.FullName -Parent) -Parent   # <ver>\python
    $sitePackages = Join-Path $pyRoot "lib\site-packages"
    $pyBin = Join-Path $pyRoot "bin"

    if (-not (Test-Path -LiteralPath $PatchMaterialsDir)) {
        Fail-D2PPatch "Patch materials not found: $PatchMaterialsDir (the distribution may be corrupted)"
    }
    $oozPyd = Join-Path $PatchMaterialsDir "ooz.pyd"
    $python3Dll = Join-Path $PatchMaterialsDir "python3.dll"
    $distInfoDirs = @(Get-ChildItem -LiteralPath $PatchMaterialsDir -Directory -Filter "pyooz-*.dist-info" -ErrorAction SilentlyContinue)
    if (-not (Test-Path -LiteralPath $oozPyd) -or -not (Test-Path -LiteralPath $python3Dll) -or $distInfoDirs.Count -eq 0) {
        Fail-D2PPatch "Patch materials are incomplete (ooz.pyd / python3.dll / pyooz-*.dist-info are not all present under $PatchMaterialsDir)"
    }
    Copy-Item -LiteralPath $oozPyd -Destination (Join-Path $sitePackages "ooz.pyd") -Force
    foreach ($di in $distInfoDirs) {
        $destDi = Join-Path $sitePackages $di.Name
        Remove-Item -LiteralPath $destDi -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item -LiteralPath $di.FullName -Destination $destDi -Recurse -Force
    }
    Copy-Item -LiteralPath $python3Dll -Destination (Join-Path $pyBin "python3.dll") -Force

    # The VC++ runtime is taken from the Blender tree's own blender.crt\ (no new files added.
    # STATUS_DLL_NOT_FOUND workaround, see make_dist.ps1's comments for details).
    $crtSrcDir = Join-Path $BlenderRoot "blender.crt"
    $crtNeeded = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    $crtDestDirs = @($pyBin, $sitePackages)
    foreach ($dll in $crtNeeded) {
        $src = Join-Path $crtSrcDir $dll
        if (-not (Test-Path -LiteralPath $src)) {
            Fail-D2PPatch "$dll is missing from blender.crt\ (the Blender portable layout may have changed)"
        }
        foreach ($destDir in $crtDestDirs) {
            Copy-Item -LiteralPath $src -Destination (Join-Path $destDir $dll) -Force
        }
    }

    # --- verify the patch actually works (dev#577): confirm that `import ooz` actually succeeds
    #     before writing the marker. This is the same functional bar a fresh official download
    #     gets -- for the adoption flow (dev#1608) there is no zip to re-hash, so this is the
    #     strongest verification available, and it is not weaker than what a fresh download
    #     goes through (a version/ABI mismatch between a manually-placed Blender and these patch
    #     materials fails here, same as it always has). -I (isolated): so a stray host-side
    #     PYTHONPATH/user site does not produce a false PASS.
    Write-D2PProgress 93 "Verifying Python environment (import ooz)"
    $importCheckOut = Join-Path ([System.IO.Path]::GetTempPath()) ("d2p_ooz_check_$([Guid]::NewGuid().ToString('N'))_stdout.txt")
    $importCheckErr = Join-Path ([System.IO.Path]::GetTempPath()) ("d2p_ooz_check_$([Guid]::NewGuid().ToString('N'))_stderr.txt")
    try {
        # Note (PS5.1): Start-Process naively space-joins each element of -ArgumentList, so an
        # argument containing a space ("import ooz") must be double-quoted by hand (otherwise it
        # is parsed as python -c import ooz and always fails with a SyntaxError -- confirmed by
        # testing).
        $importCheckProc = Start-Process -FilePath $bpyExe.FullName `
            -ArgumentList @("-I", "-c", "`"import ooz`"") `
            -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $importCheckOut `
            -RedirectStandardError $importCheckErr
        if ($importCheckProc.ExitCode -ne 0) {
            $errTail = ""
            try {
                $errLines = @(Get-Content -LiteralPath $importCheckErr -ErrorAction SilentlyContinue | Select-Object -Last 5)
                $errTail = ($errLines -join " / ")
            } catch { }
            Fail-D2PPatch ("Post-patch verification failed (import ooz did not succeed with Blender's " +
                   "bundled Python. exit=$($importCheckProc.ExitCode)). The patch materials " +
                   "(assets\blender_patch\) may be corrupted or incompatible with this " +
                   "environment. Details: $errTail")
        }
    } finally {
        Remove-Item -LiteralPath $importCheckOut -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $importCheckErr -Force -ErrorAction SilentlyContinue
    }
    Write-Host "  Verification OK: import ooz succeeded with Blender's bundled Python"

    # --- write the marker (directly under $BlenderRoot. For the normal flow this is still
    #     inside the temporary extraction directory -- it travels along with the later atomic
    #     move into $TargetDir. For the adoption flow $BlenderRoot already IS $TargetDir.) ---
    $markerObj = [ordered]@{
        version        = $BlenderVersion
        sha256         = $ExpectedSha256
        patched        = $true
        patched_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        patch_items    = @("ooz.pyd", "pyooz-dist-info", "python3.dll",
                            "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    }
    # WP-A2 (2026-07-28): `Set-Content -Encoding utf8` behaves inconsistently depending on the
    # PowerShell engine (PS5.1 writes UTF-8 with a BOM / PS7 writes it without). This script
    # always reads the marker back with Get-Content -Raw so it would not break either way, but
    # to avoid leaving unnecessary non-determinism, it is written explicitly as UTF-8 without a
    # BOM.
    $markerJson = $markerObj | ConvertTo-Json
    $markerUtf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $BlenderRoot $MarkerFileName), $markerJson, $markerUtf8NoBom)
}

# dev#230: -CheckOnly performs no download, extraction, progress output, or guidance at
# all -- it just returns the result of Test-D2PMarkerValid as an exit code (0 = valid /
# non-zero = invalid). Combining this with -Force is meaningless, so that case is not
# handled (CheckOnly is always evaluated first).
if ($CheckOnly) {
    if (Test-D2PMarkerValid $TargetDir $MarkerPath) { exit 0 }
    exit 1
}

try {
    Write-D2PProgress 0 "Checking Blender status"

    if (-not $Force -and (Test-D2PMarkerValid $TargetDir $MarkerPath)) {
        Write-D2PProgress 100 "Blender is ready"
        Write-Host "OK: Blender is already available ($TargetDir)"
        exit 0
    }

    # --- dev#1608: attempt to adopt an existing manually-placed Blender before falling back to
    #     a full download. Two independent real user reports (67H3ETNH / UDBBTGAA) showed that
    #     following this script's own manual-setup guidance (extract the official zip's contents
    #     directly into $TargetDir) was structurally useless before this change: -CheckOnly
    #     (dev#230) correctly refuses to treat "exe present, no marker" as ready (that safety
    #     invariant is untouched -- see Test-D2PMarkerValid/the -CheckOnly branch above), but the
    #     *full* run (this path, only reached because -CheckOnly said no) unconditionally
    #     re-downloaded instead of ever looking at what was already sitting in $TargetDir.
    #     Adoption below applies the exact same verification a fresh official download gets
    #     (Invoke-D2PPatchAndVerify: patch injection + import-ooz functional check) directly
    #     against $TargetDir -- not a weaker bar, just a different starting point. A verification
    #     failure here is not fatal: it is logged and this script falls through to the ordinary
    #     full download below (self-healing; a half-applied adoption attempt left in $TargetDir
    #     is harmless since the full download path below always renames the existing $TargetDir
    #     out of the way before moving the freshly-downloaded tree into place).
    #     Skipped when -Force is given (an explicit request to re-fetch even if already present).
    if (-not $Force -and (Test-Path -LiteralPath (Join-Path $TargetDir "blender.exe"))) {
        Write-Host "  Existing blender.exe found at $TargetDir without a valid setup marker."
        Write-Host "  Attempting to adopt it (dev#1608) before downloading a fresh copy..."
        try {
            Invoke-D2PPatchAndVerify -BlenderRoot $TargetDir
            Write-D2PProgress 100 "Blender setup complete (adopted existing installation)"
            Write-Host "OK: adopted the existing Blender already placed at $TargetDir"
            exit 0
        } catch {
            Write-Host "  Adoption failed, falling back to a full download. Reason: $($_.Exception.Message)"
        }
    }

    # dev#368: New-Item has no -LiteralPath, and -Path is interpreted as a wildcard.
    # To avoid misbehaving on folder names containing `[`, build the directory with the
    # raw .NET API instead (the same convention this script's extraction code already
    # uses).
    [System.IO.Directory]::CreateDirectory($ToolsDir) | Out-Null

    # --- disk free-space check ---
    Write-D2PProgress 5 "Checking free disk space"
    # dev#368 (root cause): the old implementation used
    # `(Resolve-Path $AppRoot).ProviderPath`. Resolve-Path's -Path is interpreted as a
    # wildcard, so a distribution location containing `[` `]` (e.g.
    # `D:\Games\Uchinoko [v2.2.11]\`) matches nothing -- and **a zero-match wildcard
    # does not raise an error** (this passes through silently even with
    # $ErrorActionPreference="Stop"). The result was $null.ProviderPath = $null, and the
    # next line's GetPathRoot then received an empty string and threw
    # `The path is not of a legal form.` (real user report HMZ87QGE, v2.2.11). The fix
    # is -LiteralPath (no glob interpretation). For the same reason, every
    # Test-Path/Get-Content/Copy-Item/Move-Item etc. call in this script has been made
    # to use -LiteralPath consistently (without that consistency, fixing the root cause
    # here would still leave other places silently broken by `[`-containing paths).
    $resolvedAppRootItems = @(Resolve-Path -LiteralPath $AppRoot -ErrorAction SilentlyContinue)
    $resolvedAppRoot = $null
    if ($resolvedAppRootItems.Count -eq 1) { $resolvedAppRoot = $resolvedAppRootItems[0].ProviderPath }
    if ($null -eq $resolvedAppRoot -or $resolvedAppRoot.Trim().Length -eq 0) {
        # Do not swallow this and continue. Name the cause and tell the user what they
        # can do, then stop.
        throw ("Could not resolve the app location (-AppRoot) to an actual path. " +
               "Please move the distribution folder to a location without symbols " +
               "(especially [ ] * ?) or leading/trailing whitespace " +
               "(e.g. C:\Uchinoko) and try again." +
               " Diagnostic: step=AppRoot(received as argument) " + (Get-D2PPathShape $AppRoot))
    }
    $driveRoot = [System.IO.Path]::GetPathRoot($resolvedAppRoot)
    $drive = New-Object System.IO.DriveInfo($driveRoot)
    if ($drive.AvailableFreeSpace -lt $RequiredFreeBytes) {
        $freeGb = [Math]::Round($drive.AvailableFreeSpace / 1GB, 2)
        throw "Not enough free disk space (free space on $driveRoot`: ${freeGb}GB, needed: about 2.5GB). Free up space and try again."
    }

    # --- fetch zip ---
    $downloadedZip = $null
    $zipToUse = $null
    if ($SourceZip) {
        if (-not (Test-Path -LiteralPath $SourceZip)) { throw "The specified -SourceZip was not found: $SourceZip" }
        Write-D2PProgress 60 "Using specified zip (no download, test/offline mode)"
        $zipToUse = (Resolve-Path -LiteralPath $SourceZip).ProviderPath
    } else {
        Write-D2PProgress 10 "Downloading Blender $BlenderVersion (official site, ~390MB)"
        $tempZip = Join-Path ([System.IO.Path]::GetTempPath()) ("d2p_blender_$([Guid]::NewGuid().ToString('N')).zip")
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        } catch { }
        # dev#62: sources are tried in order "official site -> (only on failure) R2
        # mirror". Which one was tried and why it failed are both always logged
        # (three-point-set principle).
        Write-Host "  Source candidate 1 (official site): $DownloadUrl"
        $primaryErrorMsg = $null
        try {
            Invoke-D2PDownloadWithProgress -Url $DownloadUrl -Dest $tempZip
            Write-Host "  Download succeeded (official site)"
        } catch {
            $primaryErrorMsg = $_.Exception.Message
            Remove-Item -LiteralPath $tempZip -Force -ErrorAction SilentlyContinue
            Write-Host "  Failed to fetch from the official site: $primaryErrorMsg"
            Write-Host "  Falling back to source candidate 2 (R2 mirror): $MirrorDownloadUrl"
            Write-D2PProgress 10 "Downloading Blender $BlenderVersion (mirror, ~390MB)"
            try {
                Invoke-D2PDownloadWithProgress -Url $MirrorDownloadUrl -Dest $tempZip
                Write-Host "  Download succeeded (R2 mirror)"
            } catch {
                $mirrorErrorMsg = $_.Exception.Message
                Remove-Item -LiteralPath $tempZip -Force -ErrorAction SilentlyContinue
                throw ("Download failed (both the official site and the mirror failed): " +
                       "official=$primaryErrorMsg / mirror=$mirrorErrorMsg")
            }
        }
        $downloadedZip = $tempZip
        $zipToUse = $tempZip
    }

    # --- SHA256 verification (fail-closed. A user-specified SourceZip is never deleted,
    #     only a zip this script itself downloaded is) ---
    Write-D2PProgress 60 "Verifying integrity (SHA256)"
    $actualHash = (Get-FileHash -LiteralPath $zipToUse -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedSha256) {
        if ($downloadedZip) { Remove-Item -LiteralPath $downloadedZip -Force -ErrorAction SilentlyContinue }
        throw "The downloaded file's SHA256 does not match (got: $actualHash / expected: $ExpectedSha256). Aborting -- the file may be corrupted or tampered with."
    }
    Write-Host "  SHA256 match confirmed: $actualHash"

    # --- extraction (build in a temporary working folder under the same parent
    #     directory as the final location, then move it into place atomically via a
    #     same-volume rename once complete) ---
    # WP-rdp_wsbops (2026-07-29): Expand-Archive is noticeably slower than calling the
    # .NET ZipFile API directly (measured on the dev machine: extracting the same zip
    # [~390MB / 6292 entries] took an average of 24.7s with Expand-Archive vs. 5.7s with
    # a single ZipFile.ExtractToDirectory call. The extra per-entry processing in the
    # Expand-Archive cmdlet layer is the cause). However, the single bulk call goes
    # completely silent until extraction finishes, which would make the "65%-85% is
    # silent" issue noted in rd_126 worse. As a compromise, this calls the .NET API
    # per-entry while reporting progress based on file count (measured: average 15.7s,
    # about 1.6x faster than Expand-Archive while still showing progress along the way).
    # See work\rdp_wsbops\README.md for the full measurement table.
    Write-D2PProgress 65 "Extracting"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # dev#199 workaround (quick, low-risk): shorten the name of the temporary extraction
    # directory. The old name `.tmp_ensure_blender_<32-hex>` (20+32=52 chars) added an
    # extra level of depth that does not exist in the final location, which meant setup
    # extraction alone could fail even in environments where the final runtime path
    # would have stayed under MAX_PATH (dev#199) -- an asymmetric fragility. The GUID
    # itself is kept (for collision avoidance); only the prefix is shortened (52 chars
    # -> 40 chars, freeing up 12 characters of headroom).
    $tmpExtractName = ".tmp_eb_$([Guid]::NewGuid().ToString('N'))"
    $tmpExtractDir = Join-Path $ToolsDir $tmpExtractName
    [System.IO.Directory]::CreateDirectory((Get-D2PLongPath $tmpExtractDir)) | Out-Null
    try {
        $zipArchive = [System.IO.Compression.ZipFile]::OpenRead($zipToUse)
        try {
            $zipEntries = $zipArchive.Entries
            $totalEntries = $zipEntries.Count
            $doneEntries = 0
            $lastReportedPct = -1
            foreach ($zipEntry in $zipEntries) {
                $entryDestPath = Join-Path $tmpExtractDir $zipEntry.FullName
                # dev#199 workaround (belt-and-braces): apply the `\\?\` long-path
                # prefix to the extraction destination path so MAX_PATH is bypassed
                # (see Get-D2PLongPath). Both directory creation and file extraction
                # already use raw .NET API calls, so the prefixed string can be passed
                # straight through.
                $longEntryDestPath = Get-D2PLongPath $entryDestPath
                # A directory entry (name ends with / or \) is created only, nothing else
                if ($zipEntry.FullName.EndsWith("/") -or $zipEntry.FullName.EndsWith("\")) {
                    [System.IO.Directory]::CreateDirectory($longEntryDestPath) | Out-Null
                    continue
                }
                # Split-Path -Parent cannot be combined with -LiteralPath (PS5.1's
                # parameter-set resolver rejects it with "Parameter set cannot be
                # resolved"). However, -Parent without -Resolve is a purely textual
                # split and does not trigger glob interpretation even on a
                # `[`-containing path (verified: `Split-Path 'C:\a[b]\c.txt' -Parent`
                # returns `C:\a[b]`). So this is safe to use as-is.
                $entryDestDir = Split-Path $entryDestPath -Parent
                $longEntryDestDir = Get-D2PLongPath $entryDestDir
                if (-not ([System.IO.Directory]::Exists($longEntryDestDir))) {
                    [System.IO.Directory]::CreateDirectory($longEntryDestDir) | Out-Null
                }
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($zipEntry, $longEntryDestPath, $true)
                $doneEntries++
                if ($totalEntries -gt 0) {
                    # Extraction progress is mapped onto the 65-85% range of the whole
                    # bar (same banding convention as the download)
                    $pct = 65 + [int](($doneEntries / [double]$totalEntries) * 20)
                    if ($pct -ne $lastReportedPct) {
                        Write-D2PProgress $pct "Extracting ($doneEntries / $totalEntries files)"
                        $lastReportedPct = $pct
                    }
                }
            }
        } finally {
            $zipArchive.Dispose()
        }
    } catch {
        Remove-Item -LiteralPath $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        throw "Failed to extract the zip: $($_.Exception.Message)"
    }
    $extractedRoot = Join-Path $tmpExtractDir $BlenderDirName
    if (-not (Test-Path -LiteralPath (Join-Path $extractedRoot "blender.exe"))) {
        Remove-Item -LiteralPath $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        throw "blender.exe was not found in the extracted result (the zip layout may not be what was expected)"
    }
    Write-D2PProgress 85 "Extraction complete"

    # --- post-processing: inject ooz.pyd / pyooz metadata / python3.dll, verify (import ooz),
    #     and write the marker (all inside the temporary extraction directory -- it travels
    #     along with the atomic move into $TargetDir below). dev#1608: this used to be inline
    #     here; it is now the same Invoke-D2PPatchAndVerify function the adoption path above
    #     uses, so both paths go through identical verification (see that function's comments).
    #     (the same injected materials build\make_dist.ps1 used to copy at build time; see
    #      make_dist.ps1's comments for the full background)
    Write-D2PProgress 90 "Injecting Python environment patches"
    Invoke-D2PPatchAndVerify -BlenderRoot $extractedRoot -CleanupOnFailureDir $tmpExtractDir

    # --- move atomically into the final location (so a mid-way failure never leaves a
    #     half-finished result) ---
    # Rename-Item can only rename within the same parent directory (crossing a parent
    # directory fails with "Cannot rename the specified target..." -- confirmed on real
    # hardware). $extractedRoot (...\assets\tools\.tmp_ensure_blender_XXXX\<Blender
    # name>) and $TargetDir (...\assets\tools\<Blender name>) have different parents, so
    # Move-Item is used instead (as long as it stays on the same volume, Move-Item's
    # underlying implementation is MoveFileEx, which is atomic just like a rename).
    Write-D2PProgress 95 "Moving to final location"
    if (Test-Path -LiteralPath $TargetDir) {
        $oldName = "$TargetDir.old_$([Guid]::NewGuid().ToString('N'))"
        Rename-Item -LiteralPath $TargetDir -NewName $oldName -Force
        Remove-Item -LiteralPath $oldName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Move-Item -LiteralPath $extractedRoot -Destination $TargetDir -Force
    Remove-Item -LiteralPath $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue

    if ($downloadedZip) {
        Remove-Item -LiteralPath $downloadedZip -Force -ErrorAction SilentlyContinue
    }

    Write-D2PProgress 100 "Blender setup complete"
    Write-Host "OK: Blender setup complete ($TargetDir)"
    exit 0
} catch {
    Show-D2PFailureGuidance $_.Exception.Message
    exit 1
}
