; Instalador de escritorio de Hypazo. Por dentro ejecuta el mismo install.ps1 que la línea de terminal.
; Lo compila GitHub Actions (.github/workflows/release.yml) al publicar una etiqueta v*:
;   ISCC.exe /DVersion=v0.1.0 installer\hypazo.iss

#ifndef Version
  #define Version "dev"
#endif

[Setup]
SetupIconFile=..\assets\hypazo.ico
UninstallDisplayIcon={localappdata}\hypazo\hypazo\assets\hypazo.ico
AppId={{6B3F2C1E-8D4A-4E5B-9C7F-1A2B3C4D5E6F}
AppName=Hypazo
AppVersion={#Version}
AppPublisher=Hypazo
AppPublisherURL=https://github.com/Luisdanielfz/hypazo
DefaultDirName={localappdata}\hypazo\instalador
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Hypazo-Setup-{#Version}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Hypazo
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
es.WelcomeLabel2=Se instalará Hypazo en tu usuario, sin permisos de administrador.%n%nEl instalador descarga lo que necesita (unos 400 MB) y tarda unos minutos. Tus clips se guardan en Vídeos\Hypazo y nunca se borran al desinstalar.

[Files]
Source: "..\install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "desinstalar.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -NonInteractive"; StatusMsg: "Instalando Hypazo: descargando herramientas y dependencias (unos minutos)..."; Flags: waituntilterminated
Filename: "{localappdata}\hypazo\hypazo\.venv\Scripts\pythonw.exe"; Parameters: """{localappdata}\hypazo\hypazo\hypazo.py"" start"; Description: "Abrir Hypazo"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\desinstalar.ps1"""; RunOnceId: "QuitarHypazo"; Flags: runhidden waituntilterminated
