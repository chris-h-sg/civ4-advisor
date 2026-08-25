<#
.SYNOPSIS
Set up civ4-advisor: deploy the mod into Civ IV, write the config files, and
create a shortcut that launches the game straight into it.

.DESCRIPTION
Run this once, from the folder you cloned or unzipped this repo into. It:

  1. Finds your Civ IV: Beyond the Sword install and your Civ IV settings folder
     (the one holding CivilizationIV.ini), asking you to confirm each.
  2. Writes config.local.json and mod\Assets\Python\LocalConfig.py.
  3. Links the mod into your MODS folder.
  4. Turns on Python logging in CivilizationIV.ini (backing it up first).
  5. Puts a "Civ IV - civ4-advisor" shortcut on your Desktop.

Nothing is written until both paths are confirmed, so quitting at a prompt
leaves your machine untouched. Re-running is safe: anything already correct is
reported and left alone.

No administrator rights are needed.

.PARAMETER InstallPath
Your Civ IV install folder - the one CONTAINING "Beyond the Sword", not the
"Beyond the Sword" folder itself. Skips the detection prompt.

.PARAMETER UserDataPath
Your Civ IV settings folder - the one containing CivilizationIV.ini, normally
under Documents\My Games\Beyond the Sword. Skips the detection prompt.

.PARAMETER Verify
Check everything and print a report. Changes nothing. Use this when state files
are not appearing and you want to know why. verify.bat is a double-clickable
wrapper for exactly this.

.PARAMETER NoShortcut
Skip creating the Desktop shortcut.

.PARAMETER Force
Overwrite generated config files without asking. Backups are still made.

.EXAMPLE
.\setup.ps1

.EXAMPLE
.\setup.ps1 -Verify

.EXAMPLE
.\setup.ps1 -InstallPath "D:\Games\Sid Meier's Civilization IV Beyond the Sword"
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallPath,
    [Alias('ModsPath')]
    [string]$UserDataPath,
    [switch]$Verify,
    [switch]$NoShortcut,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

## The mod folder's leaf name under MODS is not cosmetic: Beyond the Sword
## requires Mods\<Name>\<Name>.ini, and ours is mod\civ4-advisor.ini.
$MOD_NAME = "civ4-advisor"
$BTS_APPID = "8800"

## ---------------------------------------------------------------- output ----

$script:Results = @()

function Write-Head($Text) { Write-Host "`n$Text" -ForegroundColor Cyan }
function Write-Ok($Text)   { Write-Host "  [ok]   $Text" -ForegroundColor Green }
function Write-Warn2($Text){ Write-Host "  [warn] $Text" -ForegroundColor Yellow }
function Write-Info($Text) { Write-Host "  $Text" -ForegroundColor DarkGray }

function Add-Result($Name, $Status, $Detail) {
    $script:Results += [pscustomobject]@{ Name = $Name; Status = $Status; Detail = $Detail }
}

## ------------------------------------------------------------ validators ----

## An install root is valid iff the BTS executable sits under it. This one test
## also excludes the decoy Mods folders inside the install tree, and matches
## what harness/rules.py needs (it composes <install>\Beyond the Sword\Assets\XML).
function Test-IsBtsInstallRoot($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try { Test-Path -LiteralPath (Join-Path $Path "Beyond the Sword\Civ4BeyondSword.exe") }
    catch { $false }
}

## The settings folder is identified by CivilizationIV.ini, not by MODS\ - a
## fresh install has no MODS folder and we create it.
function Test-IsCivUserDataFolder($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try { Test-Path -LiteralPath (Join-Path $Path "CivilizationIV.ini") }
    catch { $false }
}

