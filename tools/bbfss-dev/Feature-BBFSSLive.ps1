#requires -Version 7
<#
Feature-BBFSSLive.ps1: play the DEV build (<dev>) with chosen new features switched on, to test them by hand.

  List the features:      pwsh -File <home>\Feature-BBFSSLive.ps1 -List
  Start with features:    pwsh -File <home>\Feature-BBFSSLive.ps1 -Feature footprints,bloodsheen
  Wind speed (m/s):       add -Speed 6            (1.5 light, 4 strong, 6 storm; read at start)
  Wind follows clouds:    add -Weather            (otherwise a steady wind, easier to judge)
  Change a LIVE switch while playing (taken in about half a second, no restart):
                          pwsh -File <home>\Feature-BBFSSLive.ps1 -Set BB_WIND_TWIGS=2
                          pwsh -File <home>\Feature-BBFSSLive.ps1 -Set BB_FOOTPRINTS_GAIN=0,BB_GLASS_GLINT=0
  Show the live switches now in force:
                          pwsh -File <home>\Feature-BBFSSLive.ps1 -Show

Uses your normal settings and save. Feature switches only live in this script's environment and in
<home>\bbfss-knobs.txt; lantern.ini and mods.json are not touched by this script (the in-game menu,
Insert or L3+R3, saves its own sliders as always). Refuses to start a second game while one is running.
#>
param(
    [string]$Dev = $env:BBFSS_DEV,   # the dev install folder (holds BBFSS.exe); or set BBFSS_DEV
    [string[]]$Feature = @(),
    [string[]]$Set = @(),
    [double]$Speed = 4,
    [switch]$Weather,
    [switch]$List,
    [switch]$Show
)
$ErrorActionPreference = 'Stop'
$knobs = Join-Path $env:USERPROFILE 'bbfss-knobs.txt'
$inv = [Globalization.CultureInfo]::InvariantCulture

# name -> start environment, live switches, where and what to look at
$features = [ordered]@{
    wind       = @{ env = [ordered]@{ BB_WIND = '1'; BB_WIND_SHELTER = '1'; BB_WIND_TWIGS_TREES = '1'; BB_FOG_NOISE = '1'; BB_FOG_NOISE_BANKS = '1'; BB_WIND_GAME = '1' }
                    live = 'BB_WIND_TWIGS=0/1/2/4 (twig amount)'
                    look = 'Graveyard: thin outer branches of the bare trees lean and spring back in gusts; haze and fog banks drift in the sky' }
    footprints = @{ env = [ordered]@{ BB_FOOTPRINTS = '1' }
                    live = 'BB_FOOTPRINTS_GAIN=0/1/2'
                    look = 'Graveyard: walk out of the blood pool, turn round, look at the red soles on the cobbles in the torch light (fade in about 30 s). Church puddles: wet soles. Menu: untick "Ray traced lamp shadows" to see them by the torch' }
    bloodsheen = @{ env = [ordered]@{ BB_BLOOD_SHEEN = '1'; BB_BLOOD_SHEEN_DRAW = 'c829ee58:dbb222eb'; BB_BLOOD_SHEEN_RULE = 'albedo' }
                    live = 'BB_BLOOD_SHEEN_PAUSE=1 (sheen off) / 0 (on)'
                    look = 'Graveyard: the blood pool under the torch, wet highlights moving as you move' }
    cutouts    = @{ env = [ordered]@{ BB_RT_CARD_ALPHA = '2'; BB_RT_CARD_LAMPS = '1' }
                    live = 'BB_RT_CARD_LAMPS=0/1'
                    look = 'Any place with weeds, ivy or leaves: hold the torch so a plant stands between it and a wall; the shadow on the wall should have leaf shapes' }
    lampshadow = @{ env = [ordered]@{ BB_LAMP_SHADOW_FLAME = '1'; BB_LAMP_SHADOW_LAYERS = '3'; BB_LAMP_SHADOW_MOVING_SMOOTH = '1' }
                    live = 'BB_LAMP_SHADOW_FLAME=0/1/2 (softness), BB_LAMP_SHADOW_LAYERS=0/1/3 (layered)'
                    look = 'Near a street lamp with the torch out: softer shadow edges with a darker core; two lights give overlapping, tinted shadows' }
    clouds     = @{ env = [ordered]@{ BB_VOLUMETRIC_CLOUDS = '1' }
                    live = 'BB_VOLUMETRIC_CLOUDS=0/1'
                    look = 'Outdoors, look up at open sky: a slow drifting cloud layer under the painted sky' }
    particles  = @{ env = [ordered]@{ BB_PARTICLES = '1' }
                    live = '(start only; -Feature particles2 for denser)'
                    look = 'Dust glow and embers round the torch and lamps, motes in lit rooms' }
    particles2 = @{ env = [ordered]@{ BB_PARTICLES = '2' }; live = '(start only)'; look = 'Denser particles' }
    sparks     = @{ env = [ordered]@{ BB_WEAPON_SPARKS = '2' }
                    live = '(start only)'
                    look = 'Anywhere: transform the weapon (L1); small sparks at the weapon, no big burst' }
    shafts     = @{ env = [ordered]@{ BB_LAMP_FOG_SHAFTS = '1' }
                    live = '(start only)'
                    look = 'Foggy alley or graveyard at night: light shafts from lamps and the torch through the fog' }
    sunfog     = @{ env = [ordered]@{ BB_VOLUMETRIC_AREA_GATE = '2'; BB_VOLUMETRIC_ROOF = '1' }
                    live = 'BB_VOLUMETRIC_AREA_GATE=0 (old) / 2 (sun fog kept out of rooms), BB_VOLUMETRIC_ROOF=0/1 (no sun fog under roofs; needs wind on)'
                    look = 'Go inside a building with sun outside (church, library, dream house), look up: no sun haze or shafts indoors; outdoors unchanged' }
    glass      = @{ env = [ordered]@{ BB_RT_GLASS = 'c6cdba2b:c31bd920;c6cdba2b:6720ae0d;e30b0480:8a6c7657'; BB_GLASS_GLINT = '1' }
                    live = 'BB_GLASS_GLINT=0/1'
                    look = "Hunter's Dream house: the leaded window panes glint when light hits them (unconfirmed, may be faint)" }
    caustics   = @{ env = [ordered]@{ BB_CAUSTICS = '1'; BB_CAUSTICS_LAMPS = '4'; BB_CAUSTICS_WORLD = '1' }
                    live = '(start only)'
                    look = 'Sewer water near a lantern: moving lines of light on the wall and floor; church puddles under the lantern (faint so far)' }
}

