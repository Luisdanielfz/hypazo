# Hypazo: instalacion en una linea (mismas etapas que el instalador de Hermes Agent).
#
#   iex (irm https://raw.githubusercontent.com/Luisdanielfz/hypazo/main/install.ps1)
#
# Todo queda en %LOCALAPPDATA%\hypazo (o $env:HYPAZO_HOME), sin administrador:
#   pm\      uv, Git portatil y ffmpeg en versiones fijas, comprobadas con SHA-256
#   hypazo\  el codigo (git clone) y su entorno de Python (.venv, creado con uv)
#   bin\     el comando `hypazo`, anadido al PATH del usuario
# Los clips van a Videos\Hypazo y ni `hypazo update` ni el desinstalador los tocan.
#
# Opciones (con -File) o variables de entorno (las unicas posibles con `irm | iex`):
#   -NonInteractive / $env:HYPAZO_NONINTERACTIVE=1   sin preguntas (lo usa el .exe)
#   -Channel stable|main / $env:HYPAZO_INSTALL_CHANNEL   stable = ultima version publicada
#   -Manifest        imprime la lista de etapas en JSON
#   -Stage NOMBRE    ejecuta una sola etapa
#   $env:HYPAZO_REPO_URL   otro origen del codigo (pruebas)
param(
    [string]$HypazoHome = $(if ($env:HYPAZO_HOME) { $env:HYPAZO_HOME } else { Join-Path $env:LOCALAPPDATA "hypazo" }),
    [ValidateSet("stable", "main")]
    [string]$Channel = $(if ($env:HYPAZO_INSTALL_CHANNEL) { $env:HYPAZO_INSTALL_CHANNEL } else { "stable" }),
    [switch]$NonInteractive,
    [switch]$Manifest,
    [string]$Stage = ""
)

# Bajo `irm | iex` este texto corre en la sesion del usuario: `exit` le cerraria la ventana.
# Solo un archivo (-File) puede salir con codigo; se distingue porque iex no tiene ruta.
# Un bloque {} recuerda el archivo del que se leyo; el texto de iex no tiene ninguno.
$script:ArchivoPropio = {}.File
$script:EsArchivo = [bool]$script:ArchivoPropio
$script:Interactivo = -not ($NonInteractive -or $env:HYPAZO_NONINTERACTIVE -eq "1")
$script:RepoUrl = if ($env:HYPAZO_REPO_URL) { $env:HYPAZO_REPO_URL } else { "https://github.com/Luisdanielfz/hypazo.git" }
$script:Casa = $HypazoHome
$script:Pm = Join-Path $HypazoHome "pm"
$script:Codigo = Join-Path $HypazoHome "hypazo"
$script:Bin = Join-Path $HypazoHome "bin"
$script:Venv = Join-Path $script:Codigo ".venv"
$script:PythonVersion = "3.13"

# --- Versiones fijas (verificadas el 2026-11-22; las de uv y Git son las mismas que fija Hermes) ---
$script:Pins = @{
    uv = @{ Version = "0.13.5"
            Url = "https://github.com/astral-sh/uv/releases/download/0.13.5/uv-x86_64-pc-windows-msvc.zip"
            Sha256 = "a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a"
            Exe = "uv.exe" }
    git = @{ Version = "2.56.1"
             Url = "https://github.com/git-for-windows/git/releases/download/v2.56.1.windows.1/PortableGit-2.56.1-64-bit.7z.exe"
             Sha256 = "9dd04a608ceb5f6ab32a73709e0ecb159d211da71b697c45ff81f6dd0c6b49c7"
             Exe = "cmd\git.exe" }
    ffmpeg = @{ Version = "9.1"
                Url = "https://github.com/GyanD/codexffmpeg/releases/download/9.1/ffmpeg-9.1-essentials_build.zip"
                Sha256 = "b9bbbb3acece000cbeec994f856649354e52c773807841e78908374b24d658fd"
                Exe = "bin\ffmpeg.exe" }
}

