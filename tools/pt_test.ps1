<#
.SYNOPSIS
    Reusable EEVEE Path Tracing test runner.

.DESCRIPTION
    Optionally builds Blender, then renders a set of EEVEE_PT_* debug cases in one
    background Blender process and writes PNGs, report.json and report.md.

    The case list lives in pt_auto_test.py. Add one-off cases with -ExtraCase
    "name=ENV=VAL;ENV2=VAL2". Use -Gui to launch the interactive viewport with a
    case's environment already applied.

.EXAMPLE
    .\pt_test.ps1 -Build

.EXAMPLE
    .\pt_test.ps1 -Cases normal,no_history,raw,diffuse_nrd_only,diffuse_raw

.EXAMPLE
    .\pt_test.ps1 -Percent 100 -Samples 256 -NoCycles -Out D:\pt_results\final

.EXAMPLE
    .\pt_test.ps1 -Gui -GuiCase no_history

.EXAMPLE
    .\pt_test.ps1 -ExtraCase "my_case=EEVEE_PT_DEBUG_VIEW=1;EEVEE_PT_NO_TAA=1" -Cases my_case
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [string]$Scene = "",
    [string[]]$Cases = @(),
    [string[]]$ExtraCase = @(),
    [string]$Out = "",
    [int]$Percent = 50,
    [int]$Samples = 64,
    [int]$CyclesSamples = 64,
    [ValidateSet("CPU", "GPU")]
    [string]$CyclesDevice = "CPU",
    [switch]$NoCycles,
    [switch]$SaveDiff,
    [switch]$ListCases,
    [switch]$Gui,
    [string]$GuiCase = "normal",
    [string]$Blender = $(if ($env:BLENDER_EXE) { $env:BLENDER_EXE } else { "blender.exe" }),
    [string]$CMake = "cmake.exe",
    [string]$BuildDir = $(if ($env:BLENDER_BUILD_DIR) { $env:BLENDER_BUILD_DIR } else { "" })
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Script = Join-Path $PSScriptRoot "pt_auto_test.py"

if (-not $Scene) {
    $Scene = Join-Path (Split-Path -Parent $PSScriptRoot) "scenes\pt_test_scene.blend"
}
if (-not (Test-Path -LiteralPath $Script)) {
    throw "Missing $Script"
}
if (-not (Test-Path -LiteralPath $Scene)) {
    throw "Missing scene: $Scene"
}
if (-not (Test-Path -LiteralPath $Blender)) {
    $resolved = Get-Command $Blender -ErrorAction SilentlyContinue
    if ($resolved) {
        $Blender = $resolved.Source
    }
    else {
        throw "Missing Blender executable: $Blender"
    }
}

if (-not $Out) {
    $Out = Join-Path $PSScriptRoot ("test_results\" + (Get-Date -Format "yyyyMMdd_HHmmss"))
}
$Out = [System.IO.Path]::GetFullPath($Out)
New-Item -ItemType Directory -Force -Path $Out | Out-Null

# The NVIDIA Vulkan ICD is required for the Vulkan backend on this machine. Reuse an
# existing value if the caller already set one.
if (-not $env:VK_ICD_FILENAMES) {
    $icdRoot = "C:\Windows\System32\DriverStore\FileRepository"
    $icd = Get-ChildItem -LiteralPath $icdRoot -Directory -Filter "nv*.inf_amd64_*" `
        -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "nv-vk64.json" } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if ($icd) {
        $env:VK_ICD_FILENAMES = $icd
        Write-Host "Vulkan ICD: $icd"
    }
    else {
        Write-Warning "NVIDIA Vulkan ICD not found; Blender may fail to initialize Vulkan."
    }
}

if ($Build) {
    if (-not $BuildDir) {
        throw "Build requested but BuildDir is empty. Set -BuildDir or BLENDER_BUILD_DIR."
    }
    $buildLog = Join-Path $Out "build.log"
    Write-Host "Building blender ..."
    & $CMake --build $BuildDir --target blender --config Release --parallel 1 *> $buildLog
    $buildCode = $LASTEXITCODE

    if ($buildCode -ne 0) {
        $buildText = if (Test-Path -LiteralPath $buildLog) {
            Get-Content -LiteralPath $buildLog -Raw
        }
        else {
            ""
        }
        # A running Blender keeps blender.exe open. Rename it instead of killing the
        # user's session, then retry the link once.
        if ($buildText -match "LNK1104" -and (Test-Path -LiteralPath $Blender)) {
            $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $renamed = Join-Path (Split-Path -Parent $Blender) "blender_running_$stamp.exe"
            Rename-Item -LiteralPath $Blender -NewName (Split-Path -Leaf $renamed)
            Write-Host "blender.exe was locked; renamed to $renamed"
            & $CMake --build $BuildDir --target blender --config Release --parallel 1 *> $buildLog
            $buildCode = $LASTEXITCODE
        }
    }

    if ($buildCode -ne 0) {
        Write-Host "Build failed. Log: $buildLog" -ForegroundColor Red
        if (Test-Path -LiteralPath $buildLog) {
            Get-Content -LiteralPath $buildLog -Tail 30
        }
        exit $buildCode
    }
    Write-Host "Build OK: $Blender"
}

if ($ListCases) {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Blender -b --factory-startup --python $Script -- --list-cases
    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldPreference
    exit $code
}

if ($Gui) {
    $guiArgs = @(
        "--gpu-backend", "vulkan", $Scene,
        "--python", $Script, "--",
        "--gui-case", $GuiCase,
        "--percent", $Percent,
        "--samples", $Samples
    )
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Write-Host "Launching viewport case '$GuiCase' ..."
    & $Blender @guiArgs
    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldPreference
    exit $code
}

$blenderArgs = @(
    "--gpu-backend", "vulkan", "-b", $Scene,
    "--python", $Script, "--",
    "--out", $Out,
    "--percent", $Percent,
    "--samples", $Samples,
    "--cycles-samples", $CyclesSamples,
    "--cycles-device", $CyclesDevice
)
$extraNames = @()
foreach ($spec in $ExtraCase) {
    $name = ($spec -split "=", 2)[0].Trim()
    if ($name) { $extraNames += $name }
    $blenderArgs += @("--case", $spec)
}
if ($Cases.Count -gt 0) {
    $selectedCases = @($Cases)
    foreach ($name in $extraNames) {
        if ($selectedCases -notcontains $name) { $selectedCases += $name }
    }
    $blenderArgs += @("--cases", ($selectedCases -join ","))
}
if ($NoCycles) {
    $blenderArgs += "--no-cycles-ref"
}
if ($SaveDiff) {
    $blenderArgs += "--save-diff"
}

$logPath = Join-Path $Out "blender.log"
$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$output = & $Blender @blenderArgs 2>&1
$code = $LASTEXITCODE
$ErrorActionPreference = $oldPreference
$output | Out-File -LiteralPath $logPath -Encoding utf8
foreach ($line in $output) {
    Write-Host $line
}

Write-Host ""
Write-Host "Results: $Out"
Write-Host "Report:  $(Join-Path $Out 'report.md')"
Write-Host "Log:     $logPath"
exit $code
