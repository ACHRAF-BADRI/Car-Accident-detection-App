; Windows installer for AccidentAI (Inno Setup 6).
; Build the app first (packaging/AccidentAI.spec), then:
;     ISCC packaging\installer.iss /DAppVersion=1.0.0
; Output: dist\AccidentAI-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "AccidentAI"
#define AppExe "AccidentAI.exe"

[Setup]
AppId={{7C1E4A3B-9D2F-4E8A-B6C5-2F0D8A1E9B47}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Achraf El Badri
AppPublisherURL=https://achraf-badri.github.io/Car-Accident-detection-App/
AppSupportURL=https://github.com/ACHRAF-BADRI/Car-Accident-detection-App
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; No administrator rights needed: installs for the current user (can be switched to all users)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\images\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AccidentAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; User data (%APPDATA%\AccidentAI: settings, snapshots, recordings) is kept on uninstall.
