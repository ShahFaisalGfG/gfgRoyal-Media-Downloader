#Requires -Version 5.1
<#
.SYNOPSIS
    Register (or remove) the companion browser extension's native-messaging host.
.DESCRIPTION
    Writes the host manifest next to the host exe and points each Chromium browser's
    NativeMessagingHosts key at it, so the extension can reach gfgRoyal Media Downloader. The
    per-user installer registers for the current user (HKCU); the all-users installer registers for
    every user (HKLM). Only the listed extension may connect.
.EXAMPLE
    ./register-companion-host.ps1 -HostExe "C:\Program Files\gfgRoyal Media Downloader\gfgRoyal-Media-Downloader-host.exe" -ExtensionId gipopofnfbdhmmkpeaffnjfkkdbnjepp -Scope Machine
.EXAMPLE
    ./register-companion-host.ps1 -HostExe "...\gfgRoyal-Media-Downloader-host.exe" -Scope User -Unregister
#>
param(
    [Parameter(Mandatory)] [string]$HostExe,
    [string]$ExtensionId,
    [ValidateSet("User", "Machine")] [string]$Scope = "User",
    [string]$ManifestDir,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$HostName = "com.gfgroyal.mediadownloader"
$Hive = if ($Scope -eq "Machine") { "HKLM:" } else { "HKCU:" }

# The registry locations the Chromium browsers read native-messaging host manifests from.
$BrowserKeys = @(
    "Software\Google\Chrome\NativeMessagingHosts",
    "Software\Microsoft\Edge\NativeMessagingHosts",
    "Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    "Software\Opera Software\NativeMessagingHosts",
    "Software\Vivaldi\NativeMessagingHosts"
)

if (-not $ManifestDir) { $ManifestDir = Split-Path -Parent $HostExe }
$ManifestPath = Join-Path $ManifestDir "$HostName.json"

if ($Unregister) {
    foreach ($key in $BrowserKeys) {
        $path = "$Hive\$key\$HostName"
        if (Test-Path $path) { Remove-Item $path -Force }
    }
    if (Test-Path $ManifestPath) { Remove-Item $ManifestPath -Force }
    Write-Host "Removed the companion host registration."
    return
}

if ($ExtensionId -notmatch '^[a-p]{32}$') { throw "ExtensionId must be the 32-letter id the browser shows for the extension." }

$manifest = [ordered]@{
    name            = $HostName
    description     = "gfgRoyal Media Downloader companion bridge"
    path            = $HostExe
    type            = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $ManifestPath -Encoding UTF8

foreach ($key in $BrowserKeys) {
    $path = "$Hive\$key\$HostName"
    New-Item -Path $path -Force | Out-Null
    Set-ItemProperty -Path $path -Name "(default)" -Value $ManifestPath
}
Write-Host "Registered the companion host for $ExtensionId ($Scope)."
