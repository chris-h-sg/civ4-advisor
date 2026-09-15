<#
.SYNOPSIS
Remove civ4-advisor from your Civ IV install.

.DESCRIPTION
Undoes what setup.ps1 did:

  - unlinks the mod from your MODS folder
  - removes the Desktop shortcut
  - optionally restores CivilizationIV.ini from the backup setup.ps1 made

Your saved games and your Civ IV install are never touched, and neither is this
repo. Removing the link does NOT delete the mod files - a junction is a
signpost, so taking it away leaves everything it pointed at exactly where it is.

Your recorded games under state\ are also left alone, since they are the history
the advisor reasons over. Use -IncludeState to delete those too.

.PARAMETER UserDataPath
Your Civ IV settings folder - the one containing CivilizationIV.ini. Only needed
if detection fails.

.PARAMETER IncludeState
Also delete state\ (every game the mod has recorded) and the generated
config.local.json and LocalConfig.py. Off by default.

.PARAMETER RestoreIni
Restore CivilizationIV.ini from the most recent backup setup.ps1 made. Off by
default: the two settings it changed are useful on their own and harmless to
leave, and restoring would also discard any other settings changed since.

.PARAMETER Force
Do not ask for confirmation.

.EXAMPLE
.\uninstall.ps1

.EXAMPLE
.\uninstall.ps1 -IncludeState -RestoreIni
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$UserDataPath,
    [switch]$IncludeState,
    [switch]$RestoreIni,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$MOD_NAME = "civ4-advisor"

function Write-Head($Text) { Write-Host "`n$Text" -ForegroundColor Cyan }
function Write-Ok($Text)   { Write-Host "  [ok]   $Text" -ForegroundColor Green }
function Write-Skip($Text) { Write-Host "  [--]   $Text" -ForegroundColor DarkGray }
function Write-Warn2($Text){ Write-Host "  [warn] $Text" -ForegroundColor Yellow }
function Write-Info($Text) { Write-Host "  $Text" -ForegroundColor DarkGray }

