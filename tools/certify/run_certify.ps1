# run_certify.ps1 -- SuperEmbedder 1.0 certification package (te267 U2-6; REL-4 steps 2, 3 and 5).
#
# ASCII-only, and written for both Windows PowerShell 5.1 and PowerShell 7 (the T-2116 package's rule: a script
# with one non-ASCII character was mis-decoded by 5.1 and produced a false FAIL).
#
# NO BUILD STEP. Every binary under bin\ is prebuilt on the dev box (tools\certify\build_package.py). This script
# only runs them, and writes only under results\ beside it.
#
# USAGE
#   .\run_certify.ps1                   provisional runs of the members this host runs (below), with, for
#                                       msvc19.33-auto, the query session, the round trip and U2-4's readings,
#                                       and, for msvc19.33-avx512, C63 at max_concurrency 1 and 4
#   .\run_certify.ps1 -Gpu              the same, then GPU mode: the GPU binary's proof-corpus bake
#                                       (U2-3 item 15) and every gpu-legs.json leg for this host's tier
#   .\run_certify.ps1 -Host -Gpu        the work machine's first sitting: the above, plus host mode, which bakes
#                                       the forced-SSE2 and forced-AVX2 members here and compares their rows
#                                       with the dev-box receipts in receipts\
#   .\run_certify.ps1 -Final -Members msvc19.33-auto,msvc19.33-avx512,...
#                                       final mode: only the named members, under <cell id>\final\
#   -Python <python.exe>                the Python that runs the round trip and the readings; default: the
#                                       package's own python\python.exe (embeddable CPython 3.13 with numpy,
#                                       D-SLM7811), so both hosts run the same interpreter and the same numpy
#
# MEMBERS THIS HOST RUNS (default). The CPU probe reads the host's best tier. A host with AVX-512F/BW (the work
# machine) runs msvc19.33-avx512 and the four auto members; any other host (the dev box) runs msvc19.33-sse2,
# msvc19.33-avx2 and the four auto members. A forced member whose tier the host lacks is refused by name before
# anything runs.
#
# RESUMABLE. Each step (one member's bake, the query session, the round trip, the readings, C63, one GPU leg)
# writes its files into a staging directory, moves them into place, and then records results\state\<machine>\
# <step>.json with the SHA-256 of every file it wrote. Running the script again skips every step whose record
# exists and whose files still hash to it, and runs the rest. A step that failed, crashed or was interrupted has
# no record, so it runs again from its start. A step whose files were changed afterwards runs again, and so do
# the steps that read its output.
#
# REFUSALS, each printed before anything runs, exit 1:
#   SEMB-PACKAGE-BINARY-MISSING <name>     a member's semb, the GPU binary, c63, a CPU probe, the round-trip
#                                          binary, or Python with numpy, is absent
#   SEMB-PACKAGE-WSL-DISTRO-MISSING        the Ubuntu-24.04 WSL distro is absent (the WSL member needs it)
#   SEMB-PACKAGE-WSL-DISTRO-VERSION-MISMATCH <v>
#                                          that distro's VERSION_ID is not 24.04
#   SEMB-PACKAGE-CPU-TIER-UNSUPPORTED <m>  a forced member whose tier this host's CPU lacks
#   SEMB-PACKAGE-UNKNOWN-MEMBER <m>        -Members names a member the package does not carry
#   SEMB-PACKAGE-USAGE <text>              an impossible combination of modes
#
# EXIT CODE. 0 only if every step of this invocation ran (now or on an earlier invocation) and wrote its files.
# results\summary.json lists every step with its state.

param(
    [switch]$Final,
    [Alias('Host')][switch]$HostMode,
    [switch]$Gpu,
    [string[]]$Members = @(),
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
$Root = $PSScriptRoot
$Results = Join-Path $Root "results"
$LogsDir = Join-Path $Results "logs"
$Release = "1.0.0"
$WslDistro = "Ubuntu-24.04"
$AllMembers = @("msvc19.33-auto", "msvc19.33-sse2", "msvc19.33-avx2", "msvc19.33-avx512", "clangcl18.1.8-auto",
                "msvc19.44.35214-auto", "gcc13.3.0-wsl-auto")
$AutoMember = "msvc19.33-auto"
$WslMember = "gcc13.3.0-wsl-auto"
$C63Member = "msvc19.33-avx512"
$GpuBinary = "msvc19.33-auto-gpu"
$HostModeMembers = @("msvc19.33-sse2", "msvc19.33-avx2")
$TierOrder = @{ "scalar" = 0; "sse2" = 1; "avx2" = 2; "avx512" = 3 }
$Utf8 = New-Object System.Text.UTF8Encoding $false

# --------------------------------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------------------------------
function Write-Line([string]$text, [string]$color = "") {
    if ($color) { Write-Host $text -ForegroundColor $color } else { Write-Host $text }
}

function Get-Sha256Hex([byte[]]$bytes, [int]$offset = 0, [int]$count = -1) {
    if ($count -lt 0) { $count = $bytes.Length - $offset }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $h = $sha.ComputeHash($bytes, $offset, $count) } finally { $sha.Dispose() }
    return ([System.BitConverter]::ToString($h)).Replace("-", "").ToLowerInvariant()
}

function Get-FileSha256([string]$path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($path)
    try { $h = $sha.ComputeHash($stream) } finally { $stream.Dispose(); $sha.Dispose() }
    return ([System.BitConverter]::ToString($h)).Replace("-", "").ToLowerInvariant()
}

function Write-Bytes([string]$path, [byte[]]$bytes) {
    $dir = Split-Path -Parent $path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [System.IO.File]::WriteAllBytes($path, $bytes)
}

function Write-Text([string]$path, [string]$text) { Write-Bytes $path ($Utf8.GetBytes($text)) }

function Write-JsonFile([string]$path, $value) {
    $tmp = $path + ".tmp"
    Write-Text $tmp (($value | ConvertTo-Json -Depth 32) + "`n")
    Move-Item -LiteralPath $tmp -Destination $path -Force
}

function Read-JsonFile([string]$path) {
    return ([System.IO.File]::ReadAllText($path, $Utf8) | ConvertFrom-Json)
}

function Remove-Tree([string]$path) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

function New-Dir([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Force -Path $path | Out-Null }
    return $path
}

