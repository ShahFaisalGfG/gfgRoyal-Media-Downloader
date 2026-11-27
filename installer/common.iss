; =======================================================
; gfgRoyal Media Downloader Windows installers - the parts both share
; Included by gfgmd_system_installer.iss (all users) and
; gfgmd_user_installer.iss (current user). The build scripts
; pass the app metadata from pyproject.toml as /D definitions;
; the defaults below apply when a script is compiled by hand.
; Each installer defines PathRoot, PathKey, and HostScope before
; including this file.
; =======================================================

#ifndef MyAppName
  #define MyAppName "gfgRoyal Media Downloader"
#endif
#ifndef MyFileName
  #define MyFileName "gfgRoyal-Media-Downloader"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.2.0"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "gfgRoyal"
#endif
#ifndef MyAppURL
  #define MyAppURL "https://shahfaisalgfg.github.io/"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "gfgRoyal-Media-Downloader.exe"
#endif
; The companion browser extension's id, fixed by the key in companion\wxt.config.ts.
#ifndef MyExtId
  #define MyExtId "gipopofnfbdhmmkpeaffnjfkkdbnjepp"
#endif

; Written with Inno Setup's "{{" escape for an opening brace, as section values need it; [Code]
; reads it through ExpandConstant. The system and per-user installers share this AppId, so only one
; of them can be installed at a time (each installer's [Code] enforces that).
#define AppGuid "{{38D0A3E6-3C48-44F6-AFC6-9935783C8122}"

; Held by the app while it runs (gfgmd\utils\single_instance.py mutex names)
#define AppMutexes "gfgRoyalMediaDownloaderAppMutex,Global\gfgRoyalMediaDownloaderAppMutex"

#define SourceDir "..\dist\" + MyFileName
#define IconsDir "..\gfgmd\assets\icons"
#define IconName MyFileName + ".ico"
#define HostExe MyFileName + "-host.exe"
#define RepoUrl "https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader"
; The installer's connection choices, which the app applies at its next start
; (gfgmd\utils\install_choices.py reads them; HKA is HKLM for all users, HKCU for one).
#define ChoicesKey "Software\" + MyAppName + "\Install"

[Setup]
AppId={#AppGuid}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#RepoUrl}
AppUpdatesURL={#RepoUrl}/releases
; The setup exe's version details: the app's name and version, as code signing requires.
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoCopyright=Copyright (c) 2026 Shah Faisal
; The privacy policy, shown before installing: every connection the app makes, and how to turn off
; the ones it makes on its own (the choices below).
InfoBeforeFile=..\PRIVACY.md

; One folder in the Start menu, without a page to rename it
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\build\installer
SetupIconFile={#IconsDir}\{#IconName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110,120
; The "Add the gfgmd command to PATH" task changes the environment.
ChangesEnvironment=yes
; Tells Explorer to reload icons once Setup or Uninstall is done, so the Start menu and taskbar
; show a new version's icon instead of the one Windows cached (in-app updates run this installer too).
ChangesAssociations=yes

; PySide6 6.11 needs a 64-bit PC with Windows 10 version 1809 or later.
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763

; The app holds both mutexes while it runs, so Setup and Uninstall ask the user to close it
; rather than ending every running copy in all sessions.
AppMutex={#AppMutexes}
; A fresh uninstall log each install. [InstallDelete] clears the old bundle first, so the new log
; covers every program file.
UninstallLogMode=overwrite
; Only the app's own programs can hold a file Setup replaces, so Setup offers to close just them.
CloseApplicationsFilter=*.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add the gfgmd command to PATH (download from any terminal)"; GroupDescription: "Command line:"; Flags: unchecked
Name: "companion"; Description: "Connect the companion browser extension (Chrome, Edge, Brave, Opera, Vivaldi)"; GroupDescription: "Browser:"
; Clearing one turns that connection off at the app's next start; Preferences turns it back on.
Name: "updatecheck"; Description: "Check GitHub for app updates once a day"; GroupDescription: "Connections the app makes on its own (see the privacy policy):"
Name: "toolupdates"; Description: "Keep the download tools (yt-dlp, FFmpeg, Deno, gallery-dl, spotDL) up to date from GitHub and Codeberg"; GroupDescription: "Connections the app makes on its own (see the privacy policy):"
Name: "lyricsonline"; Description: "Look up song lyrics on LRCLIB (lrclib.net) when a site has none"; GroupDescription: "Connections the app makes on its own (see the privacy policy):"

[Files]
; The app bundle from scripts\bundle.ps1, with gfgmd.exe and the companion's host beside the app.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#IconsDir}\{#IconName}"; DestDir: "{app}\icons"; Flags: ignoreversion
; The companion native-messaging host registration script (the host exe ships inside the bundle above).
Source: "..\scripts\register-companion-host.ps1"; DestDir: "{app}\companion"; Flags: ignoreversion
; Documentation and the licence texts of every bundled component
Source: "..\README.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\PRIVACY.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}\docs"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#IconsDir}\Square150x150Logo.scale-100.png"; DestDir: "{app}\docs\icons"; Flags: ignoreversion

[InstallDelete]
; Remove the previous version's bundled runtime before copying the new one. Files a newer build no
; longer ships would otherwise stay behind and can break imports at startup. Only bundled program
; files live in _internal; settings, the library, and the download tools live in the user's data
; folders and are kept.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\docs"

[Registry]
; The gfgmd command: the install folder joins PATH when the task is chosen (removed on uninstall).
Root: {#PathRoot}; Subkey: "{#PathKey}"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))
; The connection choices: 1 keeps a connection on, 0 turns it off.
Root: HKA; Subkey: "{#ChoicesKey}"; Flags: uninsdeletekey
Root: HKA; Subkey: "{#ChoicesKey}"; ValueType: dword; ValueName: "UpdateChecks"; ValueData: 1; Tasks: updatecheck
Root: HKA; Subkey: "{#ChoicesKey}"; ValueType: dword; ValueName: "UpdateChecks"; ValueData: 0; Tasks: not updatecheck
Root: HKA; Subkey: "{#ChoicesKey}"; ValueType: dword; ValueName: "ToolUpdates"; ValueData: 1; Tasks: toolupdates
Root: HKA; Subkey: "{#ChoicesKey}"; ValueType: dword; ValueName: "ToolUpdates"; ValueData: 0; Tasks: not toolupdates
Root: HKA; Subkey: "{#ChoicesKey}"; ValueType: dword; ValueName: "OnlineLyrics"; ValueData: 1; Tasks: lyricsonline
Root: HKA; Subkey: "{#ChoicesKey}"; ValueType: dword; ValueName: "OnlineLyrics"; ValueData: 0; Tasks: not lyricsonline

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icons\{#IconName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icons\{#IconName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{#RepoUrl}"; Description: "View README on GitHub"; Flags: shellexec nowait postinstall skipifsilent unchecked
; Let the companion browser extension reach the app (Chrome, Edge, Brave, Opera, Vivaldi), or take
; an earlier install's connection away when the choice is cleared.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\companion\register-companion-host.ps1"" -HostExe ""{app}\{#HostExe}"" -ExtensionId ""{#MyExtId}"" -Scope {#HostScope}"; Flags: runhidden; StatusMsg: "Connecting the companion browser extension"; Tasks: companion
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\companion\register-companion-host.ps1"" -HostExe ""{app}\{#HostExe}"" -Scope {#HostScope} -Unregister"; Flags: runhidden; Tasks: not companion

[UninstallRun]
; Remove the companion host manifest and its browser registry keys before the files are deleted.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\companion\register-companion-host.ps1"" -HostExe ""{app}\{#HostExe}"" -Scope {#HostScope} -Unregister"; Flags: runhidden; RunOnceId: "UnregisterCompanionHost"

[UninstallDelete]
; The manifest the registration script writes at runtime is not tracked by Setup; drop the folder.
Type: filesandordirs; Name: "{app}\companion"

#include "update_support.iss"

[Code]
const
  UninstallKeys = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\';

// The uninstall entry of this AppId.
function CurrentUninstallKey(): String;
begin
  Result := UninstallKeys + ExpandConstant('{#AppGuid}') + '_is1';
end;

// True when the app is installed under RootKey: HKLM for all users, HKCU for the current user.
function InstallExists(const RootKey: Integer): Boolean;
begin
  Result := RegKeyExists(RootKey, CurrentUninstallKey());
end;

// True when Folder is not already on PATH (compared without case and trailing backslashes).
function NeedsAddPath(Folder: String): Boolean;
var
  Paths: String;
begin
  if not RegQueryStringValue({#PathRoot}, '{#PathKey}', 'Path', Paths) then
  begin
    Result := True;
    Exit;
  end;
  Result := Pos(';' + Uppercase(RemoveBackslashUnlessRoot(Folder)) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

// Takes the install folder back off PATH when the app is uninstalled.
procedure RemoveFromPath(Folder: String);
var
  Paths, Entry, Kept: String;
  Separator: Integer;
begin
  if not RegQueryStringValue({#PathRoot}, '{#PathKey}', 'Path', Paths) then
    Exit;
  Kept := '';
  Paths := Paths + ';';
  while Length(Paths) > 0 do
  begin
    Separator := Pos(';', Paths);
    Entry := Copy(Paths, 1, Separator - 1);
    Delete(Paths, 1, Separator);
    if (Entry <> '') and (CompareText(RemoveBackslashUnlessRoot(Entry), RemoveBackslashUnlessRoot(Folder)) <> 0) then
    begin
      if Kept <> '' then
        Kept := Kept + ';';
      Kept := Kept + Entry;
    end;
  end;
  RegWriteExpandStringValue({#PathRoot}, '{#PathKey}', 'Path', Kept);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
