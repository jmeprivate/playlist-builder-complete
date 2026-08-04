[CmdletBinding()]
param(
    [string]$MusicRoot,
    [switch]$SkipConfig
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $RootDir '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$ConfigFile = Join-Path $RootDir 'config.ini'

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "El comando fallo con codigo ${LASTEXITCODE}: $FilePath $($ArgumentList -join ' ')"
    }
}

$candidates = @(
    [PSCustomObject]@{ Exe = 'py'; Args = @('-3.13') },
    [PSCustomObject]@{ Exe = 'py'; Args = @('-3.12') },
    [PSCustomObject]@{ Exe = 'python'; Args = @() },
    [PSCustomObject]@{ Exe = 'python3'; Args = @() }
)

$selected = $null
foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) {
        continue
    }

    $exe = $candidate.Exe
    $baseArgs = [string[]]$candidate.Args
    & $exe @baseArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" *> $null
    if ($LASTEXITCODE -eq 0) {
        $selected = $candidate
        break
    }
}

if ($null -eq $selected) {
    throw 'Se necesita Python 3.12 o posterior.'
}

Push-Location $RootDir
try {
    Write-Host "Preparando Playlist Builder en $RootDir"

    $pythonExe = $selected.Exe
    $pythonArgs = [string[]]$selected.Args
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Invoke-Checked -FilePath $pythonExe -ArgumentList ($pythonArgs + @('-m', 'venv', $VenvDir))
    }

    Invoke-Checked -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'install', '--upgrade', 'pip')
    Invoke-Checked -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'install', '-e', $RootDir)

    if (-not $SkipConfig -and [string]::IsNullOrWhiteSpace($MusicRoot)) {
        $MusicRoot = Read-Host 'Ruta de la carpeta musical (Enter para dejar config.ini sin cambios)'
    }

    if (-not [string]::IsNullOrWhiteSpace($MusicRoot)) {
        if (-not (Test-Path -LiteralPath $MusicRoot -PathType Container)) {
            throw "La carpeta musical no existe: $MusicRoot"
        }

        $resolvedMusicRoot = (Resolve-Path -LiteralPath $MusicRoot).Path
        $lines = [System.IO.File]::ReadAllLines($ConfigFile)
        $found = $false
        for ($index = 0; $index -lt $lines.Length; $index++) {
            if (-not $found -and $lines[$index] -match '^\s*music_root\s*=') {
                $lines[$index] = "music_root = $resolvedMusicRoot"
                $found = $true
            }
        }
        if (-not $found) {
            throw 'No se encontro music_root en config.ini.'
        }

        $utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
        $content = ($lines -join [Environment]::NewLine) + [Environment]::NewLine
        [System.IO.File]::WriteAllText($ConfigFile, $content, $utf8NoBom)
        Write-Host "Discoteca configurada: $resolvedMusicRoot"
    }

    Invoke-Checked -FilePath $VenvPython -ArgumentList @('-c', 'import playlist_builder')

    Write-Host ''
    Write-Host 'Instalacion completada.'
    Write-Host 'Ejecute: .\crear-playlist.cmd'
    Write-Host "Entorno virtual: $VenvDir"
    Write-Host "Configuracion: $ConfigFile"
}
finally {
    Pop-Location
}