## Resolve a relative path against PowerShell's location, not .NET's process
## working directory - the two drift apart (PowerShell does not update .NET's on
## Set-Location), so GetFullPath('foo') can silently resolve somewhere the user
## never meant.
function Get-Canonical($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    try {
        if (-not [System.IO.Path]::IsPathRooted($Path)) {
            $Path = Join-Path (Get-Location).ProviderPath $Path
        }
        [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    } catch { $Path.TrimEnd('\') }
}

## ------------------------------------------------------------- detection ----

## Steam stores library roots in libraryfolders.vdf with doubled backslashes.
function Get-SteamLibraryRoots {
    $roots = @()
    foreach ($key in 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam',
                     'HKLM:\SOFTWARE\Valve\Steam',
                     'HKCU:\Software\Valve\Steam') {
        try {
            $props = Get-ItemProperty -Path $key -ErrorAction Stop
            foreach ($value in @($props.InstallPath, $props.SteamPath)) {
                if ($value) { $roots += $value }
            }
        } catch { }
    }
    $extra = @()
    foreach ($root in $roots) {
        $vdf = Join-Path $root 'steamapps\libraryfolders.vdf'
        if (Test-Path -LiteralPath $vdf) {
            $text = Get-Content -LiteralPath $vdf -Raw
            foreach ($match in [regex]::Matches($text, '"path"\s*"([^"]+)"')) {
                ## The vdf stores "D:\\SteamLibrary" - two literal backslashes, so
                ## the pattern needs four. Getting this wrong leaves the path
                ## doubled and silently skips that whole library.
                $extra += ($match.Groups[1].Value -replace '\\\\', '\')
            }
        }
    }
    ($roots + $extra) | Where-Object { $_ } |
        ForEach-Object { $_.TrimEnd('\', '/') } | Sort-Object -Unique
}

function Find-Civ4InstallCandidates {
    $candidates = @()

    foreach ($lib in Get-SteamLibraryRoots) {
        ## The app manifest names the install folder authoritatively.
        $acf = Join-Path $lib "steamapps\appmanifest_$BTS_APPID.acf"
        if (Test-Path -LiteralPath $acf) {
            $match = [regex]::Match((Get-Content -LiteralPath $acf -Raw), '"installdir"\s*"([^"]+)"')
            if ($match.Success) {
                $candidates += Join-Path $lib "steamapps\common\$($match.Groups[1].Value)"
            }
        }
        $candidates += Join-Path $lib "steamapps\common\Sid Meier's Civilization IV Beyond the Sword"
    }

    $bases = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, 'C:\Games', 'D:\Games',
               'C:\GOG Games', 'D:\GOG Games')
    foreach ($base in $bases) {
        if (-not $base) { continue }
        $candidates += Join-Path $base "Sid Meier's Civilization IV Beyond the Sword"
        $candidates += Join-Path $base "2K Games\Firaxis Games\Sid Meier's Civilization IV Beyond the Sword"
        $candidates += Join-Path $base "GOG Galaxy\Games\Sid Meier's Civilization IV Beyond the Sword"
    }

    ## GOG records its own install paths.
    foreach ($gogKey in 'HKLM:\SOFTWARE\WOW6432Node\GOG.com\Games',
                        'HKLM:\SOFTWARE\GOG.com\Games') {
        Get-ChildItem -Path $gogKey -ErrorAction SilentlyContinue | ForEach-Object {
            $props = Get-ItemProperty -Path $_.PSPath -ErrorAction SilentlyContinue
            if ($props.path) { $candidates += $props.path }
        }
    }

    ## Registry uninstall entries LAST, and only when InstallLocation is actually
    ## populated - the Civ IV entry exists with an empty value on a real install,
    ## and an empty string here turns into a confusing downstream failure.
    foreach ($uninstall in 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
                           'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall') {
        Get-ChildItem -Path $uninstall -ErrorAction SilentlyContinue | ForEach-Object {
            $props = Get-ItemProperty -Path $_.PSPath -ErrorAction SilentlyContinue
            if ($props.DisplayName -like '*Civilization IV*' -and $props.InstallLocation) {
                $candidates += $props.InstallLocation.Trim('"')
            }
        }
    }

    $candidates | Where-Object { $_ } | ForEach-Object { Get-Canonical $_ } |
        Sort-Object -Unique | Where-Object { Test-IsBtsInstallRoot $_ }
}

## Documents is frequently redirected into OneDrive. GetFolderPath('MyDocuments')
## follows the redirection; $env:USERPROFILE\Documents does not, and is wrong on
## any redirected machine - so it is a fallback, never the primary probe.
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

function Resolve-PathChoice($Label, $Candidates, $Validator, $Explicit, $FailHelp) {
    if ($Explicit) {
        $path = Get-Canonical $Explicit.Trim().Trim('"')
        if (-not (& $Validator $path)) {
            throw "$Label was given as '$Explicit', but $FailHelp"
        }
        return $path
    }

    if (-not $Candidates -or $Candidates.Count -eq 0) {
        throw "Could not find $Label.`n$FailHelp"
    }

    $list = @($Candidates)
    Write-Host "`nFound $Label" -ForegroundColor Cyan
    for ($i = 0; $i -lt $list.Count; $i++) {
        Write-Host "  [$($i + 1)] $($list[$i])"
    }

    while ($true) {
        $answer = Read-Host "Press ENTER to use [1], a number to pick another, or paste the correct path"
        if ([string]::IsNullOrWhiteSpace($answer)) { return $list[0] }
        if ($answer -match '^\d+$' -and [int]$answer -ge 1 -and [int]$answer -le $list.Count) {
            return $list[[int]$answer - 1]
        }
        ## Explorer's "Copy as path" wraps the path in quotes, and people paste it verbatim.
        $typed = Get-Canonical $answer.Trim().Trim('"')
        if (& $Validator $typed) { return $typed }
        Write-Host "  That path doesn't look right - $FailHelp" -ForegroundColor Yellow
    }
}

## ----------------------------------------------------------------- files ----

function Write-TextFileUtf8NoBom($Path, $Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Backup-File($Path) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = "$Path.civ4-advisor-backup-$stamp"
    Copy-Item -LiteralPath $Path -Destination $backup -ErrorAction Stop
    return $backup
}

## Returns $true when the caller should write $Path.
function Confirm-Overwrite($Path, $NewText, $Label) {
    if (-not (Test-Path -LiteralPath $Path)) { return $true }

    $existing = [System.IO.File]::ReadAllText($Path)
    if ($existing -eq $NewText) {
        Write-Ok "$Label already correct"
        Add-Result $Label 'AlreadyCorrect' $Path
        return $false
    }

    if (-not $Force) {
        Write-Warn2 "$Label already exists and differs from what setup would write."
        Write-Info "  $Path"
        $answer = Read-Host "  Overwrite? A backup will be kept. [y/N]"
        if ($answer -notmatch '^[Yy]') {
            Write-Info "  Left alone."
            Add-Result $Label 'Skipped' 'existing file kept'
            return $false
        }
    }

    $backup = Backup-File $Path
    Write-Info "  backed up to $(Split-Path -Leaf $backup)"
    return $true
}

function Write-ConfigLocalJson($RepoRoot, $Install, $Mods) {
    $path = Join-Path $RepoRoot 'config.local.json'
    ## Built by hand rather than with ConvertTo-Json, which on 5.1 escapes an
    ## apostrophe to ' - valid JSON that still parses, but this file is
    ## meant to be opened and read by a person, and "Sid Meier's" does not
    ## read. Only backslash and double-quote need escaping for these values.
    function ConvertTo-JsonString($Value) {
        $Value.Replace('\', '\\').Replace('"', '\"')
    }
    $text = "{`r`n" +
            "  `"civ4_install_path`": `"$(ConvertTo-JsonString $Install)`",`r`n" +
            "  `"civ4_mods_path`": `"$(ConvertTo-JsonString $Mods)`"`r`n" +
            "}`r`n"

    if (Confirm-Overwrite $path $text 'config.local.json') {
        if ($PSCmdlet.ShouldProcess($path, 'Write')) {
            Write-TextFileUtf8NoBom $path $text
            Write-Ok "config.local.json written"
            Add-Result 'config.local.json' 'Written' $path
        }
    }
}

function Write-LocalConfigPy($RepoRoot) {
    $path = Join-Path $RepoRoot 'mod\Assets\Python\LocalConfig.py'
    ## Python 2.4 raw strings: a raw string cannot end in a backslash, so every
    ## path embedded here is trimmed first.
    $stateDir  = (Join-Path $RepoRoot 'state').TrimEnd('\')
    $pythonDir = (Join-Path $RepoRoot 'mod\Assets\Python').TrimEnd('\')

    ## LOG_TIMINGS is the one setting here a person turns on deliberately, and
    ## the paths are the only thing setup owns. Carry an existing value forward
    ## rather than quietly resetting it - regenerating the file should not undo
    ## a choice the user made in it.
    $logTimings = 'False'
    if (Test-Path -LiteralPath $path) {
        $existing = [regex]::Match((Get-Content -LiteralPath $path -Raw),
                                   '(?m)^\s*LOG_TIMINGS\s*=\s*(?<v>True|False)')
        if ($existing.Success) { $logTimings = $existing.Groups['v'].Value }
    }

    $text = @"
## LocalConfig.py - generated by setup.ps1. Machine-specific, not committed.
## Safe to edit by hand; re-running setup.ps1 will offer to regenerate it.
##
## Without this file the mod loads, runs, and writes NOTHING - no error, no
## popup, no log line. If state files stop appearing, check here first.

## Root directory state is written under. Each game gets its own subfolder
## holding one file per turn (turn_0000.json, turn_0001.json, ...).
STATE_DIR = r'$stateDir'

## Lets the mod re-read AdvisorStateWriter.py from disk on each export, so edits
## apply without restarting the game. Only useful if you are editing the mod.
MOD_PYTHON_DIR = r'$pythonDir'

## Per-section export timings to Logs\PythonDbg.log. A slow map scan is warned
## about regardless of this setting.
LOG_TIMINGS = $logTimings
"@ -replace "`r`n", "`n" -replace "`n", "`r`n"

    if (Confirm-Overwrite $path $text 'LocalConfig.py') {
        if ($PSCmdlet.ShouldProcess($path, 'Write')) {
            Write-TextFileUtf8NoBom $path $text
            Write-Ok "LocalConfig.py written (this is what makes the mod export anything)"
            Add-Result 'LocalConfig.py' 'Written' $path
        }
    }
}

## -------------------------------------------------------------- junction ----

function Install-ModJunction($RepoRoot, $ModsPath) {
    $modSource = Get-Canonical (Join-Path $RepoRoot 'mod')
    $linkPath  = Join-Path $ModsPath $MOD_NAME

    if (-not (Test-Path -LiteralPath $ModsPath)) {
        if ($PSCmdlet.ShouldProcess($ModsPath, 'Create MODS folder')) {
            New-Item -ItemType Directory -Path $ModsPath -Force | Out-Null
            Write-Info "created $ModsPath"
        }
    }

    if (Test-Path -LiteralPath $linkPath) {
        $item = Get-Item -LiteralPath $linkPath -Force
        if ($item.LinkType -in @('Junction', 'SymbolicLink')) {
            $current = Get-Canonical @($item.Target)[0]
            if ($current -ieq $modSource) {
                Write-Ok "mod already linked into MODS"
                Add-Result 'Mod link' 'AlreadyCorrect' "$linkPath -> $modSource"
                return
            }
            throw @"
MODS\$MOD_NAME already exists and points somewhere else:
  currently -> $current
  wanted    -> $modSource
Another copy of civ4-advisor is probably already installed.
Remove the link and re-run, or keep it and stop here. This script will not
delete it for you.
  To remove:  rmdir "$linkPath"
  (that deletes only the link, never the files it points to)
"@
        }
        throw @"
MODS\$MOD_NAME exists and is a REAL FOLDER, not a link:
  $linkPath
This script will not touch it - it may contain files you care about.
Rename or move it, then re-run.
"@
    }

    if ($PSCmdlet.ShouldProcess($linkPath, 'Create junction')) {
        try {
            New-Item -ItemType Junction -Path $linkPath -Target $modSource -ErrorAction Stop | Out-Null
        } catch {
            throw @"
Could not create the link:
  $linkPath  ->  $modSource
  $($_.Exception.Message)
Most likely causes:
  - Your Documents folder is on a network share or a non-NTFS drive
    (junctions need a local NTFS volume).
  - OneDrive "Files On-Demand" is still syncing that folder.
"@
        }
        Write-Ok "mod linked into MODS"
        Add-Result 'Mod link' 'Created' "$linkPath -> $modSource"
    }
}

## ------------------------------------------------------------------- ini ----

## Replace one key's value in place, preserving the file's own spacing and line
## endings. Two details, both measured against the real 246-line CRLF ini:
##   [^\r\n]* rather than .* - under (?m) the dot excludes \n but NOT \r, so .*
##   would swallow the carriage return, silently converting that line to LF.
##   No trailing $ anchor - having stopped before the \r, $ under (?m) matches
##   only before the \n, so anchoring there matches nothing at all in a CRLF
##   file. [^\r\n]* already runs to the line end, so the anchor is redundant.
function Set-IniValue($Text, $Key, $Value, [ref]$Changed, [ref]$Found) {
    $pattern = "(?m)^(?<pre>[ \t]*$([regex]::Escape($Key))[ \t]*=[ \t]*)(?<val>[^\r\n]*)"
    $match = [regex]::Match($Text, $pattern)
    if (-not $match.Success) {
        $Found.Value = $false; $Changed.Value = $false
        return $Text
    }
    $Found.Value = $true
    if ($match.Groups['val'].Value.Trim() -eq $Value) {
        $Changed.Value = $false
        return $Text
    }
    $Changed.Value = $true
    ## A MatchEvaluator, not a '${pre}...' replacement string - the latter would
    ## interpret $ and \ appearing in the value.
    ##
    ## The INSTANCE Replace is used because only it has a count overload. The
    ## static [regex]::Replace(input, pattern, evaluator, N) looks like it takes
    ## a count but its 4th parameter is RegexOptions - so N=1 silently means
    ## IgnoreCase and replaces EVERY match. The ini is sectioned, so that would
    ## rewrite a same-named key in every section it appears in.
    $re = New-Object System.Text.RegularExpressions.Regex $pattern
    return $re.Replace($Text,
        [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $m.Groups['pre'].Value + $Value },
        1)
}

function Get-IniValue($Text, $Key) {
    $pattern = "(?m)^[ \t]*$([regex]::Escape($Key))[ \t]*=[ \t]*(?<val>[^\r\n]*)"
    $match = [regex]::Match($Text, $pattern)
    if ($match.Success) { return $match.Groups['val'].Value.Trim() }
    return $null
}

function Update-CivilizationIni($UserData) {
    $iniPath = Join-Path $UserData 'CivilizationIV.ini'
    $text = [System.IO.File]::ReadAllText($iniPath)

    $changedLog = $false; $foundLog = $false
    $changedHide = $false; $foundHide = $false

    ## LoggingEnabled = 1 is not a debugging nicety here. With it at the default
    ## 0 the Python log stops updating after startup, which is the only way to
    ## tell "mod not deployed" apart from "deployed but misconfigured".
    $new = Set-IniValue $text 'LoggingEnabled' '1' ([ref]$changedLog) ([ref]$foundLog)
    ## Show Python errors in-game rather than swallowing the popup.
    $new = Set-IniValue $new 'HidePythonExceptions' '0' ([ref]$changedHide) ([ref]$foundHide)

    if (-not $foundLog -or -not $foundHide) {
        $missing = @()
        if (-not $foundLog)  { $missing += 'LoggingEnabled' }
        if (-not $foundHide) { $missing += 'HidePythonExceptions' }
        Write-Warn2 "CivilizationIV.ini has no $($missing -join ' or ')."
        Write-Info "  Your ini looks incomplete - the game writes the full file on first run."
        Write-Info "  Launch Beyond the Sword once, quit, then re-run this script."
        Write-Info "  Nothing was changed and no backup was made."
        Add-Result 'CivilizationIV.ini' 'Skipped' "missing key(s): $($missing -join ', ')"
        return
    }

    if (-not ($changedLog -or $changedHide)) {
        Write-Ok "CivilizationIV.ini already set correctly"
        Add-Result 'CivilizationIV.ini' 'AlreadyCorrect' $iniPath
        return
    }

    if ($PSCmdlet.ShouldProcess($iniPath, 'Set LoggingEnabled=1, HidePythonExceptions=0')) {
        $backup = Backup-File $iniPath
        ## The file is pure ASCII, so BOM-less UTF-8 is byte-identical apart from
        ## the digits we changed.
        Write-TextFileUtf8NoBom $iniPath $new
        Write-Ok "CivilizationIV.ini updated (logging on, Python errors shown)"
        Write-Info "  backed up to $(Split-Path -Leaf $backup)"
        Add-Result 'CivilizationIV.ini' 'Written' $iniPath
    }
}

## -------------------------------------------------------------- shortcut ----

function New-ModShortcut($Install) {
    $exe = Join-Path $Install 'Beyond the Sword\Civ4BeyondSword.exe'
    $workingDir = Join-Path $Install 'Beyond the Sword'
    $linkPath = Join-Path ([Environment]::GetFolderPath('Desktop')) "Civ IV - $MOD_NAME.lnk"
    ## The mod name has no spaces, so the argument needs no quoting - and quoting
    ## it is the form most often reported as failing to load.
    $arguments = "mod=\Mods\$MOD_NAME"

    if ($PSCmdlet.ShouldProcess($linkPath, 'Create shortcut')) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($linkPath)
        $shortcut.TargetPath = $exe
        $shortcut.Arguments = $arguments
        $shortcut.WorkingDirectory = $workingDir
        $shortcut.Description = "Civilization IV: Beyond the Sword with the civ4-advisor mod"
        $shortcut.Save()

        Write-Ok "Desktop shortcut created: Civ IV - $MOD_NAME"
        Write-Info "  target: $exe"
        Write-Info "  args:   $arguments"
        Add-Result 'Desktop shortcut' 'Created' $linkPath
    }
}

## ---------------------------------------------------------------- verify ----

function Invoke-Verify($RepoRoot, $Install, $UserData) {
    $failures = 0
    function Row($Status, $Name, $Detail) {
        $colour = switch ($Status) {
            'PASS' { 'Green' } 'WARN' { 'Yellow' } default { 'Red' }
        }
        Write-Host ("  [{0}] {1,-22} {2}" -f $Status, $Name, $Detail) -ForegroundColor $colour
    }

    Write-Head "civ4-advisor - checking your setup"

    Row 'PASS' 'Civ IV install' $Install
    Row 'PASS' 'Civ IV settings' $UserData

    ## Mod link.
    $modSource = Get-Canonical (Join-Path $RepoRoot 'mod')
    $linkPath = Join-Path (Join-Path $UserData 'MODS') $MOD_NAME
    if (-not (Test-Path -LiteralPath $linkPath)) {
        Row 'FAIL' 'Mod link' "missing - the mod is not installed. Run setup.bat"
        $failures++
    } else {
        $item = Get-Item -LiteralPath $linkPath -Force
        if ($item.LinkType -in @('Junction', 'SymbolicLink')) {
            $current = Get-Canonical @($item.Target)[0]
            if ($current -ieq $modSource) { Row 'PASS' 'Mod link' "-> $current" }
            else { Row 'FAIL' 'Mod link' "points at $current, not $modSource"; $failures++ }
        } else {
            Row 'WARN' 'Mod link' "a real folder, not a link to this repo"
        }
    }

    ## LocalConfig.py - the silent failure.
    $localConfig = Join-Path $RepoRoot 'mod\Assets\Python\LocalConfig.py'
    if (-not (Test-Path -LiteralPath $localConfig)) {
        Row 'FAIL' 'LocalConfig.py' 'MISSING - the mod will write NOTHING'
        Write-Host "         Without it the mod loads, runs, and exports nothing: no error," -ForegroundColor Red
        Write-Host "         no popup, no log line. This is the #1 cause of 'it isn't working'." -ForegroundColor Red
        Write-Host "         Fix: re-run setup.bat" -ForegroundColor Red
        $failures++
    } else {
        $stateDir = $null
        $match = [regex]::Match((Get-Content -LiteralPath $localConfig -Raw),
                                "(?m)^\s*STATE_DIR\s*=\s*r?['`"](?<v>[^'`"]*)['`"]")
        if ($match.Success) { $stateDir = $match.Groups['v'].Value }
        if ([string]::IsNullOrWhiteSpace($stateDir)) {
            Row 'FAIL' 'LocalConfig.py' 'STATE_DIR is not set - the mod will write NOTHING'
            $failures++
        } elseif (-not (Test-Path -LiteralPath $stateDir)) {
            Row 'WARN' 'LocalConfig.py' "STATE_DIR does not exist yet: $stateDir"
        } else {
            Row 'PASS' 'LocalConfig.py' "STATE_DIR = $stateDir"
        }
    }

    ## config.local.json, checked the way harness/rules.py uses it.
    $configPath = Join-Path $RepoRoot 'config.local.json'
    if (-not (Test-Path -LiteralPath $configPath)) {
        Row 'FAIL' 'config.local.json' 'missing - rules.py cannot read the game XML'
        $failures++
    } else {
        try {
            $configured = (Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).civ4_install_path
            $xml = Join-Path $configured 'Beyond the Sword\Assets\XML'
            if (Test-Path -LiteralPath $xml) { Row 'PASS' 'config.local.json' "game XML found" }
            else { Row 'FAIL' 'config.local.json' "no XML at $xml"; $failures++ }
        } catch {
            Row 'FAIL' 'config.local.json' "not valid JSON"; $failures++
        }
    }

    ## The ini.
    $iniPath = Join-Path $UserData 'CivilizationIV.ini'
    $iniText = [System.IO.File]::ReadAllText($iniPath)
    $logging = Get-IniValue $iniText 'LoggingEnabled'
    $hiding  = Get-IniValue $iniText 'HidePythonExceptions'
    if ($logging -eq '1') { Row 'PASS' 'CivilizationIV.ini' "LoggingEnabled = 1" }
    else { Row 'WARN' 'CivilizationIV.ini' "LoggingEnabled = $logging (the Python log will not update)" }
    if ($hiding -ne '0') {
        Row 'WARN' 'CivilizationIV.ini' "HidePythonExceptions = $hiding (errors hidden in-game)"
    }

    ## Python, since the harness tools need one on PATH.
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $version = (& $python.Source --version 2>&1) -join ' '
        Row 'PASS' 'Python' "$version ($($python.Source))"
    } else {
        Row 'FAIL' 'Python' "not on PATH - the advisor tools cannot run"
        $failures++
    }

    ## Is it actually producing anything? This is the line that answers
    ## "is it working?" without a support conversation.
    $stateRoot = Join-Path $RepoRoot 'state'
    if (-not (Test-Path -LiteralPath $stateRoot)) {
        Row 'WARN' 'state\' 'no state folder yet - play a turn and check again'
    } else {
        $games = @(Get-ChildItem -LiteralPath $stateRoot -Directory -ErrorAction SilentlyContinue)
        $newest = Get-ChildItem -LiteralPath $stateRoot -Filter 'turn_*.json' -Recurse -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $newest) {
            Row 'WARN' 'state\' "$($games.Count) game folder(s), no turn files yet"
        } else {
            $age = [int]((Get-Date) - $newest.LastWriteTime).TotalMinutes
            Row 'PASS' 'state\' "$($games.Count) game(s), newest $($newest.Name) ($age min ago)"
        }
    }

    Write-Host ""
    if ($failures -gt 0) {
        Write-Host "  $failures check(s) failed." -ForegroundColor Red
        return 1
    }
    Write-Host "  Everything checks out." -ForegroundColor Green
    return 0
}

## ------------------------------------------------------------------ main ----

try {
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        throw "This script needs Windows PowerShell 5.1 or later. Yours is $($PSVersionTable.PSVersion)."
    }

    $repoRoot = Get-Canonical $PSScriptRoot
    ## Same marker harness/rules.py uses to find the repo root.
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'config.local.json.example'))) {
        throw @"
This script must be run from inside the civ4-advisor folder.
Expected to find config.local.json.example next to setup.ps1, in:
  $repoRoot
Right-click setup.ps1 where you unzipped or cloned the repo and choose
"Run with PowerShell".
"@
    }

    Write-Head "civ4-advisor setup"

    $install = Resolve-PathChoice 'your Civ IV: Beyond the Sword install' `
        (Find-Civ4InstallCandidates) ${function:Test-IsBtsInstallRoot} $InstallPath @"
there is no Civ4BeyondSword.exe at <that path>\Beyond the Sword\Civ4BeyondSword.exe.
This should be the folder ABOVE "Beyond the Sword", not the "Beyond the Sword"
folder itself.
  - Steam: right-click Civilization IV in your library -> Manage -> Browse local
    files, then go UP one folder from "Beyond the Sword".
Then re-run:  setup.bat -InstallPath "D:\path\to\Sid Meier's Civilization IV Beyond the Sword"
"@

    $userData = Resolve-PathChoice 'your Civ IV settings folder' `
        (Find-CivUserDataCandidates) ${function:Test-IsCivUserDataFolder} $UserDataPath @"
there is no CivilizationIV.ini there.
This folder is created the first time you run the game, normally at
Documents\My Games\Beyond the Sword. If you have never launched Beyond the
Sword, launch it once, quit, and re-run this script.
If your Documents folder is redirected (OneDrive, or a work profile), pass it:
  setup.bat -UserDataPath "C:\...\Documents\My Games\Beyond the Sword"
"@

    $modsPath = Join-Path $userData 'MODS'

    ## Beyond the Sword loads mods from the Documents folder. The install tree
    ## also contains Mods folders holding the stock mods; deploying there does
    ## nothing at all, and looks like success.
    ## Compare with a trailing separator, or this is a string-prefix test rather
    ## than a path test: "C:\Games\CivIVdata" starts with "C:\Games\CivIV" and a
    ## legitimate sibling folder would be refused.
    if ((Get-Canonical $modsPath).StartsWith((Get-Canonical $install) + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw @"
REFUSING: the Mods folder resolved to a path inside the game install:
  $modsPath
Beyond the Sword loads mods from your Documents folder, not the install folder.
The install contains decoy "Mods" folders holding the stock mods; deploying
there does nothing.
Re-run with -UserDataPath pointing at the folder that contains CivilizationIV.ini.
"@
    }

    Write-Host ""
    Write-Info "install:  $install"
    Write-Info "settings: $userData"
    Write-Info "repo:     $repoRoot"

    if ($Verify) {
        exit (Invoke-Verify $repoRoot $install $userData)
    }

    ## ---- everything below this line writes ----

    Write-Head "Setting up"

    $stateRoot = Join-Path $repoRoot 'state'
    if (-not (Test-Path -LiteralPath $stateRoot)) {
        if ($PSCmdlet.ShouldProcess($stateRoot, 'Create')) {
            New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
            Write-Ok "created state\ (turn files land here)"
        }
    }

    Write-ConfigLocalJson $repoRoot $install $modsPath
    Write-LocalConfigPy $repoRoot
    Install-ModJunction $repoRoot $modsPath
    Update-CivilizationIni $userData

    if ($NoShortcut) {
        Write-Info "skipping the Desktop shortcut (-NoShortcut)"
    } else {
        New-ModShortcut $install
    }

    if ($env:OneDrive -and (Get-Canonical $modsPath).StartsWith((Get-Canonical $env:OneDrive) + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host ""
        Write-Warn2 "Your Civ IV settings folder is inside OneDrive."
        Write-Info "  This works, but if OneDrive starts syncing or 'freeing up space' on"
        Write-Info "  that folder the mod link can break. If turn files stop appearing,"
        Write-Info "  exclude 'My Games' from OneDrive sync and re-run this script."
    }

    Write-Head "Done"
    Write-Host @"
  Next:

  1. Launch the game with the "Civ IV - $MOD_NAME" shortcut on your Desktop.
     (Or: start Civ IV normally, then Advanced > Load a Mod > $MOD_NAME.)
     The main menu should show $MOD_NAME once it has loaded.

  2. Start a game. A folder appears under:
       $stateRoot
     If nothing appears there, double-click verify.bat

  3. Set up the advisor for that game: double-click new_game.bat
     It lists your games, you pick one, and it makes a folder for it.

  4. Open that folder in Claude Desktop (Code tab > Select folder), and
     start with:

       Read your instructions, then look at my position and tell me what to do.

  See README.md for the full walkthrough.
"@ -ForegroundColor Gray

} catch {
    Write-Host ""
    Write-Host "Setup stopped:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    exit 1
}
