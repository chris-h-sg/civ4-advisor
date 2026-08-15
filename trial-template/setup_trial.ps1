<#
.SYNOPSIS
Build a self-contained trial folder for one game, ready to point Claude Code at.

.DESCRIPTION
Creates -Destination containing junctions to this repo's harness/, the specific
game's run folder under state/, the schema/ folder and the Civ IV install, plus
a CLAUDE.md and config.local.json so the tools resolve paths with no further
setup.

schema/ is mounted because AGENT_GUIDE.md sends the agent to
schema/state.schema.json for a field's exact meaning, and 40 of its 84 field
descriptions carry a caveat that cannot be inferred from the turn files.
Without it that instruction is a dead end.

The destination is deliberately not created inside this repo: Claude Code's
CLAUDE.md discovery walks up from cwd, so a trial folder nested under this
repo would also pick up its root CLAUDE.md (the mod/harness dev instructions)
alongside the advisor persona.

.PARAMETER GameDir
The subfolder name under state/, e.g. LEADER_DARIUS_1785912623104.

.PARAMETER Destination
Where to create the trial folder. Must not already exist.

.EXAMPLE
.\setup_trial.ps1 -GameDir LEADER_DARIUS_1785912623104 -Destination C:\Users\Chris\Desktop\my-trial
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$GameDir,

    [Parameter(Mandatory = $true)]
    [string]$Destination
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$harnessPath = Join-Path $repoRoot "harness"
$schemaPath = Join-Path $repoRoot "schema"
$stateRoot = Join-Path $repoRoot "state"
$gameStatePath = Join-Path $stateRoot $GameDir
$configPath = Join-Path $repoRoot "config.local.json"

if (-not (Test-Path $harnessPath)) {
    throw "Expected $harnessPath - is this script still inside trial-template/ in the repo?"
}
if (-not (Test-Path $schemaPath)) {
    throw "Expected $schemaPath - is this script still inside trial-template/ in the repo?"
}
if (-not (Test-Path $gameStatePath)) {
    $available = Get-ChildItem $stateRoot -Directory | Select-Object -ExpandProperty Name
    throw "No such game folder: $gameStatePath`nAvailable under state/: $($available -join ', ')"
}
if (-not (Test-Path $configPath)) {
    throw "$configPath not found - copy config.local.json.example at the repo root and set civ4_install_path first."
}

$installPath = (Get-Content $configPath -Raw | ConvertFrom-Json).civ4_install_path
if (-not $installPath) {
    throw "$configPath has no civ4_install_path"
}
if (-not (Test-Path $installPath)) {
    throw "civ4_install_path in $configPath does not exist: $installPath"
}

if (Test-Path $Destination) {
    throw "$Destination already exists - remove it first, or pass a different -Destination."
}

New-Item -ItemType Directory -Path $Destination | Out-Null
New-Item -ItemType Junction -Path (Join-Path $Destination "harness") -Target $harnessPath | Out-Null
New-Item -ItemType Junction -Path (Join-Path $Destination "schema") -Target $schemaPath | Out-Null
New-Item -ItemType Junction -Path (Join-Path $Destination "state") -Target $gameStatePath | Out-Null
New-Item -ItemType Junction -Path (Join-Path $Destination "civ4_install") -Target $installPath | Out-Null

Copy-Item (Join-Path $PSScriptRoot "CLAUDE.md") (Join-Path $Destination "CLAUDE.md")

$configJson = @{ civ4_install_path = "civ4_install" } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $Destination "config.local.json"), $configJson, [System.Text.UTF8Encoding]::new($false))

Write-Output "Trial folder ready: $Destination"
Write-Output "  harness      -> $harnessPath"
Write-Output "  schema       -> $schemaPath"
Write-Output "  state        -> $gameStatePath"
Write-Output "  civ4_install -> $installPath"