function Get-Prop($object, [string]$name) {
    if ($null -eq $object) { return $null }
    $p = $object.PSObject.Properties[$name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

# One argument quoted by the rules CommandLineToArgvW and .NET's own parser read back (backslashes are literal
# except before a quote; a quote is escaped with a backslash).
function ConvertTo-Argument([string]$arg) {
    if ($arg.Length -gt 0 -and $arg -notmatch '[\s"]') { return $arg }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $backslashes = 0
    foreach ($ch in $arg.ToCharArray()) {
        if ($ch -eq [char]'\') { $backslashes++; continue }
        if ($ch -eq [char]'"') { [void]$sb.Append([char]'\', 2 * $backslashes + 1); [void]$sb.Append([char]'"'); $backslashes = 0; continue }
        if ($backslashes -gt 0) { [void]$sb.Append([char]'\', $backslashes); $backslashes = 0 }
        [void]$sb.Append($ch)
    }
    if ($backslashes -gt 0) { [void]$sb.Append([char]'\', 2 * $backslashes) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

# Runs a program with its standard output and error streamed to files (never through the PowerShell pipeline,
# whose encoding would rewrite the bytes) and, when given, exact bytes on its standard input. Returns the exit
# code, or -1 when the program cannot be started.
function Invoke-Program([string]$file, [string[]]$arguments, [string]$stdoutPath, [string]$stderrPath,
                        [byte[]]$stdinBytes = $null) {
    New-Dir (Split-Path -Parent $stdoutPath) | Out-Null
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $file
    $psi.Arguments = (($arguments | ForEach-Object { ConvertTo-Argument ([string]$_) }) -join " ")
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = ($null -ne $stdinBytes)
    $out = [System.IO.File]::Create($stdoutPath)
    $err = [System.IO.File]::Create($stderrPath)
    try {
        try { $proc = [System.Diagnostics.Process]::Start($psi) } catch {
            $msg = $Utf8.GetBytes("cannot start ${file}: $($_.Exception.Message)`n")
            $err.Write($msg, 0, $msg.Length)
            return -1
        }
        $t1 = $proc.StandardOutput.BaseStream.CopyToAsync($out)
        $t2 = $proc.StandardError.BaseStream.CopyToAsync($err)
        if ($null -ne $stdinBytes) {
            try {
                $proc.StandardInput.BaseStream.Write($stdinBytes, 0, $stdinBytes.Length)
                $proc.StandardInput.BaseStream.Flush()
            } catch { }  # the program exited early; its exit code says why
            try { $proc.StandardInput.Close() } catch { }
        }
        $proc.WaitForExit()
        $t1.Wait(); $t2.Wait()
        return $proc.ExitCode
    } finally { $out.Dispose(); $err.Dispose() }
}

function Read-Tail([string]$path, [int]$chars = 600) {
    if (-not (Test-Path -LiteralPath $path)) { return "" }
    $t = [System.IO.File]::ReadAllText($path, $Utf8)
    if ($t.Length -gt $chars) { $t = $t.Substring($t.Length - $chars) }
    return $t.Trim()
}

# Decodes a program's output that may be UTF-16LE (wsl.exe's own listing) or UTF-8.
function ConvertFrom-ProgramBytes([byte[]]$bytes) {
    $zeros = 0
    for ($i = 1; $i -lt $bytes.Length; $i += 2) { if ($bytes[$i] -eq 0) { $zeros++ } }
    if ($bytes.Length -ge 2 -and $zeros * 2 -ge ($bytes.Length / 2)) {
        $text = [System.Text.Encoding]::Unicode.GetString($bytes)
    } else { $text = $Utf8.GetString($bytes) }
    return $text.Replace([string][char]0xFEFF, "").Replace([string][char]0, "")
}

$HasFromHex = $null -ne ([System.Convert].GetMethod("FromHexString", [type[]]@([string])))
function ConvertFrom-Hex([string]$hex) {
    if ($HasFromHex) { return ,([System.Convert]::FromHexString($hex)) }
    $n = $hex.Length / 2
    $bytes = New-Object byte[] $n
    for ($i = 0; $i -lt $n; $i++) { $bytes[$i] = [System.Convert]::ToByte($hex.Substring(2 * $i, 2), 16) }
    return ,$bytes
}

function Get-TierOf([string]$member) {
    if ($member -match '-(sse2|avx2|avx512)$') { return $Matches[1] }
    return "auto"
}

$script:Refusals = New-Object System.Collections.Generic.List[string]
function Add-Refusal([string]$text) { $script:Refusals.Add($text); Write-Line $text "Red" }

# --------------------------------------------------------------------------------------------------------------
# The package
# --------------------------------------------------------------------------------------------------------------
$packageJson = Join-Path $Root "package.json"
if (-not (Test-Path -LiteralPath $packageJson)) {
    Write-Line "FAIL: $packageJson is absent -- this folder is not a built certification package" "Red"
    exit 1
}
$Package = Read-JsonFile $packageJson
$ModelPath = Join-Path (Join-Path $Root "artifacts") $Package.model.file
$TokenizerPath = Join-Path (Join-Path $Root "artifacts") $Package.tokenizer.file
$CorpusPath = Join-Path $Root ($Package.corpus -replace '/', [System.IO.Path]::DirectorySeparatorChar)
$ArtifactKind = Get-Prop $Package "artifactKind"
if (-not $ArtifactKind) { $ArtifactKind = "real" }
$ToolsDir = Join-Path (Join-Path $Root "bin") "tools"
$Machine = [System.Environment]::MachineName -replace '[^A-Za-z0-9_.-]', '_'
$StateDir = Join-Path (Join-Path $Results "state") $Machine
$Stamp = (Get-Date).ToString("yyyyMMdd'T'HHmmss")

function Get-MemberDir([string]$member) { return (Join-Path (Join-Path $Root "bin") $member) }
function Get-Semb([string]$member) {
    $dir = Get-MemberDir $member
    foreach ($name in @("semb.exe", "semb")) {
        $p = Join-Path $dir $name
        if (Test-Path -LiteralPath $p -PathType Leaf) { return $p }
    }
    return $null
}

# --------------------------------------------------------------------------------------------------------------
# Usage and the host
# --------------------------------------------------------------------------------------------------------------
if ($Final -and ($Gpu -or $HostMode)) { Add-Refusal "SEMB-PACKAGE-USAGE -Final runs neither -Gpu nor -Host (REL-4 step 5)" }
if ($Final -and $Members.Count -eq 0) { Add-Refusal "SEMB-PACKAGE-USAGE -Final runs only the members named with -Members" }
$Members = @($Members | ForEach-Object { $_ -split ',' } | Where-Object { $_ } | ForEach-Object { $_.Trim() })
foreach ($m in $Members) { if ($AllMembers -notcontains $m) { Add-Refusal "SEMB-PACKAGE-UNKNOWN-MEMBER $m" } }

$winProbe = Join-Path $ToolsDir "host_cpuid.exe"
$linuxProbe = Join-Path $ToolsDir "host_cpuid"

function Read-Probe([string]$stdoutPath) {
    $text = [System.IO.File]::ReadAllText($stdoutPath, $Utf8)
    $brand = $null; $tier = $null; $features = ""
    foreach ($line in ($text -split "`n")) {
        $l = $line.TrimEnd([char]13)
        if ($l -match '^HOST_BRAND=(.*)$') { $brand = $Matches[1].Trim() }
        elseif ($l -match '^HOST_BEST_TIER=(\S+)$') { $tier = $Matches[1] }
        elseif ($l -match '^HOST_FEATURES=(.*)$') { $features = $Matches[1] }
    }
    if ($null -eq $brand -or -not $TierOrder.ContainsKey([string]$tier)) { return $null }
    return @{ Brand = $brand; Tier = $tier; Features = $features }
}

$HostProbe = $null
if (-not (Test-Path -LiteralPath $winProbe -PathType Leaf)) {
    Add-Refusal "SEMB-PACKAGE-BINARY-MISSING host_cpuid"
} else {
    $pOut = Join-Path $LogsDir "probe-$Machine.out" ; $pErr = Join-Path $LogsDir "probe-$Machine.err"
    $code = Invoke-Program $winProbe @() $pOut $pErr
    if ($code -eq 0) { $HostProbe = Read-Probe $pOut }
    if ($null -eq $HostProbe) { Add-Refusal "SEMB-PACKAGE-BINARY-MISSING host_cpuid (it ran, exit $code, and printed no tier)" }
}

# The members this invocation runs.
if ($Members.Count -eq 0 -and $null -ne $HostProbe) {
    if ($HostProbe.Tier -eq "avx512") {
        $Members = @("msvc19.33-auto", "msvc19.33-avx512", "clangcl18.1.8-auto", "msvc19.44.35214-auto", $WslMember)
    } else {
        $Members = @("msvc19.33-auto", "msvc19.33-sse2", "msvc19.33-avx2", "clangcl18.1.8-auto",
                     "msvc19.44.35214-auto", $WslMember)
    }
}
$HostLegs = @()
if ($HostMode) { $HostLegs = $HostModeMembers }
if ($null -ne $HostProbe) {
    foreach ($m in @($Members + $HostLegs)) {
        $t = Get-TierOf $m
        if ($t -ne "auto" -and $TierOrder[$t] -gt $TierOrder[$HostProbe.Tier]) {
            Add-Refusal "SEMB-PACKAGE-CPU-TIER-UNSUPPORTED $m (the host's best tier is $($HostProbe.Tier))"
        }
    }
}

# Every binary this package runs, checked before any run (TE-401: the GPU binary and every member's semb; TE-417:
# c63). Final mode runs only the named members and never the GPU binary or C63, so it needs only theirs.
if ($Final) { $needMembers = $Members } else { $needMembers = $AllMembers }
foreach ($m in $needMembers) { if ($null -eq (Get-Semb $m)) { Add-Refusal "SEMB-PACKAGE-BINARY-MISSING $m" } }
if (-not $Final) {
    if ($null -eq (Get-Semb $GpuBinary)) { Add-Refusal "SEMB-PACKAGE-BINARY-MISSING $GpuBinary" }
    if (-not (Test-Path -LiteralPath (Join-Path (Get-MemberDir $C63Member) "c63.exe") -PathType Leaf)) {
        Add-Refusal "SEMB-PACKAGE-BINARY-MISSING c63"
    }
}
$runsAuto = $Members -contains $AutoMember
$runsWsl = $Members -contains $WslMember
if ($runsAuto -and -not (Test-Path -LiteralPath (Join-Path $ToolsDir "sf_roundtrip.exe") -PathType Leaf)) {
    Add-Refusal "SEMB-PACKAGE-BINARY-MISSING sf_roundtrip"
}
if ($runsWsl -and -not (Test-Path -LiteralPath $linuxProbe -PathType Leaf)) {
    Add-Refusal "SEMB-PACKAGE-BINARY-MISSING host_cpuid (Linux)"
}
foreach ($f in @($ModelPath, $TokenizerPath, $CorpusPath)) {
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { Add-Refusal "SEMB-PACKAGE-BINARY-MISSING artifact $f" }
}

# Python with numpy, for the round trip and U2-4's readings (msvc19.33-auto only): the package's own python\
# (D-SLM7811), never whatever is on PATH, so both hosts run the same interpreter and numpy.
$PythonCmd = $null
if ($runsAuto) {
    $pyExe = $Python
    if (-not $pyExe) { $pyExe = Join-Path (Join-Path $Root "python") "python.exe" }
    if (-not (Test-Path -LiteralPath $pyExe -PathType Leaf)) {
        Add-Refusal "SEMB-PACKAGE-BINARY-MISSING python ($pyExe)"
    } else {
        $code = Invoke-Program $pyExe @("-c", "import sys, numpy; assert sys.version_info >= (3, 9)") `
            (Join-Path $LogsDir "python-check.out") (Join-Path $LogsDir "python-check.err")
        if ($code -eq 0) { $PythonCmd = @($pyExe) }
        else { Add-Refusal "SEMB-PACKAGE-BINARY-MISSING python ($pyExe ran, exit $code, and could not import numpy)" }
    }
}

# The WSL member runs as `wsl -d Ubuntu-24.04 -u root`, never through the default distro (D-SLM7285).
$WslExe = $null
$WslGuest = $null
function Invoke-Wsl([string[]]$linuxCommand, [string]$stdoutPath, [string]$stderrPath) {
    return (Invoke-Program $script:WslExe (@("-d", $WslDistro, "-u", "root", "--exec") + $linuxCommand) $stdoutPath $stderrPath)
}
if ($runsWsl) {
    $w = Get-Command "wsl.exe" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $present = $false
    if ($w) {
        $WslExe = $w.Path
        $lOut = Join-Path $LogsDir "wsl-list.out"
        $code = Invoke-Program $WslExe @("-l", "-q") $lOut (Join-Path $LogsDir "wsl-list.err")
        if ($code -eq 0) {
            $names = (ConvertFrom-ProgramBytes ([System.IO.File]::ReadAllBytes($lOut))) -split "`n" | ForEach-Object { $_.Trim() }
            $present = ($names -contains $WslDistro)
        }
    }
    if (-not $present) {
        Add-Refusal "SEMB-PACKAGE-WSL-DISTRO-MISSING (install it: wsl --install -d $WslDistro --no-launch, then wsl -d $WslDistro -u root once)"
    } else {
        $oOut = Join-Path $LogsDir "wsl-os-release.out"
        $code = Invoke-Wsl @("cat", "/etc/os-release") $oOut (Join-Path $LogsDir "wsl-os-release.err")
        $version = ""
        if ($code -eq 0) {
            foreach ($line in ([System.IO.File]::ReadAllText($oOut, $Utf8) -split "`n")) {
                if ($line -match '^VERSION_ID="?([^"]*)"?\s*$') { $version = $Matches[1] }
            }
        }
        if ($version -ne "24.04") {
            Add-Refusal "SEMB-PACKAGE-WSL-DISTRO-VERSION-MISMATCH $version (the WSL member runs on Ubuntu 24.04)"
        } else {
            $WslGuest = [ordered]@{ distro = $WslDistro; VERSION_ID = $version }
            foreach ($pkg in @("libc6", "libstdc++6")) {
                $vOut = Join-Path $LogsDir "wsl-$pkg.out"
                $code = Invoke-Wsl @("dpkg-query", "-W", "-f=`${Version}", $pkg) $vOut (Join-Path $LogsDir "wsl-$pkg.err")
                $v = ""
                if ($code -eq 0) { $v = [System.IO.File]::ReadAllText($vOut, $Utf8).Trim() }
                $WslGuest[$pkg] = $v
            }
        }
    }
}

if ($script:Refusals.Count -gt 0) {
    Write-Line ""
    Write-Line "CERTIFICATION PACKAGE: REFUSED before any run -- $($script:Refusals.Count) refusal(s) above" "Red"
    exit 1
}

$mode = "provisional"
if ($Final) { $mode = "final" }
Write-Line "=== SuperEmbedder $Release certification package ===" "Cyan"
Write-Line ("host: " + $HostProbe.Brand + "  best tier: " + $HostProbe.Tier + "  machine: " + $Machine)
Write-Line ("mode: $mode" + $(if ($HostMode) { " +host" } else { "" }) + $(if ($Gpu) { " +gpu" } else { "" }))
Write-Line ("members: " + ($Members -join ", "))

# --------------------------------------------------------------------------------------------------------------
# Step records (resumability)
# --------------------------------------------------------------------------------------------------------------
function Get-StatePath([string]$key) { return (Join-Path $StateDir ($key + ".json")) }

function Get-RelPath([string]$path) {
    $full = [System.IO.Path]::GetFullPath($path)
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    return $full.Substring($rootFull.Length).Replace('\', '/')
}

function Get-AbsPath([string]$rel) { return (Join-Path $Root ($rel.Replace('/', [System.IO.Path]::DirectorySeparatorChar))) }

# A step is done when its record exists, was written on this host, and every file it lists hashes as recorded.
function Get-DoneRecord([string]$key) {
    $path = Get-StatePath $key
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try { $rec = Read-JsonFile $path } catch { return $null }
    if ((Get-Prop $rec "status") -ne "done" -or (Get-Prop $rec "host") -ne $HostProbe.Brand) { return $null }
    $outputs = Get-Prop $rec "outputs"
    if ($null -eq $outputs) { return $null }
    foreach ($p in $outputs.PSObject.Properties) {
        $abs = Get-AbsPath $p.Name
        if (-not (Test-Path -LiteralPath $abs -PathType Leaf)) { return $null }
        if ((Get-FileSha256 $abs) -ne $p.Value) { return $null }
    }
    return $rec
}

function Save-DoneRecord([string]$key, [string[]]$files, $extra) {
    $outputs = [ordered]@{}
    foreach ($f in $files) { $outputs[(Get-RelPath $f)] = Get-FileSha256 $f }
    $rec = [ordered]@{ step = $key; status = "done"; host = $HostProbe.Brand; finished = (Get-Date).ToString("s"); outputs = $outputs }
    if ($null -ne $extra) { foreach ($k in $extra.Keys) { $rec[$k] = $extra[$k] } }
    New-Dir $StateDir | Out-Null
    Write-JsonFile (Get-StatePath $key) $rec
}

function Clear-DoneRecord([string]$key) {
    $p = Get-StatePath $key
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
}

$script:Summary = New-Object System.Collections.Generic.List[object]
$script:Failed = $false

function Save-Summary {
    $s = [ordered]@{
        schemaVersion = 1; release = $Release; mode = $mode; hostMode = [bool]$HostMode; gpuMode = [bool]$Gpu
        host = $HostProbe.Brand; hostBestTier = $HostProbe.Tier; machine = $Machine; members = $Members
        started = $Stamp; finished = (Get-Date).ToString("s"); allStepsDone = (-not $script:Failed)
        steps = $script:Summary.ToArray()
    }
    New-Dir $Results | Out-Null
    Write-JsonFile (Join-Path $Results "summary.json") $s
}

# Runs one step unless it is already done. $body returns a hashtable: Files (every file it wrote, which the record
# hashes) and optionally Extra (fields kept in the record). A step whose dependency is not done does not run.
function Invoke-Step([string]$key, [string]$title, [string[]]$dependsOn, [scriptblock]$body) {
    foreach ($d in $dependsOn) {
        if ($null -eq (Get-DoneRecord $d)) {
            Write-Line ("  [NOT RUN] {0}: {1} is not done" -f $title, $d) "Red"
            $script:Summary.Add([ordered]@{ step = $key; state = "not-run"; detail = "$d is not done" })
            $script:Failed = $true; Save-Summary; return $null
        }
    }
    $done = Get-DoneRecord $key
    if ($null -ne $done) {
        Write-Line ("  [DONE]    {0} (recorded {1})" -f $title, $done.finished) "Green"
        $script:Summary.Add([ordered]@{ step = $key; state = "done-earlier"; detail = [string]$done.finished })
        return $done
    }
    Clear-DoneRecord $key
    Write-Line ("  [RUN]     {0}" -f $title) "Cyan"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $result = & $body
        $extra = $null
        if ($result.ContainsKey("Extra")) { $extra = $result.Extra }
        Save-DoneRecord $key $result.Files $extra
        $sw.Stop()
        $detail = ""
        if ($result.ContainsKey("Detail")) { $detail = $result.Detail }
        Write-Line ("  [PASS]    {0} ({1}s) {2}" -f $title, [math]::Round($sw.Elapsed.TotalSeconds, 1), $detail) "Green"
        $script:Summary.Add([ordered]@{ step = $key; state = "done"; seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1); detail = $detail })
        Save-Summary
        return (Get-DoneRecord $key)
    } catch {
        $sw.Stop()
        $msg = $_.Exception.Message
        Write-Line ("  [FAIL]    {0}: {1}" -f $title, $msg) "Red"
        $script:Summary.Add([ordered]@{ step = $key; state = "failed"; seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1); detail = $msg })
        $script:Failed = $true
        Save-Summary
        return $null
    }
}

# --------------------------------------------------------------------------------------------------------------
# The bake and its run files (U2-3 items 6, 7, 12, 15; the file set Slice 7 fixed, D-SLM7206)
# --------------------------------------------------------------------------------------------------------------
$CorpusRows = @()
foreach ($line in ([System.IO.File]::ReadAllText($CorpusPath, $Utf8) -split "`n")) {
    if ($line.Trim().Length -gt 0) {
        $row = $line | ConvertFrom-Json
        # ConvertFrom-Json can turn a date-shaped string into a date; a query text must stay its exact bytes.
        if ($row.id -isnot [string] -or $row.text -isnot [string]) { throw "corpus row $($CorpusRows.Count) is not {id, text} strings" }
        $CorpusRows += , $row
    }
}
$CorpusIds = @($CorpusRows | ForEach-Object { [string]$_.id })

$script:WslRoot = $null
function ConvertTo-WslPath([string]$path) {
    if ($null -eq $script:WslRoot) {
        $o = Join-Path $LogsDir "wslpath.out"
        $code = Invoke-Wsl @("wslpath", "-a", $Root) $o (Join-Path $LogsDir "wslpath.err")
        if ($code -ne 0) { throw "wslpath failed for $Root (exit $code)" }
        $script:WslRoot = [System.IO.File]::ReadAllText($o, $Utf8).Trim().TrimEnd('/')
    }
    return ($script:WslRoot + "/" + (Get-RelPath $path))
}

function Invoke-MemberProbe([string]$member, [string]$logDir) {
    $pOut = Join-Path $logDir "probe.out"; $pErr = Join-Path $logDir "probe.err"
    if ($member -eq $WslMember) {
        $code = Invoke-Wsl @((ConvertTo-WslPath $linuxProbe)) $pOut $pErr
    } else {
        $code = Invoke-Program $winProbe @() $pOut $pErr
    }
    if ($code -ne 0) { throw "the CPU probe exited $code for $member" }
    $probe = Read-Probe $pOut
    if ($null -eq $probe) { throw "the CPU probe printed no tier for $member" }
    return $probe
}

# Bakes the corpus with one binary and returns the run's files, staged in $stage. $verbArgs are extra bake
# arguments (--device gpu for the GPU binary).
function Invoke-Bake([string]$member, [string]$binaryDir, [string]$corpus, [string]$work, [string[]]$verbArgs,
                     [string]$pass, [string]$runIdPrefix) {
    Remove-Tree $work
    New-Dir $work | Out-Null
    $logDir = New-Dir (Join-Path $work "logs")
    $probe = Invoke-MemberProbe $member $logDir
    $bankDir = New-Dir (Join-Path $work "bank")
    $stem = Join-Path $bankDir "corpus"
    $semb = $null
    foreach ($name in @("semb.exe", "semb")) {
        $p = Join-Path $binaryDir $name
        if (Test-Path -LiteralPath $p -PathType Leaf) { $semb = $p; break }
    }
    if ($member -eq $WslMember) {
        $cmd = @((ConvertTo-WslPath $semb), "bake", (ConvertTo-WslPath $corpus), "--out", (ConvertTo-WslPath $stem),
                 "--model", (ConvertTo-WslPath $ModelPath), "--tokenizer", (ConvertTo-WslPath $TokenizerPath)) + $verbArgs
        $code = Invoke-Wsl $cmd (Join-Path $logDir "bake.out") (Join-Path $logDir "bake.err")
    } else {
        $cmd = @("bake", $corpus, "--out", $stem, "--model", $ModelPath, "--tokenizer", $TokenizerPath) + $verbArgs
        $code = Invoke-Program $semb $cmd (Join-Path $logDir "bake.out") (Join-Path $logDir "bake.err")
    }
    if ($code -ne 0) { throw "semb bake exited $code for ${member}: $(Read-Tail (Join-Path $logDir 'bake.err'))" }
    $headerPath = $stem + ".wvbank.json"; $payloadPath = $stem + ".wvbank.bin"; $manifestPath = $stem + ".semb.json"
    foreach ($f in @($headerPath, $payloadPath, $manifestPath)) {
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { throw "semb bake exited 0 and wrote no $f" }
    }
    $header = Read-JsonFile $headerPath
    $payload = [System.IO.File]::ReadAllBytes($payloadPath)
    $manifestBytes = [System.IO.File]::ReadAllBytes($manifestPath)
    $manifest = $Utf8.GetString($manifestBytes) | ConvertFrom-Json
    $ids = @($header.ids | ForEach-Object { [string]$_ })
    $count = [int]$header.count; $dims = [int]$header.dims
    $rows = @([System.IO.File]::ReadAllText($corpus, $Utf8) -split "`n" | Where-Object { $_.Trim().Length -gt 0 }).Count
    if ($header.dtype -ne "float32" -or $count -ne $ids.Count -or $count -ne $rows) {
        throw "the bank's header is not $rows float32 rows with one id each"
    }
    $stride = 4 * $dims
    if ($payload.Length -ne $count * $stride) { throw "the payload is $($payload.Length) bytes, not $count x $stride" }
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt $count; $i++) {
        [void]$sb.Append($ids[$i]).Append("`t").Append((Get-Sha256Hex $payload ($i * $stride) $stride)).Append("`n")
    }
    $tsvBytes = $Utf8.GetBytes($sb.ToString())
    $tier = [string]$manifest.machine_tier
    $cellId = "$member@$tier"
    $memberJson = Read-JsonFile (Join-Path $binaryDir "member.json")
    $runId = "$runIdPrefix-$tier-$pass-" + (Get-Date).ToString("yyyyMMdd'T'HHmmss")
    $run = [ordered]@{
        cellId = $cellId; runId = $runId; date = (Get-Date).ToString("yyyy-MM-dd"); pass = $pass
        host = $probe.Brand; manifestSha256 = (Get-Sha256Hex $manifestBytes)
        buildDescriptor = $manifest.build_descriptor; machineTier = $manifest.machine_tier
        certificationEpoch = $manifest.certification_epoch; certifiedBuildsSha256 = $manifest.certified_builds_sha256
        certifiedCell = $manifest.certified_cell; dispatchedTier = $manifest.machine_tier; hostBestTier = $probe.Tier
        hostFeatures = $probe.Features
        enginePin = $memberJson.enginePin; productCommit = $memberJson.productCommit
        derivationInputsSha256 = $memberJson.derivationInputsSha256
        rowDigest = (Get-Sha256Hex $tsvBytes); tokenIdDigest = [string]$manifest.token_id_digest
    }
    if ($pass -eq "final") {
        # The five fingerprint components the bake's manifest carries (U2-3 item 6), as the final binary wrote them.
        $run["fingerprintComponents"] = [ordered]@{
            model_sha = $manifest.model_sha; tokenizer_sha = $manifest.tokenizer_sha
            template_sha256 = $manifest.template_sha256; witness_sha = $manifest.witness_sha
            certification_epoch = $manifest.certification_epoch
        }
        $run["encoderFingerprint"] = $manifest.encoder_fingerprint
    }
    if ($member -eq $WslMember) { $run["wslGuest"] = $script:WslGuest }
    $stage = New-Dir (Join-Path $work "run")
    Write-Bytes (Join-Path $stage "row-digests.tsv") $tsvBytes
    Write-Text (Join-Path $stage "token-id-digest.txt") ([string]$manifest.token_id_digest + "`n")
    Write-Bytes (Join-Path $stage "bake-manifest.semb.json") $manifestBytes
    Copy-Item -LiteralPath (Join-Path $binaryDir "compile-flags.json") -Destination (Join-Path $stage "compile-flags.json")
    Copy-Item -LiteralPath (Join-Path $binaryDir "engine-flags.json") -Destination (Join-Path $stage "engine-flags.json")
    return @{ Stage = $stage; Run = $run; Manifest = $manifest; CellId = $cellId; Stem = $stem; Dims = $dims
              BankFiles = @($headerPath, $payloadPath, $manifestPath); Probe = $probe }
}

# Moves a staged run into place (replacing whatever an interrupted attempt left there) and returns its files.
function Publish-Run($baked, [string]$target) {
    Write-JsonFile (Join-Path $baked.Stage "run.json") $baked.Run
    Remove-Tree $target
    New-Dir (Split-Path -Parent $target) | Out-Null
    Move-Item -LiteralPath $baked.Stage -Destination $target
    return @(Get-ChildItem -LiteralPath $target -File | ForEach-Object { $_.FullName })
}

function Get-CellRoot { return (Join-Path (Join-Path (Join-Path $Results "docs") "certification") $Release) }

function Get-RunDir([string]$cellId, [string]$pass) {
    $d = Join-Path (Get-CellRoot) $cellId
    if ($pass -eq "final") { $d = Join-Path $d "final" }
    return $d
}

# --------------------------------------------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------------------------------------------
function Step-Bake([string]$member, [string]$pass) {
    $work = Join-Path (Join-Path (Join-Path $Results "work") $member) $pass
    $baked = Invoke-Bake $member (Get-MemberDir $member) $CorpusPath $work @() $pass $member
    $files = Publish-Run $baked (Get-RunDir $baked.CellId $pass)
    return @{ Files = ($files + $baked.BankFiles); Extra = @{ cellId = $baked.CellId; stem = (Get-RelPath $baked.Stem) }
              Detail = "cell $($baked.CellId), dispatched $($baked.Run.dispatchedTier), host best $($baked.Run.hostBestTier)" }
}

# One `semb query --stdin` session over the 239 query texts in its default output mode (TE-278, F17); each
# VECTOR_HEX= line hex-decoded to dims x 4 bytes and hashed (TE-275 F14).
function Step-Query([string]$bakeKey, [string]$pass) {
    $bake = Get-DoneRecord $bakeKey
    $stem = Get-AbsPath $bake.stem
    $runDir = Get-RunDir $bake.cellId $pass
    $work = New-Dir (Join-Path (Join-Path (Join-Path $Results "work") $AutoMember) "$pass-query")
    $texts = New-Object System.Text.StringBuilder
    foreach ($r in $CorpusRows) {
        $t = [string]$r.text
        if ($t.Contains("`n") -or $t.Contains("`r")) { throw "query text $($r.id) holds a line terminator" }
        [void]$texts.Append($t).Append("`n")
    }
    $textBytes = $Utf8.GetBytes($texts.ToString())
    Write-Bytes (Join-Path $work "query-texts.txt") $textBytes
    $out = Join-Path $work "query.out"; $err = Join-Path $work "query.err"
    $code = Invoke-Program (Get-Semb $AutoMember) @("query", "--stdin", $stem, "--model", $ModelPath, "--tokenizer", $TokenizerPath) $out $err $textBytes
    if ($code -ne 0) { throw "semb query --stdin exited ${code}: $(Read-Tail $err)" }
    $lines = @([System.IO.File]::ReadAllText($out, $Utf8) -split "`n" | Where-Object { $_.Length -gt 0 })
    if ($lines.Count -ne $CorpusRows.Count) { throw "$($lines.Count) output lines for $($CorpusRows.Count) query texts" }
    $header = Read-JsonFile ($stem + ".wvbank.json")
    $want = 8 * [int]$header.dims
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $l = $lines[$i].TrimEnd([char]13)
        if (-not $l.StartsWith("VECTOR_HEX=")) { throw "query $i printed no VECTOR_HEX= line" }
        $hex = $l.Substring(11)
        if ($hex.Length -ne $want) { throw "query $i's vector is $($hex.Length / 2) bytes, not $($want / 2)" }
        [void]$sb.Append($CorpusIds[$i]).Append("`t").Append((Get-Sha256Hex (ConvertFrom-Hex $hex))).Append("`n")
    }
    $target = Join-Path $runDir "query-digests.tsv"
    Write-Text ($target + ".tmp") $sb.ToString()
    Move-Item -LiteralPath ($target + ".tmp") -Destination $target -Force
    return @{ Files = @($target); Detail = "$($lines.Count) query digests" }
}

function Invoke-PythonTool([string[]]$toolArgs, [string]$stdoutPath, [string]$stderrPath) {
    $pyArgs = @()
    if ($PythonCmd.Count -gt 1) { $pyArgs = @($PythonCmd[1..($PythonCmd.Count - 1)]) }
    return (Invoke-Program $PythonCmd[0] ($pyArgs + $toolArgs) $stdoutPath $stderrPath)
}

# The round trip (U2-2's RT-1...RT-4) in its prebuilt mode, over the member's own bank.
function Step-RoundTrip([string]$bakeKey, [string]$pass) {
    $bake = Get-DoneRecord $bakeKey
    $work = Join-Path (Join-Path (Join-Path $Results "work") $AutoMember) "$pass-roundtrip"
    Remove-Tree $work
    New-Dir $work | Out-Null
    $out = Join-Path $work "roundtrip.out"; $err = Join-Path $work "roundtrip.err"
    $harness = Join-Path $Root "harness"
    $sep = [System.IO.Path]::DirectorySeparatorChar
    $code = Invoke-PythonTool @((Join-Path $harness ("tests" + $sep + "superfaiss_roundtrip" + $sep + "roundtrip.py")),
        "--build-dir", $work, "--artifact", $ArtifactKind, "--model", $ModelPath, "--tokenizer", $TokenizerPath,
        "--semb", (Get-Semb $AutoMember), "--program", (Join-Path $ToolsDir "sf_roundtrip.exe"),
        "--wvbank", (Join-Path $harness "wvbank.py"), "--bank", (Get-AbsPath $bake.stem), "--out", (Join-Path $work "out")) $out $err
    if ($code -ne 0) { throw "the round trip exited ${code}: $(Read-Tail $out) $(Read-Tail $err)" }
    $rt4 = Join-Path (Join-Path $work "out") "rt4-digests.tsv"
    if (-not (Test-Path -LiteralPath $rt4)) { throw "the round trip wrote no rt4-digests.tsv" }
    $target = Join-Path (Get-RunDir $bake.cellId $pass) "rt4-digests.txt"
    Copy-Item -LiteralPath $rt4 -Destination ($target + ".tmp") -Force
    Move-Item -LiteralPath ($target + ".tmp") -Destination $target -Force
    $log = Join-Path (Join-Path (Join-Path $Results "roundtrip") $bake.cellId) "$pass.txt"
    New-Dir (Split-Path -Parent $log) | Out-Null
    Copy-Item -LiteralPath $out -Destination $log -Force
    return @{ Files = @($target, $log); Detail = "RT-1...RT-4 exit 0" }
}

# U2-4's readings (C20), published values with their cell, never a guard (D-SLM7251).
function Step-Readings([string]$bakeKey) {
    $bake = Get-DoneRecord $bakeKey
    $outDir = Join-Path (Join-Path $Results "readings") $bake.cellId
    Remove-Tree $outDir
    New-Dir $outDir | Out-Null
    $harness = Join-Path $Root "harness"
    $sep = [System.IO.Path]::DirectorySeparatorChar
    $code = Invoke-PythonTool @((Join-Path $harness ("tools" + $sep + "readiness" + $sep + "readiness.py")),
        "--semb", (Get-Semb $AutoMember), "--model", $ModelPath, "--tokenizer", $TokenizerPath, "--cell", $bake.cellId,
        "--out", $outDir, "--bank", (Get-AbsPath $bake.stem),
        "--corpus", (Join-Path $harness ("tests" + $sep + "fixtures" + $sep + "c12b" + $sep + "corpus-239.jsonl"))) `
        (Join-Path $outDir "readiness.out") (Join-Path $outDir "readiness.err")
    if ($code -ne 0) { throw "the readiness tool exited ${code}: $(Read-Tail (Join-Path $outDir 'readiness.out'))" }
    return @{ Files = @((Join-Path $outDir "readiness.json"), (Join-Path $outDir "readiness.out")); Detail = "readiness.json" }
}

# C63 on the forced AVX-512 member, at max_concurrency 1 and 4 (the binary runs both), after the member's bake
# (TE-417, TE-415 W-3). Red blocks the tag.
function Step-C63([string]$bakeKey) {
    $bake = Get-DoneRecord $bakeKey
    $outDir = Join-Path (Join-Path $Results "c63") $bake.cellId
    Remove-Tree $outDir
    $scratch = New-Dir (Join-Path $outDir "scratch")
    $out = Join-Path $outDir "c63.out"; $err = Join-Path $outDir "c63.err"
    $code = Invoke-Program (Join-Path (Get-MemberDir $C63Member) "c63.exe") @("--model", $ModelPath, "--tokenizer", $TokenizerPath,
        "--mid", (Join-Path (Join-Path $Root "c63") "mid.txt"), "--short", (Join-Path (Join-Path $Root "c63") "short.txt"),
        "--scratch", $scratch) $out $err
    $text = [System.IO.File]::ReadAllText($out, $Utf8)
    Remove-Tree $scratch
    if ($code -ne 0 -or $text -notmatch '(?m)^TOTAL fail=0\s*$' -or $text -match '\[(PRECONDITION|MISSING PREREQUISITE|FAIL)\]') {
        throw "C63 exited $code; see $out"
    }
    foreach ($mc in @("1", "4")) {
        if ($text -notmatch "mc $mc") { throw "C63 printed no leg at max_concurrency $mc" }
    }
    return @{ Files = @($out); Detail = "C63 green at max_concurrency 1 and 4" }
}

# Host mode (REL-4 step 3): a forced member on this host is a reading of its cell on a second microarchitecture,
# never a new cell, so it is written under results\host-mode\ and compared with the dev-box receipt.
function Step-HostMode([string]$member) {
    $work = Join-Path (Join-Path (Join-Path $Results "work") $member) "host-mode"
    $baked = Invoke-Bake $member (Get-MemberDir $member) $CorpusPath $work @() "host" "$member-hostmode"
    $receipt = Join-Path (Join-Path $Root "receipts") $baked.CellId
    $target = Join-Path (Join-Path $Results "host-mode") $baked.CellId
    $files = Publish-Run $baked $target
    foreach ($name in @("row-digests.tsv", "token-id-digest.txt")) {
        $r = Join-Path $receipt $name
        if (-not (Test-Path -LiteralPath $r)) { throw "no dev-box receipt $r to compare with" }
        if ((Get-FileSha256 $r) -ne (Get-FileSha256 (Join-Path $target $name))) {
            throw "HOST-MODE DIFFERENCE: $($baked.CellId)'s $name here differs from its dev-box receipt (a product finding; it blocks the tag)"
        }
    }
    return @{ Files = $files; Extra = @{ cellId = $baked.CellId }; Detail = "$($baked.CellId) rows and tokens equal the dev-box receipt" }
}

# GPU mode (TE-401, D-SLM7757): the GPU binary's proof-corpus bake, filed under gpu\<runId>\ with the manifest's
# device and four gpu_* labels copied into run.json (U2-3 item 15). Its process resolves on msvc19.33-auto's cell.
$GpuLabels = @("gpu_vendor_id", "gpu_device_id", "gpu_adapter_name", "gpu_driver_version")
function Step-GpuBake([string]$name, [string]$corpus, [string]$binary, [string[]]$extraArgs, [bool]$requireGpu) {
    $work = Join-Path (Join-Path (Join-Path $Results "work") "gpu") $name
    # The GPU binary's process resolves on msvc19.33-auto's cell (U2-3 item 1); a CPU leg names its member.
    $cellMember = $binary
    if ($binary -eq $GpuBinary) { $cellMember = $AutoMember }
    $baked = Invoke-Bake $cellMember (Get-MemberDir $binary) $corpus $work $extraArgs "provisional" "gpu-$name"
    $device = Get-Prop $baked.Manifest "device"
    if ($requireGpu -and $device -ne "gpu") { throw "the GPU binary's manifest records device '$device', not gpu" }
    $baked.Run["device"] = $device
    foreach ($l in $GpuLabels) { $baked.Run[$l] = Get-Prop $baked.Manifest $l }
    $baked.Run["gpuLeg"] = $name
    $target = Join-Path (Join-Path (Get-CellRoot) "gpu") $baked.Run.runId
    $files = Publish-Run $baked $target
    return @{ Files = $files; Extra = @{ runId = $baked.Run.runId }; Detail = "gpu\$($baked.Run.runId), device $device" }
}

# --------------------------------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------------------------------
$pass = $mode
foreach ($m in $Members) {
    Write-Line ""
    Write-Line "=== $m ($pass) ===" "Yellow"
    $bakeKey = "$pass.bake.$m"
    Invoke-Step $bakeKey "$m bake" @() { Step-Bake $m $pass } | Out-Null
    if ($m -eq $AutoMember) {
        Invoke-Step "$pass.query.$m" "$m query session" @($bakeKey) { Step-Query $bakeKey $pass } | Out-Null
        Invoke-Step "$pass.roundtrip.$m" "$m round trip" @($bakeKey, "$pass.query.$m") { Step-RoundTrip $bakeKey $pass } | Out-Null
        if (-not $Final) { Invoke-Step "$pass.readings.$m" "$m readings (U2-4)" @($bakeKey) { Step-Readings $bakeKey } | Out-Null }
    }
    if ($m -eq $C63Member -and -not $Final) {
        Invoke-Step "$pass.c63.$m" "$m C63 at max_concurrency 1 and 4" @($bakeKey) { Step-C63 $bakeKey } | Out-Null
    }
}

foreach ($m in $HostLegs) {
    Write-Line ""
    Write-Line "=== $m (host mode) ===" "Yellow"
    Invoke-Step "host.bake.$m" "$m host-mode bake" @() { Step-HostMode $m } | Out-Null
}

if ($Gpu) {
    Write-Line ""
    Write-Line "=== GPU mode ===" "Yellow"
    Invoke-Step "gpu.proof-corpus" "GPU binary proof-corpus bake (C10(a) GPU half)" @() {
        Step-GpuBake "proof-corpus" $CorpusPath $GpuBinary @("--device", "gpu") $true } | Out-Null
    # U3's hook: gpu-legs.json lists the host's other GPU and CPU legs (C10(c), C10(g), C11 on the work machine,
    # te266 sec 4.5), each a bake of its own corpus filed under its own run id.
    $legsPath = Join-Path $Root "gpu-legs.json"
    $legs = @()
    if (Test-Path -LiteralPath $legsPath) { $legs = @((Read-JsonFile $legsPath).legs) }
    foreach ($leg in $legs) {
        if ($null -eq $leg) { continue }
        $hostTier = [string](Get-Prop $leg "hostTier")
        if ($hostTier -and $hostTier -ne "any" -and $hostTier -ne $HostProbe.Tier) { continue }
        $legName = [string]$leg.name
        $legCorpus = Get-AbsPath ([string]$leg.corpus)
        $legBinary = [string]$leg.binary
        $legArgs = @()
        if ($null -ne (Get-Prop $leg "args")) { $legArgs = @($leg.args | ForEach-Object { [string]$_ }) }
        $needGpu = ((Get-Prop $leg "device") -eq "gpu")
        Invoke-Step "gpu.leg.$legName" "GPU-mode leg $legName" @() { Step-GpuBake $legName $legCorpus $legBinary $legArgs $needGpu } | Out-Null
    }
}

Save-Summary
Write-Line ""
if ($script:Failed) {
    Write-Line "CERTIFICATION PACKAGE: INCOMPLETE -- a step failed or did not run; run the script again to resume. See results\summary.json" "Red"
    exit 1
}
Write-Line "CERTIFICATION PACKAGE: every step ran and wrote its files. Return the results folder." "Green"
exit 0
