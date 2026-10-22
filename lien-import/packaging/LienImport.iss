; Inno Setup script for the Lien Import installer.
; Built by ..\build-installer.bat - do not run by hand unless the PyInstaller
; output (..\build\pyinstaller\dist\LienImport) already exists.
;
; Per-user install (no admin rights needed), desktop + Start menu icon,
; uninstall entry in "Apps". User data in Documents\Lien Import is NEVER
; removed by the uninstaller.

#define AppName "Lien Import"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "LienImport.exe"

[Setup]
AppId={{7C1E5B9A-3F42-4E0B-9D6A-2B8E41C7A3F5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=LienImport-Setup-{#AppVersion}
SetupIconFile=lien-import.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put a Lien Import icon on the desktop"; GroupDescription: "Shortcuts:"

[InstallDelete]
; an upgrade replaces the bundled runtime completely (no stale files)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\build\pyinstaller\dist\LienImport\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open Lien Import now"; Flags: nowait postinstall skipifsilent
