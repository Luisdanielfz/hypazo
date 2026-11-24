# Lo ejecuta el desinstalador del .exe. Quita Hypazo de %LOCALAPPDATA%\hypazo y del PATH del usuario.
# NUNCA toca la carpeta de clips (Videos\Hypazo o la que se eligiera en `hypazo setup`).
$casa = if ($env:HYPAZO_HOME) { $env:HYPAZO_HOME } else { Join-Path $env:LOCALAPPDATA "hypazo" }
$bin = Join-Path $casa "bin"

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    $resto = @($userPath -split ";" | Where-Object { $_ -and $_.TrimEnd("\") -ine $bin.TrimEnd("\") })
    [Environment]::SetEnvironmentVariable("Path", ($resto -join ";"), "User")
}

$clips = $null
try { $clips = (Get-Content -LiteralPath (Join-Path $casa "config\config.json") -Raw | ConvertFrom-Json).salida } catch { }
if ($clips) {
    $casaReal = [IO.Path]::GetFullPath($casa).TrimEnd("\") + "\"
    if ([IO.Path]::GetFullPath($clips).TrimEnd("\").StartsWith($casaReal.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "La carpeta de clips esta dentro de la instalacion: no borro nada." ; exit 0
    }
}
foreach ($d in "hypazo", "pm", "bin", "config") {
    Remove-Item -LiteralPath (Join-Path $casa $d) -Recurse -Force -ErrorAction SilentlyContinue
}
# Identidad de la app en Windows (nombre e icono en la barra de tareas y los avisos); la crea hypazo.py.
Remove-Item -Path "HKCU:\Software\Classes\AppUserModelId\Hypazo.App" -Recurse -Force -ErrorAction SilentlyContinue
foreach ($lnk in (Join-Path ([Environment]::GetFolderPath("Programs")) "Hypazo.lnk"),
                 (Join-Path ([Environment]::GetFolderPath("Desktop")) "Hypazo.lnk")) {
    Remove-Item -LiteralPath $lnk -Force -ErrorAction SilentlyContinue
}
