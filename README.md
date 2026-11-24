# Hypazo

Saca los mejores momentos de un directo de **Twitch** o **Kick** mientras ocurre: caza los picos del chat y del audio, guarda el clip en vertical con el crédito del canal y te deja revisarlo todo desde una sola app.

> Windows 10/11 de 64 bits. No necesita permisos de administrador.

## Instalar

### Opción 1 (recomendada): una línea en la terminal

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
- Mientras el instalador no esté firmado, Windows SmartScreen muestra "Windows protegió su PC". Pulsa **Más información → Ejecutar de todas formas**. La opción 1 no muestra este aviso.

## Usar

| Comando | Qué hace |
|---|---|
| `hypazo` | Abre la app en su propia ventana de Windows, igual que el acceso directo. |
| `hypazo setup` | Carpeta de clips y crédito por defecto. |
| `hypazo doctor` | Revisa que todo esté bien instalado y dice cómo arreglar lo que falle. |
| `hypazo update` | Actualiza a la última versión publicada (`--channel main` para la última del código). |
| `hypazo version` | Muestra la versión. |

**Durante la caza:**
- **F9** guarda un clip ahora mismo.
- **F8** pausa o reanuda la caza automática. En pausa, F9 guarda un clip **forzado**, pendiente de revisar.

Los clips se guardan en `Vídeos\Hypazo`. Ni `hypazo update` ni el desinstalador los borran.

## Usar desde el móvil (Android)

En **Ajustes → Conectar el móvil**, enciende la opción y pulsa **Emparejar un móvil**. Después, en la app de Android de Hypazo, pulsa **Escanear QR**.

- **En casa** se conecta por wifi; **fuera de casa**, por [Tailscale](https://tailscale.com), que tiene que estar instalado en el PC y en el móvil.
- **Seguridad:**
  - Todo va cifrado, con un certificado propio del PC.
  - Cada móvil tiene su propio permiso, que se puede quitar desde Ajustes.
  - Con la opción apagada, nada fuera del PC puede entrar.
- **Compilar la app:** el código está en [`android/`](android/README.md).

## Desinstalar

Desde **Configuración → Aplicaciones → Hypazo**, si usaste el `.exe`. Si instalaste por terminal, borra la carpeta `%LOCALAPPDATA%\hypazo`. Tus clips se quedan.

## Uso responsable

Hypazo usa la señal **pública** del directo. Cada clip lleva el crédito del canal (`twitch.tv/<canal>` o `kick.com/<canal>`). Respeta las normas de cada plataforma y retira cualquier clip si el creador te lo pide.

## Licencia

© Hypazo. Todos los derechos reservados. El código es público para que puedas ver qué instalas, pero no se concede permiso para copiarlo, modificarlo ni redistribuirlo.

## Modelos de terceros

- Transcripción: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) con el modelo Whisper `small` de OpenAI (MIT).
- Subtítulos solo con la voz del streamer: [WeSpeaker](https://github.com/wenet-e2e/wespeaker) ResNet34 entrenado con VoxCeleb ([Wespeaker/wespeaker-voxceleb-resnet34-LM](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM)), licencia [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Se descarga la primera vez que se usa y no se modifica.