$script:Stages = @(
    @{ name = "prerequisites"; title = "Herramientas (uv, Git, ffmpeg)"; needs_user_input = $false },
    @{ name = "repository"; title = "Descargar Hypazo"; needs_user_input = $false },
    @{ name = "venv"; title = "Crear el entorno de Python"; needs_user_input = $false },
    @{ name = "python-deps"; title = "Instalar dependencias de Python"; needs_user_input = $false },
    @{ name = "config"; title = "Preparar configuracion"; needs_user_input = $false },
    @{ name = "products"; title = "Publicar el comando hypazo"; needs_user_input = $false },
    @{ name = "setup"; title = "Configuracion guiada"; needs_user_input = $true },
    @{ name = "complete"; title = "Terminar"; needs_user_input = $false }
)

function Log([string]$msg) { Write-Host "-> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err([string]$msg) { Write-Host "[X] $msg" -ForegroundColor Red }
function Fail([string]$msg) { throw [System.Exception]::new($msg) }

function Write-Banner {
    Write-Host ""
    Write-Host "  Hypazo - instalacion" -ForegroundColor Magenta
    Write-Host "  $script:Casa" -ForegroundColor DarkGray
    Write-Host ""
}

function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$Que) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "$Que fallo (codigo $LASTEXITCODE)." }
}

function Get-Pin([string]$nombre) {
    $pin = $script:Pins[$nombre]
    $sha = $pin.Sha256
    if ($env:HYPAZO_TEST_BAD_SHA -eq $nombre) { $sha = "0" * 64 }   # solo pruebas: descarga "corrupta"
    return @{ Version = $pin.Version; Url = $pin.Url; Sha256 = $sha; Exe = $pin.Exe
              Dir = Join-Path (Join-Path $script:Pm $nombre) $pin.Version }
}

# SHA-256 con .NET: Get-FileHash vive en un modulo y falla si PowerShell 5.1 hereda la ruta de
# modulos de PowerShell 7 (pasa, por ejemplo, al lanzarlo desde pwsh o desde GitHub Actions).
function Get-Sha256([string]$Ruta) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $f = [IO.File]::OpenRead($Ruta)
    try { return (($sha.ComputeHash($f) | ForEach-Object { $_.ToString("x2") }) -join "") }
    finally { $f.Dispose(); $sha.Dispose() }
}

function Invoke-VerifiedDownload([string]$Url, [string]$Sha256, [string]$Destino, [string]$Nombre) {
    $parte = "$Destino.part"
    Remove-Item -LiteralPath $parte -Force -ErrorAction SilentlyContinue
    Log "Descargando $Nombre..."
    $prev = $ProgressPreference; $ProgressPreference = "SilentlyContinue"   # PS 5.1: la barra lo hace 10x mas lento
    try { Invoke-WebRequest -Uri $Url -OutFile $parte -UseBasicParsing }
    catch { Remove-Item -LiteralPath $parte -Force -ErrorAction SilentlyContinue; Fail "No se pudo descargar $Nombre ($($_.Exception.Message))." }
    finally { $ProgressPreference = $prev }
    $real = Get-Sha256 $parte
    if ($real -ne $Sha256.ToLowerInvariant()) {
        Remove-Item -LiteralPath $parte -Force -ErrorAction SilentlyContinue
        Fail "La descarga de $Nombre no coincide con su huella SHA-256 (esperada $Sha256, recibida $real). No se ha instalado nada de $Nombre."
    }
    Move-Item -LiteralPath $parte -Destination $Destino -Force
}

function Expand-Zip([string]$Zip, [string]$Destino) {
    New-Item -ItemType Directory -Force -Path $Destino | Out-Null
    $tar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (Test-Path -LiteralPath $tar) { & $tar -xf $Zip -C $Destino; if ($LASTEXITCODE -eq 0) { return } }
    Add-Type -AssemblyName System.IO.Compression.FileSystem   # sin depender del modulo Archive
    [IO.Compression.ZipFile]::ExtractToDirectory($Zip, $Destino)
}

