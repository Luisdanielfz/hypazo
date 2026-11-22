# Hypazo

Saca los mejores momentos de un directo de **Twitch** o **Kick** mientras ocurre: caza los picos del chat y del audio, guarda el clip en vertical con el crédito del canal y te deja revisarlo todo desde una sola app.

> Windows 10/11 de 64 bits. No necesita permisos de administrador.

## Instalar

### Opción 1: una línea en la terminal

Abre **PowerShell** y pega:

```powershell
iex (irm https://raw.githubusercontent.com/Luisdanielfz/hypazo/main/install.ps1)
```

El instalador:
1. descarga versiones fijas de `uv`, Git portátil y ffmpeg, y comprueba su huella SHA-256;
2. descarga Hypazo en `%LOCALAPPDATA%\hypazo`;
3. crea su propio entorno de Python e instala las dependencias;
4. añade el comando `hypazo` a tu PATH;
5. te hace unas preguntas rápidas;
6. crea accesos directos en Inicio y en el escritorio.

No toca el Python ni el Git que ya tengas.

### Opción 2: instalador `.exe`

Descarga `Hypazo-Setup-<versión>.exe` desde [Releases](https://github.com/Luisdanielfz/hypazo/releases/latest) y ejecútalo: siguiente, siguiente, terminar.
- Por dentro hace lo mismo que la opción 1, así que necesita internet.
- Windows puede avisar de "editor desconocido" porque el instalador aún no está firmado.

## Usar

| Comando | Qué hace |
|---|---|
| `hypazo` | Abre la app en el navegador (`http://127.0.0.1:8765`). |
| `hypazo setup` | Carpeta de clips y crédito por defecto. |
| `hypazo doctor` | Revisa que todo esté bien instalado y dice cómo arreglar lo que falle. |
| `hypazo update` | Actualiza a la última versión publicada (`--channel main` para la última del código). |
| `hypazo version` | Muestra la versión. |

**Durante la caza:**
- **F9** guarda un clip ahora mismo.
- **F8** pausa o reanuda la caza automática. En pausa, F9 guarda un clip **forzado**, pendiente de revisar.

Los clips se guardan en `Vídeos\Hypazo`. Ni `hypazo update` ni el desinstalador los borran.

## Desinstalar

Desde **Configuración → Aplicaciones → Hypazo**, si usaste el `.exe`. Si instalaste por terminal, borra la carpeta `%LOCALAPPDATA%\hypazo`. Tus clips se quedan.

## Uso responsable

Hypazo usa la señal **pública** del directo. Cada clip lleva el crédito del canal (`twitch.tv/<canal>` o `kick.com/<canal>`). Respeta las normas de cada plataforma y retira cualquier clip si el creador te lo pide.

## Licencia

© Hypazo. Todos los derechos reservados. El código es público para que puedas ver qué instalas, pero no se concede permiso para copiarlo, modificarlo ni redistribuirlo.
