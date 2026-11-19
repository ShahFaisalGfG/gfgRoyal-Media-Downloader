#Requires -Version 7.2
<#
.SYNOPSIS
    Build the gfgRoyal Media Downloader system-wide or per-user Windows installer.
.DESCRIPTION
    Step 1 - PyInstaller : the app bundle in dist\gfgRoyal-Media-Downloader\, then its --self-test,
                           and gfgmd.exe plus the companion's host beside it
    Step 2 - Inno Setup  : build\installer\gfgRoyal-Media-Downloader_<version>_<kind>_installer.exe
.PARAMETER Kind
    System installs for all users into Program Files (needs admin rights); User installs for
    the current user into %LOCALAPPDATA%\Programs (no admin rights).
.NOTES
    Requirements: PowerShell 7.2+, the venv from requirements.txt, and Inno Setup 6
#>

param(
    [Parameter(Mandatory)] [ValidateSet("User", "System")] [string]$Kind
)

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

Write-Step "Compiling the $($Kind.ToLowerInvariant()) installer with Inno Setup"
$Installer = Invoke-Iscc -Kind $Kind -Meta $Meta

Write-Host ""
Write-Host "Build complete in $(Format-Elapsed ((Get-Date) - $BuildStart))." -ForegroundColor Green
Write-Host "Installer : $Installer  ($(Get-SizeMb $Installer) MB)" -ForegroundColor Green
