#Requires -Version 7.2
# bundle.ps1 - PyInstaller builds, the bundle self-test, and the portable archive, shared by every
# build script and the release workflow so local and CI builds package and verify the same files.
# Dot-source it: . "$PSScriptRoot\bundle.ps1" (it loads common.ps1 too)

. "$PSScriptRoot\common.ps1"

$SelfTestTimeoutSec = 180
$AppIcon = "gfgRoyal-Media-Downloader.ico"
# Written next to the exe so a one-folder build keeps its settings, library, and tools in a
# "gfgRoyal Media Downloader data" folder beside itself instead of in %APPDATA% and %LOCALAPPDATA%.
$PortableMarkerName = "gfgRoyal-Media-Downloader-portable.txt"
$PortableMarkerText = @"
Settings, the library, sign-ins, and the download tools for this copy of gfgRoyal Media Downloader
stay in the "gfgRoyal Media Downloader data" folder next to gfgRoyal-Media-Downloader.exe.
Delete this file to keep them in %APPDATA% and %LOCALAPPDATA% instead.
"@

function New-VersionFile {
    <#
    .SYNOPSIS
        Writes an exe's version details for PyInstaller and returns the file's path.
    .DESCRIPTION
        Every exe the build makes carries the app's name as its product name and the version from
        pyproject.toml (read_meta.py writes them), which code signing requires; the description
        names the exe in Task Manager and in its Properties.
    #>
    param(
        [Parameter(Mandatory)] [string]$Exe,
        [Parameter(Mandatory)] [string]$Description
    )
    $root = Split-Path -Parent $PSScriptRoot
    $path = "$root\build\pyinstaller\$Exe.version.txt"
    python (Join-Path $PSScriptRoot "read_meta.py") --version-file $path --exe $Exe --description $Description
    if ($LASTEXITCODE -ne 0) { Fail "Could not write the version details of $Exe.exe (exit $LASTEXITCODE)" }
    return $path
}

function Get-PyInstallerArgs {
    <#
    .SYNOPSIS
        Returns the PyInstaller arguments for a onedir (installer) or onefile (portable) build.
    #>
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [ValidateSet("onedir", "onefile")] [string]$Mode,
        [Parameter(Mandatory)] [string]$DistPath
    )
    $root = Split-Path -Parent $PSScriptRoot
    $pyArgs = @(
        "--name",      $Name,
        "--windowed",
        "--$Mode",
        "--icon",      "$root\gfgmd\assets\icons\$AppIcon",
        "--version-file", (New-VersionFile -Exe $Name -Description (Get-AppMeta).AppName),
        # The Qt modules the app loads; the project hooks trim each to what the app uses.
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtNetwork",
        "--hidden-import", "PySide6.QtQml",
        "--hidden-import", "PySide6.QtQuick",
        "--hidden-import", "PySide6.QtQuickControls2",
        "--hidden-import", "PySide6.QtMultimedia",
        # Project hooks trim Qt to what the app uses (see each file in hooks\).
        "--additional-hooks-dir", "$root\hooks",
        "--runtime-hook", "$root\hooks\pyi_rth_qt_dll_dirs.py",
        "--add-data",  "$root\gfgmd\qml;gfgmd\qml",
        "--add-data",  "$root\gfgmd\assets;gfgmd\assets",
        "--distpath",  $DistPath,
        "--workpath",  "$root\build\pyinstaller",
        "--specpath",  "$root\build\pyinstaller",
        "--noconfirm",
        "--clean"
    )
    if ($Mode -eq "onefile") {
        # A one-file exe carries the licence texts inside; the installers and the portable .7z
        # ship them as files next to the app instead.
        $pyArgs += "--add-data", "$root\LICENSE;."
        $pyArgs += "--add-data", "$root\THIRD_PARTY_NOTICES.md;."
    }
    return $pyArgs + "$root\gfgmd\__main__.py"
}

