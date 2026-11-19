; =======================================================
; gfgRoyal Media Downloader Windows installer for the current user (no admin rights)
; Inno Setup script. The parts it shares with the all-users
; installer are in common.iss.
; =======================================================

#define PathRoot "HKCU"
#define PathKey "Environment"
#define HostScope "User"
#include "common.iss"

[Setup]
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
OutputBaseFilename={#MyFileName}_{#MyAppVersion}_user_installer

[UninstallDelete]
; Installed files are removed by the uninstaller itself. This user's settings and logs (Roaming)
; and the library, saved sign-ins, download tools, and caches (Local) go too; downloaded videos stay
; where they were saved. Folders go only when empty, so a folder that held other files keeps them.
Type: files; Name: "{userappdata}\{#MyAppName}\settings.json"
Type: files; Name: "{userappdata}\{#MyAppName}\settings.json.tmp"
Type: files; Name: "{userappdata}\{#MyAppName}\updates.json"
Type: filesandordirs; Name: "{userappdata}\{#MyAppName}\logs"
Type: dirifempty; Name: "{userappdata}\{#MyAppName}"
Type: filesandordirs; Name: "{localappdata}\{#MyAppName}"
Type: dirifempty; Name: "{app}"

[Code]
function SystemInstallExists(): Boolean;
var
  S: String;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\{#MyAppPublisher}\{#MyAppName}', 'InstallPath', S) or InstallExists(HKLM);
end;

function InitializeSetup(): Boolean;
begin
  Result := not SystemInstallExists();
  if not Result then
    SuppressibleMsgBox(
      '{#MyAppName} is already installed for all users on this PC.' + #13#10#13#10 +
      'Update it with the all-users (system) installer instead.',
      mbError, MB_OK, IDOK);
end;
