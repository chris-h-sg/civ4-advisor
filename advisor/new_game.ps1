<#
.SYNOPSIS
Set up the advisor for one game, ready to point Claude Code at.

.DESCRIPTION
Run this once per game, AFTER you have started that game in Civ IV - the run
folder under state\ has to exist before this can link to it.

With no arguments it lists the games it can see, newest first, and lets you pick
one. The most recently played is the default, so pressing Enter is usually the
right answer.

Creates a folder containing links to this repo's harness/, that game's run
folder, the schema/ folder and your Civ IV install, plus a CLAUDE.md and
config.local.json so the tools resolve paths with no further setup. Then open
Claude Code in that folder and ask it about your position each turn.

schema/ is included because the advisor is sent to schema/state.schema.json for
a field's exact meaning, and 40 of its 84 field descriptions carry a caveat that
cannot be inferred from the turn files. Without it that instruction is a dead end.

The destination is deliberately NOT inside this repo: Claude Code walks up from
the current folder collecting CLAUDE.md files, so a folder nested here would
pick up the repo's developer instructions alongside the advisor persona.

.PARAMETER GameDir
The game's folder name under state\, e.g. LEADER_DARIUS_1785912623104. Omit it
to pick from a list.

.PARAMETER Destination
Where to create the advisor folder. Must not already exist, and must be outside
this repo. Omit it and you are asked, with a folder named after the game on your
Desktop offered as the default.

.EXAMPLE
.\new_game.ps1

.EXAMPLE
.\new_game.ps1 -GameDir LEADER_DARIUS_1785912623104 -Destination $HOME\Desktop\civ-game-1
#>
param(
    [string]$GameDir,
    [string]$Destination
)

$ErrorActionPreference = "Stop"