function Install-Tool([string]$nombre) {
    $pin = Get-Pin $nombre
    $exe = Join-Path $pin.Dir $pin.Exe
    if (Test-Path -LiteralPath $exe) { Write-Ok "$nombre $($pin.Version) ya estaba"; return $exe }
    $tmp = Join-Path $script:Pm "_descargas"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $archivo = Join-Path $tmp ([IO.Path]::GetFileName($pin.Url))
    Invoke-VerifiedDownload $pin.Url $pin.Sha256 $archivo $nombre
    $temporal = "$($pin.Dir).tmp"
    Remove-Item -LiteralPath $temporal -Recurse -Force -ErrorAction SilentlyContinue
    if ($archivo.EndsWith(".7z.exe")) {
        # Git portatil es un 7z autoextraible: se descomprime solo, sin instalar nada.
        $p = Start-Process -FilePath $archivo -ArgumentList @("-y", "-o`"$temporal`"") -Wait -PassThru -WindowStyle Hidden
        if ($p.ExitCode -ne 0) { Fail "No se pudo extraer Git portatil (codigo $($p.ExitCode))." }
    } else {
        Expand-Zip $archivo $temporal
        $hijos = @(Get-ChildItem -LiteralPath $temporal)
        if ($hijos.Count -eq 1 -and $hijos[0].PSIsContainer) {     # zip con una carpeta raiz (ffmpeg)
            $interior = $hijos[0].FullName
            Rename-Item -LiteralPath $temporal -NewName ([IO.Path]::GetFileName($temporal) + "2")
            $temporal = "$temporal" + "2"
            $interior = Join-Path $temporal $hijos[0].Name
            Move-Item -LiteralPath $interior -Destination "$($pin.Dir).tmp"
            Remove-Item -LiteralPath $temporal -Recurse -Force
            $temporal = "$($pin.Dir).tmp"
        }
    }
    Remove-Item -LiteralPath $pin.Dir -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $temporal -Destination $pin.Dir
    Remove-Item -LiteralPath $archivo -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $exe)) { Fail "$nombre se extrajo, pero falta $($pin.Exe)." }
    Write-Ok "$nombre $($pin.Version)"
    return $exe
}

function Get-ToolExe([string]$nombre) {
    $pin = Get-Pin $nombre
    $exe = Join-Path $pin.Dir $pin.Exe
    if (-not (Test-Path -LiteralPath $exe)) { Fail "Falta ${nombre}: ejecuta antes la etapa prerequisites." }
    return $exe
}

function Set-ToolEnv {
    # uv guarda Python y su cache dentro de <home>: desinstalar no deja restos.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $script:Pm "python"
    $env:UV_CACHE_DIR = Join-Path $script:Pm "uv-cache"
    $gitDir = Split-Path (Get-ToolExe "git") -Parent
    $ffDir = Split-Path (Get-ToolExe "ffmpeg") -Parent
    if (-not ($env:Path -split ";" | Where-Object { $_ -eq $gitDir })) { $env:Path = "$gitDir;$ffDir;$env:Path" }
}

# --- Etapas ------------------------------------------------------------------
function Stage-Prerequisites {
    if ([Environment]::Is64BitOperatingSystem -eq $false -or $env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
        Fail "Hypazo necesita Windows de 64 bits (x64). Este equipo no esta soportado todavia."
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Force -Path $script:Pm | Out-Null
    foreach ($n in "uv", "git", "ffmpeg") { Install-Tool $n | Out-Null }
}

function Get-Target([string]$git) {
    if ($Channel -eq "main") { return "main" }
    $tags = & $git ls-remote --tags --refs --sort=-v:refname $script:RepoUrl "v*" 2>$null
    $ultima = $tags | Select-Object -First 1
    if ($ultima) { return ($ultima -split "refs/tags/")[1] }
    Write-Warn "Todavia no hay ninguna version publicada: instalo la rama main."
    return "main"
}

function Stage-Repository {
    Set-ToolEnv
    $git = Get-ToolExe "git"
    $destino = Get-Target $git
    if (Test-Path -LiteralPath (Join-Path $script:Codigo ".git")) {
        Log "Actualizando el codigo a $destino..."
        Invoke-Native $git @("-C", $script:Codigo, "fetch", "--tags", "--force", "origin") "git fetch"
        $ref = if ($destino -eq "main") { "origin/main" } else { $destino }
        Invoke-Native $git @("-C", $script:Codigo, "checkout", "--force", $ref) "git checkout"
    } else {
        if (Test-Path -LiteralPath $script:Codigo) {
            $roto = "$script:Codigo.roto-" + (Get-Date -Format "yyyyMMddHHmmss")
            Write-Warn "$script:Codigo no es un repositorio valido; lo aparto en $roto"
            Move-Item -LiteralPath $script:Codigo -Destination $roto
        }
        Log "Descargando Hypazo ($destino)..."
        Invoke-Native $git @("clone", "--depth", "1", "--branch", $destino, $script:RepoUrl, $script:Codigo) "git clone"
    }
    Write-Ok "codigo en $script:Codigo ($destino)"
}

function Stage-Venv {
    Set-ToolEnv
    $py = Join-Path $script:Venv "Scripts\python.exe"
    if (Test-Path -LiteralPath $py) { Write-Ok "entorno de Python ya estaba"; return }
    Invoke-Native (Get-ToolExe "uv") @("venv", "--python", $script:PythonVersion, $script:Venv) "uv venv"
    Write-Ok "entorno de Python $script:PythonVersion"
}

function Stage-PythonDeps {
    Set-ToolEnv
    $py = Join-Path $script:Venv "Scripts\python.exe"
    Log "Instalando dependencias (la primera vez tarda unos minutos)..."
    Invoke-Native (Get-ToolExe "uv") @("pip", "install", "--python", $py, "-r", (Join-Path $script:Codigo "requirements.txt")) "uv pip install"
    Write-Ok "dependencias de Python"
}

function Invoke-Hypazo([string[]]$Argumentos) {
    $env:HYPAZO_HOME = $script:Casa
    Set-ToolEnv
    # Out-Host: lo que imprime Python se ve, pero no se mezcla con el codigo de salida.
    & (Join-Path $script:Venv "Scripts\python.exe") (Join-Path $script:Codigo "hypazo.py") @Argumentos | Out-Host
    return $LASTEXITCODE
}

function Stage-Config {
    if (Test-Path -LiteralPath (Join-Path $script:Casa "config\config.json")) { Write-Ok "configuracion ya existia (se conserva)"; return }
    if ((Invoke-Hypazo @("setup", "--non-interactive")) -ne 0) { Fail "No se pudo crear la configuracion." }
    Write-Ok "configuracion"
}

function Set-LauncherUserPath([string]$binDir) {
    $actual = [Environment]::GetEnvironmentVariable("Path", "User")
    $partes = @($actual -split ";" | Where-Object { $_ })
    if (-not ($partes | Where-Object { $_.TrimEnd("\") -ieq $binDir.TrimEnd("\") })) {
        [Environment]::SetEnvironmentVariable("Path", (($partes + $binDir) -join ";"), "User")
        Write-Ok "anadido al PATH del usuario: $binDir"
    }
    if (-not ($env:Path -split ";" | Where-Object { $_ -ieq $binDir })) { $env:Path = "$binDir;$env:Path" }
}

function Stage-Products {
    New-Item -ItemType Directory -Force -Path $script:Bin | Out-Null
    $git = Get-Pin "git"; $ff = Get-Pin "ffmpeg"
    # Sin rutas escritas: todo sale de %~dp0 (la carpeta bin). Asi funciona aunque el usuario
    # tenga tildes o espacios en su nombre (cmd.exe leeria mal una ruta escrita en otra pagina de codigos).
    $cmd = @(
        "@echo off",
        "rem Generado por install.ps1 de Hypazo.",
        "setlocal",
        "for %%I in (`"%~dp0..`") do set `"HYPAZO_HOME=%%~fI`"",
        "set `"UV_PYTHON_INSTALL_DIR=%HYPAZO_HOME%\pm\python`"",
        "set `"UV_CACHE_DIR=%HYPAZO_HOME%\pm\uv-cache`"",
        "set `"PATH=%HYPAZO_HOME%\pm\git\$($git.Version)\cmd;%HYPAZO_HOME%\pm\ffmpeg\$($ff.Version)\bin;%PATH%`"",
        "`"%HYPAZO_HOME%\hypazo\.venv\Scripts\python.exe`" `"%HYPAZO_HOME%\hypazo\hypazo.py`" %*"
    ) -join "`r`n"
    [IO.File]::WriteAllText((Join-Path $script:Bin "hypazo.cmd"), $cmd + "`r`n", [Text.Encoding]::ASCII)
    Set-LauncherUserPath $script:Bin
    Write-Ok "comando hypazo"
}