function Read-Knobs {
    $map = [ordered]@{}
    if (Test-Path $knobs) {
        foreach ($line in Get-Content $knobs) {
            $i = $line.IndexOf('=')
            if ($i -gt 0) { $map[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim() }
        }
    }
    return $map
}
function Write-Knobs($map) {
    $lines = foreach ($k in $map.Keys) { "$k=$($map[$k])" }
    Set-Content -Path $knobs -Value $lines -Encoding ascii
}

if ($List) {
    foreach ($n in $features.Keys) {
        Write-Host ("{0,-11} live: {1}" -f $n, $features[$n].live)
        Write-Host ("            {0}" -f $features[$n].look)
    }
    Write-Host 'Menu sliders (Insert or L3+R3, no script needed): Interior brightness, Halation strength, Lamp flicker strength,'
    Write-Host '  Flicker strength on already flickering lamps, Heat haze, Drawn look, Ray traced lamp shadows.'
    return
}

if ($Show) { $m = Read-Knobs; if ($m.Count) { $m.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" } } else { 'No live switches set.' }; return }

if ($Set.Count) {
    # live change: the running game reads the knobs file every 250 ms
    $m = Read-Knobs
    foreach ($pair in ($Set -split ',')) {
        $i = $pair.IndexOf('=')
        if ($i -le 0 -or $pair -notmatch '^BB_[A-Z0-9_]+=') { Write-Host "Not NAME=VALUE: $pair"; exit 2 }
        $m[$pair.Substring(0, $i)] = $pair.Substring($i + 1)
    }
    Write-Knobs $m
    Write-Host ('Set: ' + ($Set -join ', ') + ' (the game takes it in about half a second; only live switches act mid-game).')
    return
}

$names = @($Feature -split ',' | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
if (-not $names.Count) { Write-Host 'Name at least one feature (-List shows them), e.g. -Feature wind,footprints'; exit 2 }
if ($names -contains 'all') { $names = @($features.Keys | Where-Object { $_ -ne 'particles2' }) }
foreach ($n in $names) { if (-not $features.Contains($n)) { Write-Host "Unknown feature '$n'. Use -List."; exit 2 } }

$busy = Get-Process -Name 'bb-probe', 'bb-start', 'BBFSS' -ErrorAction SilentlyContinue
if ($busy) { Write-Host 'A game is already running. Close it first.'; exit 8 }

Set-Content -Path $knobs -Value @() -Encoding ascii          # start with no live overrides
$env:BB_LIVE_KNOBS_FILE = $knobs
foreach ($n in $names) {
    foreach ($k in $features[$n].env.Keys) { Set-Item -Path "env:$k" -Value $features[$n].env[$k] }
}
if ($names -contains 'wind') {
    $env:BB_WIND_SPEED   = $Speed.ToString($inv)
    $env:BB_WIND_WEATHER = if ($Weather) { '1' } else { '0' }
}
Write-Host ('Starting the dev build with: ' + ($names -join ', '))
foreach ($n in $names) { Write-Host ("  {0}: {1}" -f $n, $features[$n].look); Write-Host ("     live: {0}" -f $features[$n].live) }
if (-not $Dev -or -not (Test-Path (Join-Path $Dev 'BBFSS.exe'))) { Write-Host 'Give -Dev <dev install folder> or set BBFSS_DEV.'; exit 2 }
Start-Process -FilePath (Join-Path $Dev 'BBFSS.exe') -ArgumentList '--play' -WorkingDirectory $Dev