## Resolve a relative path against PowerShell's location, not .NET's process
## working directory - the two drift apart. Same as setup.ps1.
function Get-Canonical($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    try {
        if (-not [System.IO.Path]::IsPathRooted($Path)) {
            $Path = Join-Path (Get-Location).ProviderPath $Path
        }
        [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    } catch { $Path.TrimEnd('\') }
}

function Test-IsCivUserDataFolder($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try { Test-Path -LiteralPath (Join-Path $Path "CivilizationIV.ini") } catch { $false }
}

## Documents is frequently redirected into OneDrive; GetFolderPath follows that,
## $env:USERPROFILE\Documents does not. Same probe order as setup.ps1.
function Find-CivUserDataCandidates {
    $bases = @()
    $bases += [Environment]::GetFolderPath('MyDocuments')
    try {
        $shell = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders' -ErrorAction Stop
        if ($shell.Personal) { $bases += [Environment]::ExpandEnvironmentVariables($shell.Personal) }
    } catch { }
    if ($env:OneDrive)           { $bases += (Join-Path $env:OneDrive 'Documents') }
    if ($env:OneDriveCommercial) { $bases += (Join-Path $env:OneDriveCommercial 'Documents') }
    $bases += (Join-Path $env:USERPROFILE 'Documents')
    $bases += (Join-Path $env:USERPROFILE 'OneDrive\Documents')

    $bases | Where-Object { $_ } |
        ForEach-Object { Join-Path $_ 'My Games\Beyond the Sword' } |
        ForEach-Object { Get-Canonical $_ } | Sort-Object -Unique |
        Where-Object { Test-IsCivUserDataFolder $_ }
}

try {
    $repoRoot = Get-Canonical $PSScriptRoot
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'config.local.json.example'))) {
        throw @"
This script must be run from inside the civ4-advisor folder.
Expected to find config.local.json.example next to uninstall.ps1, in:
  $repoRoot
"@
    }

    if ($UserDataPath) {
        $userData = Get-Canonical $UserDataPath.Trim().Trim('"')
        if (-not (Test-IsCivUserDataFolder $userData)) {
            throw "-UserDataPath was given as '$UserDataPath' but there is no CivilizationIV.ini there."
        }
    } else {
        $found = @(Find-CivUserDataCandidates)
        if ($found.Count -eq 0) {
            throw @"
Could not find your Civ IV settings folder (the one containing CivilizationIV.ini).
Pass it directly:
  uninstall.bat -UserDataPath "C:\...\Documents\My Games\Beyond the Sword"
"@
        }
        $userData = $found[0]
    }

    Write-Head "civ4-advisor uninstall"
    Write-Info "settings: $userData"
    Write-Info "repo:     $repoRoot"

    Write-Host ""
    Write-Host "  This will remove:" -ForegroundColor Gray
    Write-Host "    - the mod link in MODS\$MOD_NAME (the mod files themselves stay here)" -ForegroundColor Gray
    Write-Host "    - the Desktop shortcut" -ForegroundColor Gray
    if ($RestoreIni)   { Write-Host "    - your CivilizationIV.ini changes (restored from backup)" -ForegroundColor Gray }
    if ($IncludeState) { Write-Host "    - state\ and the generated config files - EVERY RECORDED GAME" -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "  Your saves, your Civ IV install and this repo are not touched." -ForegroundColor Gray

    if (-not $Force) {
        $answer = Read-Host "`n  Continue? [y/N]"
        if ($answer -notmatch '^[Yy]') {
            Write-Host "  Nothing was changed." -ForegroundColor Gray
            exit 0
        }
    }

    Write-Head "Removing"

    ## --- the mod link ---
    $modSource = Get-Canonical (Join-Path $repoRoot 'mod')
    $linkPath = Join-Path (Join-Path $userData 'MODS') $MOD_NAME
    if (-not (Test-Path -LiteralPath $linkPath)) {
        Write-Skip "mod link already gone"
    } else {
        $item = Get-Item -LiteralPath $linkPath -Force
        if ($item.LinkType -in @('Junction', 'SymbolicLink')) {
            $target = Get-Canonical @($item.Target)[0]
            if ($target -ine $modSource) {
                Write-Warn2 "MODS\$MOD_NAME points at $target, not this repo."
                Write-Info "  Left alone - it belongs to a different copy of civ4-advisor."
            } elseif ($PSCmdlet.ShouldProcess($linkPath, 'Remove junction')) {
                ## Directory.Delete removes the reparse point itself and never
                ## follows it, so the mod files cannot be touched from here.
                ## Remove-Item -Recurse on a junction has historically been the
                ## dangerous call; this one cannot recurse into the target.
                ##
                ## It does refuse a read-only directory, though, and OneDrive
                ## sets ReadOnly on reparse points inside a synced folder some
                ## time AFTER they are created - a fresh junction does not carry
                ## it. So uninstalling straight after installing works and
                ## uninstalling a week later fails with "Access to the path is
                ## denied", which reads as a permissions problem and is not one.
                ## Clear just that one bit, preserving OneDrive's own flags.
                try {
                    if ($item.Attributes -band [System.IO.FileAttributes]::ReadOnly) {
                        $item.Attributes = $item.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
                    }
                } catch { }

                try {
                    [System.IO.Directory]::Delete($linkPath)
                } catch {
                    throw @"
Could not remove the mod link:
  $linkPath
  $($_.Exception.Message)

Your mod files are fine - this only failed to remove the link to them.
Things to try:
  - Close Civ IV if it is running, and close any Explorer window showing that folder.
  - If your Documents folder is in OneDrive, pause syncing and try again.
  - Remove it by hand:  rmdir "$linkPath"
    (that deletes only the link, never the files it points at)
"@
                }
                Write-Ok "mod unlinked (files still in $modSource)"
            }
        } else {
            Write-Warn2 "MODS\$MOD_NAME is a real folder, not a link - left alone."
            Write-Info "  $linkPath"
        }
    }

    ## --- the shortcut ---
    ## Checked by its arguments, not just its name: a shortcut with the expected
    ## filename might be one the player made themselves, pointing somewhere else.
    ## Deleting something off someone's Desktop on a name match alone is not a
    ## trade worth making.
    $shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) "Civ IV - $MOD_NAME.lnk"
    if (-not (Test-Path -LiteralPath $shortcut)) {
        Write-Skip "no Desktop shortcut"
    } else {
        $arguments = ''
        try {
            $shell = New-Object -ComObject WScript.Shell
            $arguments = $shell.CreateShortcut($shortcut).Arguments
        } catch { }

        if ($arguments -notmatch [regex]::Escape("mod=\Mods\$MOD_NAME")) {
            Write-Warn2 "a Desktop shortcut named 'Civ IV - $MOD_NAME' does not launch this mod - left alone."
            Write-Info "  $shortcut"
        } elseif ($PSCmdlet.ShouldProcess($shortcut, 'Remove')) {
            Remove-Item -LiteralPath $shortcut -Force -Confirm:$false
            Write-Ok "Desktop shortcut removed"
        }
    }

    ## --- the ini ---
    $iniPath = Join-Path $userData 'CivilizationIV.ini'
    if (-not $RestoreIni) {
        Write-Skip "CivilizationIV.ini left as it is (pass -RestoreIni to roll it back)"
    } else {
        $backup = Get-ChildItem -LiteralPath $userData -Filter 'CivilizationIV.ini.civ4-advisor-backup-*' -ErrorAction SilentlyContinue |
                  Sort-Object Name -Descending | Select-Object -First 1
        if (-not $backup) {
            Write-Warn2 "no backup found - CivilizationIV.ini left as it is"
            Write-Info "  To undo by hand, set LoggingEnabled = 0 and HidePythonExceptions = 1."
        } elseif ($PSCmdlet.ShouldProcess($iniPath, "Restore from $($backup.Name)")) {
            Copy-Item -LiteralPath $backup.FullName -Destination $iniPath -Force
            Write-Ok "CivilizationIV.ini restored from $($backup.Name)"
        }
    }

    ## --- generated files and recorded games ---
    if (-not $IncludeState) {
        $stateRoot = Join-Path $repoRoot 'state'
        if (Test-Path -LiteralPath $stateRoot) {
            $games = @(Get-ChildItem -LiteralPath $stateRoot -Directory -ErrorAction SilentlyContinue)
            Write-Skip "kept state\ ($($games.Count) recorded game(s)) and your config files"
        }
    } else {
        foreach ($relative in 'state', 'config.local.json', 'mod\Assets\Python\LocalConfig.py') {
            $path = Join-Path $repoRoot $relative
            if (-not (Test-Path -LiteralPath $path)) { continue }
            if ($PSCmdlet.ShouldProcess($path, 'Delete')) {
                Remove-Item -LiteralPath $path -Recurse -Force -Confirm:$false
                Write-Ok "deleted $relative"
            }
        }
    }

    Write-Head "Done"
    Write-Host "  civ4-advisor is no longer loaded by Civ IV. The game runs unmodded as before." -ForegroundColor Gray
    if ($IncludeState) {
        Write-Host "  Your recorded games and config files were deleted, as you asked." -ForegroundColor Gray
        Write-Host "  The mod itself is still here - run setup.bat to reinstall." -ForegroundColor Gray
    } else {
        Write-Host "  Nothing in this folder was deleted - run setup.bat to reinstall." -ForegroundColor Gray
    }

} catch {
    Write-Host ""
    Write-Host "Uninstall stopped:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    exit 1
}