function Stage-Setup {
    if (-not $script:Interactivo) { Write-Ok "configuracion guiada omitida (sin preguntas); hazla cuando quieras con: hypazo setup"; return }
    Invoke-Hypazo @("setup") | Out-Null
}

function New-Shortcut([string]$Ruta) {
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($Ruta)
    $lnk.TargetPath = Join-Path $script:Bin "hypazo.cmd"
    $lnk.WorkingDirectory = $script:Codigo
    $lnk.Description = "Hypazo: clips de directos de Twitch y Kick"
    $lnk.Save()
}

function Stage-Complete {
    if ($env:HYPAZO_NO_SHORTCUTS -ne "1") {
        New-Shortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "Hypazo.lnk")
        New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "Hypazo.lnk")
        Write-Ok "accesos directos en Inicio y en el escritorio"
    }
    Write-Host ""
    Write-Ok "Hypazo esta instalado."
    Write-Host "   Abrelo con el acceso directo o escribiendo: hypazo" -ForegroundColor Gray
    Write-Host "   Revisa la instalacion con: hypazo doctor" -ForegroundColor Gray
    Write-Host "   En otras terminales ya abiertas, reinicialas para que encuentren el comando." -ForegroundColor Gray
}

function Invoke-StageByName([string]$name) {
    switch ($name) {
        "prerequisites" { Stage-Prerequisites }
        "repository" { Stage-Repository }
        "venv" { Stage-Venv }
        "python-deps" { Stage-PythonDeps }
        "config" { Stage-Config }
        "products" { Stage-Products }
        "setup" { Stage-Setup }
        "complete" { Stage-Complete }
        default { Fail "Etapa desconocida: $name" }
    }
}

