; =======================================================
; gfgRoyal Media Downloader Windows installer for all users (needs admin rights)
; Inno Setup script. The parts it shares with the per-user
; installer are in common.iss.
; =======================================================

#define PathRoot "HKLM"
#define PathKey "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
#define HostScope "Machine"
#include "common.iss"

[Setup]
PrivilegesRequired=admin
DefaultDirName={autopf}\{#MyAppName}
OutputBaseFilename={#MyFileName}_{#MyAppVersion}_system_installer

[Registry]
; Where the per-user installer looks for a copy installed for all users
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}"; Flags: uninsdeletekeyifempty
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "ExePath"; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey

[UninstallDelete]
; Installed files are removed by the uninstaller itself. The folder goes only when it is empty, so
; installing into a folder that already held other files can never cost those files. Each user's
; settings, library, and sign-ins live in their own profile and are kept for a reinstall.
Type: dirifempty; Name: "{app}"

[Code]
var
  UserDataMoved: Boolean;

// This user's data folders, which the copy installed for all users reads too: Roaming holds the
// settings and logs, Local the library, sign-ins, and download tools.
function RoamingDir(): String;
begin
  Result := ExpandConstant('{userappdata}\{#MyAppName}');
end;

function LocalDir(): String;
begin
  Result := ExpandConstant('{localappdata}\{#MyAppName}');
end;

// Where a folder waits while the per-user copy is removed.
function KeptDir(const Dir: String): String;
begin
  Result := Dir + ' (kept by Setup)';
end;

// Moves a file or folder; True when it moved.
function MoveItem(const Source, Target: String): Boolean;
begin
  Result := False;
  if not FileExists(Source) and not DirExists(Source) then
    Exit;
  if FileExists(Target) or DirExists(Target) then
    Log('Left ' + Source + ' where it is: ' + Target + ' already exists')
  else if not ForceDirectories(ExtractFileDir(Target)) then
    Log('Could not create ' + ExtractFileDir(Target))
  else
  begin
    Result := RenameFile(Source, Target);
    if not Result then
      Log('Could not move ' + Source + ' to ' + Target);
  end;
end;

// The per-user uninstaller deletes this user's data, so it moves aside until that copy is gone.
procedure KeepUserData();
begin
  if MoveItem(RoamingDir() + '\settings.json', KeptDir(RoamingDir()) + '\settings.json') then
    UserDataMoved := True;
  if MoveItem(RoamingDir() + '\logs', KeptDir(RoamingDir()) + '\logs') then
    UserDataMoved := True;
  if MoveItem(LocalDir(), KeptDir(LocalDir())) then
    UserDataMoved := True;
end;

// Puts back what KeepUserData moved; a later call does nothing.
procedure RestoreUserData();
begin
  if not UserDataMoved then
    Exit;
  MoveItem(KeptDir(RoamingDir()) + '\settings.json', RoamingDir() + '\settings.json');
  MoveItem(KeptDir(RoamingDir()) + '\logs', RoamingDir() + '\logs');
  RemoveDir(KeptDir(RoamingDir()));
  MoveItem(KeptDir(LocalDir()), LocalDir());
  UserDataMoved := False;
end;

// Runs the uninstaller of the per-user entry Key silently; an entry whose uninstaller is gone is
// deleted instead. True when nothing failed.
function RunUserUninstaller(const Key: String): Boolean;
var
  UninstExe: String;
  ResultCode: Integer;
begin
  Result := True;
  if not RegQueryStringValue(HKCU, Key, 'UninstallString', UninstExe) then
    Exit;
  UninstExe := RemoveQuotes(UninstExe);
  if not FileExists(UninstExe) then
    RegDeleteKeyIncludingSubkeys(HKCU, Key)
  else if not Exec(UninstExe, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := False
  else
    Result := ResultCode = 0;
end;

// Removes the per-user copy; this user's data stays.
function RemoveUserInstall(): Boolean;
begin
  KeepUserData();
  Result := RunUserUninstaller(CurrentUninstallKey());
  if Result then
    Result := not InstallExists(HKCU);
end;

// The per-user copy is removed before Setup's own AppMutex check runs, so the app must be closed
// first: its uninstaller would fail on a running copy.
function AppClosed(): Boolean;
begin
  Result := True;
  while CheckForMutexes('{#AppMutexes}') do
    if SuppressibleMsgBox('{#MyAppName} is running. Close it (Quit in the tray menu), then click OK to continue.',
      mbError, MB_OKCANCEL, IDCANCEL) <> IDOK then
    begin
      Result := False;
      Exit;
    end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not InstallExists(HKCU) then
    Exit;
  if SuppressibleMsgBox(
    '{#MyAppName} is installed for your account only.' + #13#10#13#10 +
    'Click Yes to remove that copy and install it for all users. Your settings, library, sign-ins, and download tools are kept.' + #13#10 +
    'Click No to cancel, then update that copy with the per-user installer instead.',
    mbConfirmation, MB_YESNO, IDYES) = IDNO then
  begin
    Result := False;
    Exit;
  end;
  if not AppClosed() then
  begin
    Result := False;
    Exit;
  end;
  if not RemoveUserInstall() then
  begin
    RestoreUserData();
    SuppressibleMsgBox(
      'The copy of {#MyAppName} installed for your account could not be removed.' + #13#10#13#10 +
      'Uninstall it in Settings > Apps, then run this installer again.',
      mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RestoreUserData();
end;

procedure DeinitializeSetup();
begin
  RestoreUserData();
end;
