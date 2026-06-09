<#
.SYNOPSIS
  Run a CBECC-Res Title 24 compliance analysis HEADLESS (no GUI) on a .ribd25
  file and produce the CF1R-PRF report (PDF + XML) plus pass/fail + margin.

.DESCRIPTION
  Wraps CBECC-CLI25.exe -Compliance. This is the verified headless invocation
  cracked in Phase 0.5 (see PHASE0_FINDINGS.md). Primary functions exposed by
  the CLI: -CompileDataModel, -CompileRuleset, -Compliance, -BatchRuns,
  -SFamBatchRuns.

  CRITICAL GOTCHA: the CLI builds file paths by NAIVE STRING CONCATENATION.
  -WeatherPath and -ProcessingPath MUST end with a path separator or the engine
  looks for e.g. "EPW25CA_Title24_...epw" / "_clitestclitest - PreProp.cse".
  We append a forward slash ("/") which both Windows and Qt/CSE accept and which
  (unlike a trailing backslash) does not get mangled by PowerShell's native-arg
  quoting.

  The "SignXML(): PEM_read_bio_RSAPrivateKey() failure" line in the log is
  BENIGN here: it only means the PDF was not digitally signed by a registry
  provider key. The CF1R PDF/XML are still produced. Final permit-bound
  registration happens through a data registry anyway.

.PARAMETER ModelInput
  Path to the .ribd25 project file to analyze.

.PARAMETER OutDir
  Working/processing + output directory. Defaults to a "<model>_run" folder
  next to the model. Created if missing.

.PARAMETER DataDir
  CBECC 2025 Data folder (holds Rulesets\ and EPW25\). Auto-detected under the
  user's Documents (incl. OneDrive redirection) if not supplied.

.EXAMPLE
  .\run_compliance.ps1 -ModelInput "C:\path\Doe.ribd25"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ModelInput,

    [string]$OutDir,

    [string]$DataDir,

    [string]$Exe = "C:\Program Files\CBECC 2025\CBECC-CLI25.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Exe))        { throw "CBECC CLI not found: $Exe" }
if (-not (Test-Path $ModelInput)) { throw "Model input not found: $ModelInput" }
$ModelInput = (Resolve-Path $ModelInput).Path

# --- Locate the CBECC 2025 Data folder (ruleset + weather live here) ---
if (-not $DataDir) {
    $candidates = @(
        (Join-Path $env:USERPROFILE "OneDrive\Documents\CBECC 2025 Data"),
        (Join-Path $env:USERPROFILE "Documents\CBECC 2025 Data")
    )
    $DataDir = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $DataDir) { throw "Could not auto-detect 'CBECC 2025 Data'. Pass -DataDir." }
}

$bemBase = Join-Path $DataDir "Rulesets\CA Res 2025\CAR25 BEMBase.bin"  # SFam data model
$ruleset = Join-Path $DataDir "Rulesets\CA Res 2025.bin"               # SFam ruleset
$weather = Join-Path $DataDir "EPW25"
foreach ($p in @($bemBase, $ruleset, $weather)) {
    if (-not (Test-Path $p)) { throw "Required CBECC data file/folder missing: $p" }
}

# --- Output / processing directory ---
if (-not $OutDir) {
    $OutDir = Join-Path (Split-Path $ModelInput -Parent) `
                        ([IO.Path]::GetFileNameWithoutExtension($ModelInput) + "_run")
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$logFile = Join-Path $OutDir "run.log"

# Trailing "/" is REQUIRED on the two *Path args (see header note).
$argList = @(
    "-Compliance",
    "-ModelInput",     $ModelInput,
    "-sharedPath",     $DataDir,
    "-BEMBaseBin",     $bemBase,
    "-RulesetBin",     $ruleset,
    "-WeatherPath",    ($weather + "/"),
    "-ProcessingPath", ($OutDir + "/"),
    "-LogFile",        $logFile
)

Write-Host "Running CBECC-Res compliance (headless)..." -ForegroundColor Cyan
Write-Host "  Model : $ModelInput"
Write-Host "  Out   : $OutDir"
& $Exe @argList | Out-Null
$code = $LASTEXITCODE

# Surface the analysis verdict from the log.
$verdict = Get-Content $logFile -ErrorAction SilentlyContinue |
           Select-String -Pattern "Analysis result:|Analysis errant|ERROR:" |
           Select-Object -Last 3
Write-Host ""
if ($code -eq 0) {
    Write-Host "SUCCESS (exit 0)" -ForegroundColor Green
} else {
    Write-Host "FAILED (exit $code)" -ForegroundColor Red
}
$verdict | ForEach-Object { Write-Host "  $_" }

$cf1r = Get-ChildItem $OutDir -Filter "*CF1RPRF*.pdf" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cf1r) { Write-Host "  CF1R PDF: $($cf1r.FullName)" -ForegroundColor Green }

exit $code
