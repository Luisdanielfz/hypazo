# Hypazo para Android

App de Android que abre el Hypazo de tu PC: en casa por wifi y fuera por Tailscale.
Es un WebView nativo en Kotlin, sin Capacitor ni npm.

## Cómo funciona

- **La interfaz es la del PC.** La app carga `https://<IP del PC>:8766/` y le pone encima la capa móvil del APK
  (`app/src/main/assets/movil/movil.css` y `movil.js`). Cada mejora de `app.html`, `app.css` o `app.js` llega
  al móvil sin instalar un APK nuevo.
- **Seguridad.**
  - El PC abre el puerto 8766 solo si está encendido Ajustes → «Conectar el móvil». Escucha solo en sus IPs
    de wifi y de Tailscale (ver `movil.py`).
  - Todo va por HTTPS con un certificado propio del PC. El móvil solo acepta ese certificado, porque su
    huella SHA-256 va en el QR.
  - El token de cada móvil se guarda cifrado con el Android Keystore (`Almacen.kt`). El WebView lo envía en
    una cookie `HttpOnly`, así que el JavaScript de la página no puede leerlo.
  - El PC solo guarda el hash del token, y desde Ajustes se le puede quitar el permiso a cada móvil.
  - Desde el móvil no se puede abrir carpetas, abrir la mini ventana, actualizar Hypazo ni escribir claves de IA.
- **Puente** (`Puente.kt`). La página solo puede pedir a Android cinco cosas: `vibrar`, `avisos`, `descargar`
  (un `.mp4` de `/salida/`), `conexion` e `info`. Funciona solo en los orígenes de la app y del PC
  emparejado, y nunca devuelve el token.
- **Conexión** (`Red.kt`, `MainActivity.kt`).
  - Prueba primero la IP de wifi (1,5 s) y luego la de Tailscale.
  - Cuando cambia la red, vuelve a probar.
  - Sin PC, muestra `assets/movil/conexion.html`, que reintenta cada 10 s y explica qué pasa.
- **Avisos** (`AvisosServicio.kt`). Mientras estén encendidos, la app consulta `/api/status` cada 15 s y
  avisa de cada clip listo y de cada caza que arranca. Mientras tanto queda un aviso fijo.

## Compartido con el escritorio

| Qué | Dónde | Cómo llega al APK |
|---|---|---|
| `app.html`, `assets/app.css`, `assets/app.js` | raíz del repo | Los sirve el PC; el APK no los copia |
| `assets/fonts/` | raíz del repo | Se copian en cada compilación (tarea `copiarWeb`) para la pantalla sin conexión |
| `movil.css`, `movil.js`, `conexion.html` | `android/app/src/main/assets/movil/` | Exclusivos de Android |

Si hay que tocar el HTML del PC para el móvil, mejor marcarlo (p. ej. `data-solo-pc`) que copiarlo.

## Compilar e instalar

Requisitos: Android Studio (o su JDK) y el SDK de Android 36. Todo compila sin conexión con la caché de Gradle.

```powershell
cd android
.\gradlew.bat assembleDebug testDebugUnitTest
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

### APK firmado (release)

1. Crea el almacén de claves **una vez** y elige tú la contraseña:
   `keytool -genkeypair -v -keystore hypazo.jks -alias hypazo -keyalg RSA -keysize 2048 -validity 10000`
2. Crea `android/keystore.properties`, que no se sube a git:
   ```
   storeFile=hypazo.jks
   storePassword=…
   keyAlias=hypazo
   keyPassword=…
   ```
3. Ejecuta `.\gradlew.bat assembleRelease`. El APK sale en `app\build\outputs\apk\release\`.

Guarda `hypazo.jks` y su contraseña en un sitio seguro: sin ellos no podrás actualizar la app instalada.

## Emparejar

1. En el PC: Ajustes → **Conectar el móvil** → enciéndelo → **Emparejar un móvil**.
2. En el móvil: escanea el QR con la cámara. Se abre Hypazo con un enlace `hypazo://emparejar?…`.
3. Si la cámara no abre el enlace, en la app escribe la IP del PC y el código, y comprueba que la huella
   que muestra el móvil es la misma que sale en el PC.

El código vale 5 minutos y una sola vez. Si alguien teclea 5 códigos mal, se anulan todos.