function Test-Bundle {
    <#
    .SYNOPSIS
        Runs a built exe with --self-test, prints its report, and returns $true when every check passed.
    .DESCRIPTION
        The exe is a --windowed build with no console, so the report is read from a file. A build
        that hangs (for example on a startup error dialog) is stopped after $SelfTestTimeoutSec.
    #>
    param([Parameter(Mandatory)] [string]$ExePath)

    $report = Join-Path ([IO.Path]::GetTempPath()) "gfgmd_self_test_$PID.txt"
    Remove-Item $report -Force -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $ExePath -ArgumentList "--self-test", "`"$report`"" -PassThru
    $null = $proc.Handle  # cache the handle so ExitCode is available after WaitForExit
    if (-not $proc.WaitForExit($SelfTestTimeoutSec * 1000)) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "   Self-test did not finish within $SelfTestTimeoutSec s" -ForegroundColor Red
        return $false
    }
    if (Test-Path $report) {
        Get-Content $report | ForEach-Object { Write-Host "   $_" }
        Remove-Item $report -Force
    } else {
        Write-Host "   The self-test wrote no report (exit $($proc.ExitCode))" -ForegroundColor Red
    }
    return $proc.ExitCode -eq 0
}

function New-AppBundle {
    <#
    .SYNOPSIS
        Builds the app with PyInstaller, runs the result's --self-test, and returns the exe path.
    .DESCRIPTION
        onedir builds <DistPath>\<Name>\<Name>.exe (used by the installers and the portable .7z);
        onefile builds <DistPath>\<Name>.exe. Earlier output of the same build is removed first.
    #>
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [ValidateSet("onedir", "onefile")] [string]$Mode,
        [Parameter(Mandatory)] [string]$DistPath,
        # Local staging builds only: the test update server (http://127.0.0.1:<port>) and the
        # public key (PEM file) its manifests are signed with. Release builds never pass these.
        [string]$UpdateFeed = "",
        [string]$UpdateKeyFile = ""
    )
    $root = Split-Path -Parent $PSScriptRoot
    $staging = "$root\gfgmd\config\update_staging.py"
    if ($UpdateFeed) {
        if ($UpdateFeed -notmatch '^http://127\.0\.0\.1:\d{2,5}$') { Fail "-UpdateFeed must be http://127.0.0.1:<port>" }
        if (-not (Test-Path $UpdateKeyFile)) { Fail "-UpdateFeed needs -UpdateKeyFile with the test feed's public key" }
        $key = (Get-Content $UpdateKeyFile -Raw).Trim()
        Set-Content -Path $staging -Encoding utf8NoBOM -Value @"
# Written by scripts\bundle.ps1 -UpdateFeed for a local staging build; never commit or release it.
BASE_URL = "$UpdateFeed"
PUBLIC_KEYS = ("""$key
""",)
"@
        Write-Host "   Staging build: updates come from $UpdateFeed" -ForegroundColor Yellow
    } elseif (Test-Path $staging) {
        Fail "$staging is left from a staging build; delete it first."
    }
    $output = if ($Mode -eq "onedir") { Join-Path $DistPath $Name } else { Join-Path $DistPath "$Name.exe" }
    $exe = if ($Mode -eq "onedir") { Join-Path $output "$Name.exe" } else { $output }
    foreach ($path in @($output, "$root\build\pyinstaller\$Name")) {
        if (Test-Path $path) {
            Remove-Item $path -Recurse -Force
            Write-Host "   Removed $path" -ForegroundColor DarkGray
        }
    }

    Write-Step "Running PyInstaller for $Name ($Mode, this may take several minutes)"
    $pyinstaller = (Get-Command pyinstaller -ErrorAction Stop).Source
    $pyArgs = Get-PyInstallerArgs -Name $Name -Mode $Mode -DistPath $DistPath
    try {
        & $pyinstaller @pyArgs | Out-Host
        $exitCode = $LASTEXITCODE
    } finally {
        if ($UpdateFeed) { Remove-Item $staging -Force -ErrorAction SilentlyContinue }
    }
    if ($exitCode -ne 0) { Fail "PyInstaller failed (exit $exitCode). Check output above." }
    if (-not (Test-Path $exe)) { Fail "Expected executable not found: $exe" }
    $sizeMb = [math]::Round((Get-ChildItem $output -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host "   Built $output ($sizeMb MB)" -ForegroundColor DarkGray

    Write-Step "Verifying $Name starts and loads every QML module"
    if (-not (Test-Bundle $exe)) {
        Fail "Self-test failed for $exe - a module, DLL, or data file is missing from the build. See the report above."
    }
    return $exe
}

function New-ConsoleExe {
    <#
    .SYNOPSIS
        Builds a small console exe with no Qt into a bundle folder: the command-line tool or the
        companion's native-messaging host.
    .DESCRIPTION
        gfgmd.exe is the command-line tool (the installers can add its folder to PATH).
        gfgRoyal-Media-Downloader-host.exe is started by the browser for the companion extension and
        hands its requests to the running app. Both are one file, placed beside the app's exe in the
        onedir bundle so the installers ship them, and neither includes Qt. -Skill bundles the
        repository's skills\<name> folder, which `<name> skill install` copies for AI coding agents.
    #>
    param(
        [Parameter(Mandatory)] [string]$BundleDir,
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$Entry,
        [Parameter(Mandatory)] [string]$Description,
        [switch]$Skill
    )
    $root = Split-Path -Parent $PSScriptRoot
    Write-Step "Building $Name"
    $pyinstaller = (Get-Command pyinstaller -ErrorAction Stop).Source
    $pyArgs = @(
        "--name",      $Name,
        "--console",
        "--onefile",
        "--icon",      "$root\gfgmd\assets\icons\$AppIcon",
        "--version-file", (New-VersionFile -Exe $Name -Description $Description),
        "--exclude-module", "PySide6",
        "--exclude-module", "shiboken6",
        "--paths",     $root,
        "--distpath",  $BundleDir,
        "--workpath",  "$root\build\pyinstaller",
        "--specpath",  "$root\build\pyinstaller",
        "--noconfirm", "--clean"
    )
    if ($Skill) {
        $skillDir = "$root\skills\$Name"
        if (-not (Test-Path "$skillDir\SKILL.md")) { Fail "The $Name skill is missing: $skillDir\SKILL.md" }
        $pyArgs += @("--add-data", "$skillDir;skills\$Name")
    }
    $pyArgs += "$root\$Entry"
    & $pyinstaller @pyArgs | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed for $Name (exit $LASTEXITCODE)." }
    $exe = Join-Path $BundleDir "$Name.exe"
    if (-not (Test-Path $exe)) { Fail "Console exe not found: $exe" }
    Write-Host "   Built $exe ($(Get-SizeMb $exe) MB)" -ForegroundColor DarkGray
    return $exe
}

function New-ConsoleExes {
    <#
    .SYNOPSIS
        Builds the command-line tool and the native host beside the app, and checks the tool runs.
    #>
    param([Parameter(Mandatory)] [string]$BundleDir)
    $app = (Get-AppMeta).AppName
    $cli = New-ConsoleExe -BundleDir $BundleDir -Name "gfgmd" -Entry "gfgmd\cli.py" -Description "$app command line" -Skill
    $version = & $cli --version
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^gfgmd \d+\.\d+\.\d+$') { Fail "gfgmd.exe --version failed: $version" }
    $skill = & $cli skill show --json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or -not $skill.files.'SKILL.md') { Fail "gfgmd.exe doesn't carry its agent skill" }
    Write-Host "   $version, with its agent skill" -ForegroundColor DarkGray
    New-ConsoleExe -BundleDir $BundleDir -Name "gfgRoyal-Media-Downloader-host" -Entry "gfgmd\host_entry.py" `
        -Description "$app browser extension connector" | Out-Null
}

