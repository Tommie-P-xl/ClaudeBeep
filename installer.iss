#define MyAppName "ClaudeBeep"
; 版本号默认值，构建时由 build.ps1 通过 /DMyAppVersion= 注入（M1）
#ifndef MyAppVersion
#define MyAppVersion "2.3.3"
#endif
#define MyAppExeName "ClaudeBeep.exe"

[Setup]
AppId={{B60D0E97-26DE-45A2-A843-1A3E541D7569}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=Output
OutputBaseFilename=ClaudeBeep-Setup-{#MyAppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
AppMutex=Global\ClaudeBeepTray

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "claudebeep_hook.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

; M7/S3：运行时数据（config.json/notify.log/pending 等）已迁移到 %APPDATA%\ClaudeBeep，
; 卸载时不再删除用户配置与日志（保留在用户数据目录，重装后配置自动沿用）。
[UninstallDelete]
Type: dirifempty; Name: "{app}\pending"
Type: dirifempty; Name: "{app}\responses"
Type: dirifempty; Name: "{app}\send_queue"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