function Install-Hypazo {
    if ($Manifest) {
        Write-Host ($script:Stages | ForEach-Object { [pscustomobject]$_ } | ConvertTo-Json -Compress)
        $script:CodigoSalida = 0
        return
    }
    Write-Banner
    $lista = if ($Stage) { @($Stage) } else { $script:Stages | ForEach-Object { $_.name } }
    $actual = ""
    try {
        foreach ($n in $lista) {
            $actual = $n
            $titulo = ($script:Stages | Where-Object { $_.name -eq $n }).title
            Log "[$n] $titulo"
            Invoke-StageByName $n
        }
        $script:CodigoSalida = 0
    } catch {
        Write-Err "La instalacion se paro en la etapa '$actual': $($_.Exception.Message)"
        Write-Host "   Puedes volver a lanzar el instalador: retoma donde se quedo." -ForegroundColor Gray
        $script:CodigoSalida = 1
    }
}

# Cargado con `. install.ps1` (pruebas): solo define las funciones, no instala nada.
if (-not ($script:ArchivoPropio -and $MyInvocation.InvocationName -eq ".")) {
    # Sin capturar la salida: asi se ve en pantalla lo que imprimen git y uv.
    $script:CodigoSalida = 1
    Install-Hypazo
    if ($script:EsArchivo) { exit $script:CodigoSalida }
}