function New-PortableArchive {
    <#
    .SYNOPSIS
        Packs a onedir bundle as the portable .7z, with its licences and the portable marker.
    .DESCRIPTION
        The marker file next to the exe makes that copy keep its data in a
        "gfgRoyal Media Downloader data" folder beside itself.
    #>
    param(
        [Parameter(Mandatory)] [string]$BundleDir,
        [Parameter(Mandatory)] [string]$ArchivePath
    )
    $root = Split-Path -Parent $PSScriptRoot
    $command = Get-Command 7z -ErrorAction SilentlyContinue
    $sevenZip = if ($command) { $command.Source } else { "$env:ProgramFiles\7-Zip\7z.exe" }
    if (-not (Test-Path $sevenZip)) { Fail "7-Zip not found (looked for 7z on PATH and $sevenZip)" }

    $extras = Join-Path $root "build\portable-extras"
    if (Test-Path $extras) { Remove-Item $extras -Recurse -Force }
    New-Item -ItemType Directory -Path $extras | Out-Null
    Copy-Item "$root\LICENSE" "$extras\LICENSE.txt"
    Copy-Item "$root\THIRD_PARTY_NOTICES.md" $extras
    Set-Content -Path "$extras\$PortableMarkerName" -Value $PortableMarkerText

    if (Test-Path $ArchivePath) { Remove-Item $ArchivePath -Force }
    & $sevenZip a -t7z -mx=9 $ArchivePath "$BundleDir\*" "$extras\*" | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "7-Zip failed (exit $LASTEXITCODE) for $ArchivePath" }
    Write-Host "   Packed $ArchivePath ($(Get-SizeMb $ArchivePath) MB)" -ForegroundColor DarkGray
}