try {

    $repoRoot = Split-Path -Parent $PSScriptRoot
    $harnessPath = Join-Path $repoRoot "harness"
    $schemaPath = Join-Path $repoRoot "schema"
    $stateRoot = Join-Path $repoRoot "state"
    $configPath = Join-Path $repoRoot "config.local.json"

    if (-not (Test-Path -LiteralPath $harnessPath)) {
        throw "Expected $harnessPath - is this script still inside advisor/ in the repo?"
    }
    if (-not (Test-Path -LiteralPath $schemaPath)) {
        throw "Expected $schemaPath - is this script still inside advisor/ in the repo?"
    }

    $noGames = @"
No games found under state\.

Start a game in Civ IV first - the mod creates that game's folder the moment you
begin, and this script links to it. Play at least the first turn, then re-run.

If you have started a game and nothing appeared, the mod is not exporting. Run:
  setup.bat -Verify
"@

    ## Describe each run folder by what a person would recognise: the leader, how far
    ## along it is, and when it was last played. Ordered by the newest turn file
    ## rather than the folder's own timestamp - loading a save rewrites an existing
    ## turn file, so folder mtime does not track "most recently played".
    function Get-GameCandidates {
        $folders = @(Get-ChildItem -LiteralPath $stateRoot -Directory -ErrorAction SilentlyContinue)
        $described = foreach ($folder in $folders) {
            $turns = @(Get-ChildItem -LiteralPath $folder.FullName -Filter 'turn_*.json' -ErrorAction SilentlyContinue)
            if ($turns.Count -eq 0) { continue }

            ## Order by filename, never mtime - a resumed save rewrites its turn file.
            $latest = $turns | Sort-Object Name | Select-Object -Last 1
            $turnNumber = 0
            if ($latest.BaseName -match 'turn_(\d+)') { $turnNumber = [int]$Matches[1] }

            ## The leader is the folder name minus the synthetic game id the mod appends.
            $leader = $folder.Name -replace '^LEADER_', '' -replace '_\d+$', ''

            [pscustomobject]@{
                Name       = $folder.Name
                Leader     = (Get-Culture).TextInfo.ToTitleCase($leader.ToLower().Replace('_', ' '))
                Turn       = $turnNumber
                TurnCount  = $turns.Count
                LastPlayed = ($turns | Sort-Object LastWriteTime | Select-Object -Last 1).LastWriteTime
            }
        }
        @($described) | Sort-Object LastPlayed -Descending
    }

    function Format-Age($When) {
        $span = (Get-Date) - $When
        if ($span.TotalMinutes -lt 60)  { return "$([int]$span.TotalMinutes) min ago" }
        if ($span.TotalHours   -lt 24)  { return "$([int]$span.TotalHours) hours ago" }
        if ($span.TotalDays    -lt 30)  { return "$([int]$span.TotalDays) days ago" }
        return $When.ToString('d MMM yyyy')
    }

    ## @() around the CALL, not just inside the function: Sort-Object unrolls a
    ## one-element array back to a scalar, and a PSCustomObject's .Count is $null
    ## on PS 5.1. Without this the single-game case - the common one - takes the
    ## multi-candidate branch, prints an empty list, and rejects every number the
    ## user types.
    $candidates = @(Get-GameCandidates)

    if ($GameDir) {
        $gameStatePath = Join-Path $stateRoot $GameDir
        ## A folder that exists but holds no turn files is the "started a game but
        ## the mod isn't exporting" case, and $noGames is the message that explains
        ## it. Checking only Test-Path would junction an empty folder instead.
        $hasTurns = (Test-Path -LiteralPath $gameStatePath) -and
                    @(Get-ChildItem -LiteralPath $gameStatePath -Filter 'turn_*.json' -ErrorAction SilentlyContinue).Count -gt 0
        if (-not $hasTurns) {
            if ($candidates.Count -eq 0) { throw $noGames }
            if (Test-Path -LiteralPath $gameStatePath) {
                throw "$GameDir has no turn files yet.`n`n$noGames"
            }
            throw @"
No such game folder: $GameDir

Games available under state\:
$($candidates | ForEach-Object { "  $($_.Name)" } | Out-String)
Pass one of those as -GameDir, or run this with no arguments to pick from a list.
"@
        }
    } else {
        if ($candidates.Count -eq 0) { throw $noGames }

        if ($candidates.Count -eq 1) {
            $chosen = $candidates[0]
            Write-Host ""
            Write-Host "One game found: $($chosen.Leader), turn $($chosen.Turn) ($(Format-Age $chosen.LastPlayed))" -ForegroundColor Cyan
        } else {
            Write-Host ""
            Write-Host "Which game?" -ForegroundColor Cyan
            for ($i = 0; $i -lt $candidates.Count; $i++) {
                $c = $candidates[$i]
                Write-Host ("  [{0}] {1,-14} turn {2,-4} {3}" -f ($i + 1), $c.Leader, $c.Turn, (Format-Age $c.LastPlayed))
            }
            Write-Host ""

            while ($true) {
                $answer = Read-Host "Press ENTER for the most recent [1], or a number"
                if ([string]::IsNullOrWhiteSpace($answer)) { $chosen = $candidates[0]; break }
                if ($answer -match '^\d+$' -and [int]$answer -ge 1 -and [int]$answer -le $candidates.Count) {
                    $chosen = $candidates[[int]$answer - 1]
                    break
                }
                Write-Host "  Enter a number from 1 to $($candidates.Count)." -ForegroundColor Yellow
            }
        }

        $GameDir = $chosen.Name
        $gameStatePath = Join-Path $stateRoot $GameDir
    }

    if (-not (Test-Path -LiteralPath $configPath)) {
        throw "$configPath not found - run setup.bat at the repo root first."
    }

    $installPath = (Get-Content $configPath -Raw | ConvertFrom-Json).civ4_install_path
    if (-not $installPath) {
        throw "$configPath has no civ4_install_path"
    }
    if (-not (Test-Path -LiteralPath $installPath)) {
        throw "civ4_install_path in $configPath does not exist: $installPath"
    }

    ## Ask where to put it, suggesting the Desktop named for the game. Asked rather
    ## than assumed: this creates a folder somewhere the user will have to find
    ## again, and silently choosing that place for them is presumptuous.
    if (-not $Destination) {
        $leafName = ($GameDir -replace '^LEADER_', 'civ-' -replace '_\d+$', '').ToLower()
        $desktop = [Environment]::GetFolderPath('Desktop')
        $suggested = Join-Path $desktop $leafName

        ## Never propose a name that already exists: a second advisor folder for the
        ## same leader would otherwise collide and simply be refused below.
        $suffix = 2
        while (Test-Path -LiteralPath $suggested) {
            $suggested = Join-Path $desktop "$leafName-$suffix"
            $suffix++
        }

        Write-Host ""
        Write-Host "Where should the advisor folder go?" -ForegroundColor Cyan
        Write-Host "  $suggested" -ForegroundColor DarkGray

        while ($true) {
            $answer = Read-Host "Press ENTER to use that, or type another path"
            if ([string]::IsNullOrWhiteSpace($answer)) { $Destination = $suggested; break }

            ## Explorer's "Copy as path" wraps in quotes, and people paste it verbatim.
            $typed = $answer.Trim().Trim('"')
            try {
                $candidate = [System.IO.Path]::GetFullPath($typed).TrimEnd('\')
            } catch {
                Write-Host "  That doesn't look like a valid path." -ForegroundColor Yellow
                continue
            }
            if (Test-Path -LiteralPath $candidate) {
                Write-Host "  $candidate already exists - pick a folder that doesn't." -ForegroundColor Yellow
                continue
            }
            $Destination = $candidate
            break
        }
    }

    ## Normalise ONCE, before any check, and use the result everywhere after.
    ## Test-Path and New-Item resolve a relative path against PowerShell's
    ## location while GetFullPath uses .NET's process directory, and the two
    ## drift apart - so `-Destination my-game` could be guarded at one path and
    ## created at another, silently bypassing the repo check below.
    if (-not [System.IO.Path]::IsPathRooted($Destination)) {
        $Destination = Join-Path (Get-Location).ProviderPath $Destination
    }
    $Destination = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')

    if (Test-Path -LiteralPath $Destination) {
        throw "$Destination already exists - remove it first, or pass a different -Destination."
    }

    ## Enforced, not just documented: Claude Code collects CLAUDE.md files walking up
    ## from the folder it starts in, so an advisor folder nested inside this repo
    ## would silently load the developer instructions alongside the advisor persona.
    ## The symptom would be strange advice, with nothing on screen to explain it.
    $destFull = $Destination
    $repoFull = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd('\')
    if ($destFull -ieq $repoFull -or $destFull.StartsWith($repoFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw @"
That folder is inside the civ4-advisor repo:
  $destFull

It has to go somewhere else. Claude Code picks up instruction files from every
folder above the one it starts in, so an advisor folder nested here would load
this repo's developer instructions too, and give you odd advice with nothing on
screen to explain why.

Your Desktop or Documents folder is fine.
"@
    }

    ## Roll back on a partial failure - e.g. the install is on a drive that is
    ## currently offline. Without this the half-built folder stays behind, every
    ## retry hits "already exists", and the obvious recovery (Remove-Item
    ## -Recurse over a folder of junctions) is the one command that can traverse
    ## into the Civ IV install and this repo. Junctions are removed with
    ## Directory.Delete, which unlinks without ever following the link.
    $links = @(
        @{ Name = "harness";      Target = $harnessPath },
        @{ Name = "schema";       Target = $schemaPath },
        @{ Name = "state";        Target = $gameStatePath },
        @{ Name = "civ4_install"; Target = $installPath }
    )
    New-Item -ItemType Directory -Path $Destination | Out-Null
    try {
        foreach ($link in $links) {
            New-Item -ItemType Junction -Path (Join-Path $Destination $link.Name) -Target $link.Target | Out-Null
        }
    } catch {
        foreach ($link in $links) {
            $p = Join-Path $Destination $link.Name
            if (Test-Path -LiteralPath $p) { try { [System.IO.Directory]::Delete($p) } catch { } }
        }
        try { Remove-Item -LiteralPath $Destination -Force -Confirm:$false } catch { }
        throw "Could not finish setting up $Destination`n  $($_.Exception.Message)`n`nNothing was left behind. Fix that and re-run."
    }

    Copy-Item (Join-Path $PSScriptRoot "CLAUDE.md") (Join-Path $Destination "CLAUDE.md")

    $configJson = @{ civ4_install_path = "civ4_install" } | ConvertTo-Json
    [System.IO.File]::WriteAllText((Join-Path $Destination "config.local.json"), $configJson, [System.Text.UTF8Encoding]::new($false))

    Write-Host ""
    Write-Host "Advisor folder ready: $Destination" -ForegroundColor Green
    Write-Host "  game -> $GameDir" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Now open Claude Code there:" -ForegroundColor Gray
    Write-Host "  cd `"$Destination`"" -ForegroundColor Gray
    Write-Host "  claude" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Then start with:" -ForegroundColor Gray
    Write-Host "  Read your instructions, then look at my position and tell me what to do." -ForegroundColor White
    Write-Host ""
    Write-Host "After that, just tell it when you have played a turn." -ForegroundColor DarkGray

} catch {
    Write-Host ""
    Write-Host "Setup stopped:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    exit 1
}
