#Requires -Version 7.2
<#
.SYNOPSIS
    Full build: both installers and the portable exe.
.DESCRIPTION
    Step 1 - PyInstaller : the app bundle in dist\gfgRoyal-Media-Downloader\, then its --self-test,
                           and gfgmd.exe plus the companion's host beside it
    Step 2 - Inno Setup  : the system and per-user installers in build\installer\
    Step 3 - Portable    : the single-file exe in build\, then its --self-test
.NOTES
    Requirements: PowerShell 7.2+, the venv from requirements.txt, and Inno Setup 6
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\bundle.ps1"

$BuildStart = Get-Date
Set-Location (Split-Path -Parent $PSScriptRoot)

Enable-Venv
Assert-BuildTools -Installer
$Meta = Get-AppMeta

$null = New-AppBundle -Name $Meta.FileName -Mode onedir -DistPath "dist"
New-ConsoleExes -BundleDir (Join-Path "dist" $Meta.FileName)

Write-Step "Compiling installers with Inno Setup"
$Installers = foreach ($Kind in "System", "User") {
    $Start = Get-Date
    $Path = Invoke-Iscc -Kind $Kind -Meta $Meta
    [pscustomobject]@{ Path = $Path; Elapsed = (Get-Date) - $Start }
}

$PortableStart = Get-Date
$PortableExe = New-AppBundle -Name "$($Meta.FileName)_$($Meta.Version)_portable" -Mode onefile -DistPath "build"
$PortableElapsed = (Get-Date) - $PortableStart

Write-Host ""
Write-Host "Build complete in $(Format-Elapsed ((Get-Date) - $BuildStart))." -ForegroundColor Green
foreach ($Installer in $Installers) {
    Write-Host "Installer    : $($Installer.Path)  ($(Get-SizeMb $Installer.Path) MB)  ($(Format-Elapsed $Installer.Elapsed))" -ForegroundColor Green
}
Write-Host "Portable Exe : $PortableExe  ($(Get-SizeMb $PortableExe) MB)  ($(Format-Elapsed $PortableElapsed))" -ForegroundColor Green
