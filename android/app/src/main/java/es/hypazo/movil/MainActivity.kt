package es.hypazo.movil

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.webkit.CookieManager
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.webkit.WebViewAssetLoader
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import okhttp3.Request
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    companion object {
        const val LOCAL = "https://appassets.androidplatform.net"
        const val CONEXION = "$LOCAL/assets/movil/conexion.html"
    }

    private lateinit var raiz: FrameLayout
    lateinit var web: WebView
    private val hilo = Executors.newSingleThreadExecutor()
    private val cargador by lazy { WebViewAssetLoader.Builder().addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this)).build() }
    private var pantallaCompleta: View? = null
    private lateinit var puente: Puente

    @Volatile var origen: String? = null          // PC al que está conectada la página ahora
    @Volatile var estado = Estado("buscando", "Buscando tu PC…", emptyList())

    data class Estado(val clave: String, val texto: String, val detalle: List<String>, val via: String = "")

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(guardado: Bundle?) {
        super.onCreate(guardado)
        window.decorView.setBackgroundColor(Color.parseColor("#04050b"))
        raiz = FrameLayout(this).apply { setBackgroundColor(Color.parseColor("#04050b")) }
        web = WebView(this).apply { setBackgroundColor(Color.parseColor("#04050b")) }
        raiz.addView(web)
        setContentView(raiz)
        @Suppress("DEPRECATION")
        window.statusBarColor = Color.parseColor("#04050b")
        @Suppress("DEPRECATION")
        window.navigationBarColor = Color.parseColor("#04050b")
        if (Build.VERSION.SDK_INT >= 30) {
            // De borde a borde en todas las versiones (en Android 15+ es obligatorio): el fondo llega tras las barras.
            window.setDecorFitsSystemWindows(false)
            raiz.setOnApplyWindowInsetsListener { v, ins ->
                val b = ins.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime() or WindowInsets.Type.displayCutout())
                if (pantallaCompleta == null) v.setPadding(b.left, b.top, b.right, b.bottom)
                ins
            }
        }

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            mediaPlaybackRequiresUserGesture = true
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            setSupportMultipleWindows(false)
        }
        CookieManager.getInstance().setAcceptCookie(true)
        web.webViewClient = Cliente()
        web.webChromeClient = Cromo()
        puente = Puente(this)
        puente.instalar()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = atras(this)
        })
        val cm = getSystemService(ConnectivityManager::class.java)
        cm.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = runOnUiThread { if (origen == null) conectar() else comprobarRuta() }
        })
        // Con el VPN de Tailscale encendido, la red por defecto es el VPN y no avisa de que vuelve el wifi: se vigila aparte.
        cm.registerNetworkCallback(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(),
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) = runOnUiThread { web.postDelayed({ if (origen == null) conectar() else comprobarRuta() }, 2000) }
            })
        if (!abrirEnlace(intent)) conectar()
        if (Almacen.prefs(this).getBoolean("avisos", false)) AvisosServicio.encender(this)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        abrirEnlace(intent)
    }

    override fun onResume() {
        super.onResume()
        if (origen == null && estado.clave != "buscando") conectar()
        else if (estado.via == "Tailscale") comprobarRuta()     // de vuelta en casa: mejor el wifi
    }

    // ---------- conexión ----------
    fun conectar() {
        val pc = Almacen.leer(this)
        if (pc == null) { mostrar(Estado("sin_emparejar", "Empareja este móvil con Hypazo del PC.", emptyList())); return }
        mostrar(Estado("buscando", "Buscando tu PC…", emptyList()))
        hilo.execute {
            when (val b = Red.buscar(pc)) {
                is Red.Busqueda.Ok -> runOnUiThread { abrirPc(pc, b.origen, b.via) }
                Red.Busqueda.Revocado -> runOnUiThread { mostrar(Estado("revocado", "El PC ha quitado el permiso a este móvil. Vuelve a emparejarlo.", emptyList())) }
                is Red.Busqueda.Nada -> runOnUiThread {
                    mostrar(Estado("sin_pc", "No encuentro Hypazo en tu PC.", b.detalle))
                    web.postDelayed({ if (origen == null && estado.clave == "sin_pc") conectar() }, 10_000)
                }
            }
        }
    }

    /** Cambió la red (wifi ↔ datos): si la ruta buena ya es otra, se pasa a ella. */
    private fun comprobarRuta() {
        val pc = Almacen.leer(this) ?: return
        hilo.execute {
            val b = Red.buscar(pc)
            runOnUiThread {
                when {
                    b is Red.Busqueda.Ok && b.origen != origen -> abrirPc(pc, b.origen, b.via)
                    b is Red.Busqueda.Revocado -> { origen = null; mostrar(Estado("revocado", "El PC ha quitado el permiso a este móvil. Vuelve a emparejarlo.", emptyList())) }
                }
            }
        }
    }

    private fun abrirPc(pc: Pc, o: String, via: String) {
        // Cookie HttpOnly: el JS de la página no puede leer el token; el WebView la manda en cada petición.
        CookieManager.getInstance().setCookie(o, "hz=${pc.token}; Secure; HttpOnly; SameSite=Strict; Path=/")
        CookieManager.getInstance().flush()
        origen = o
        estado = Estado("conectado", "Conectado por $via", emptyList(), via)
        web.loadUrl("$o/")
        actualizarIps(pc, o)
    }

    /** Si el PC cambió de IP o encendió Tailscale, se apunta sin volver a emparejar. */
    private fun actualizarIps(pc: Pc, o: String) = hilo.execute {
        runCatching {
            Red.cliente(pc).newCall(Request.Builder().url("$o/api/movil/red").header("Authorization", "Bearer ${pc.token}").build())
                .execute().use { r ->
                    if (!r.isSuccessful) return@runCatching
                    val j = org.json.JSONObject(r.body!!.string())
                    fun lista(k: String) = j.optJSONArray(k)?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList()
                    val nuevo = pc.copy(wifi = lista("wifi"), tailscale = lista("tailscale"), puerto = j.optInt("puerto", pc.puerto))
                    if (nuevo != pc && nuevo.ips().isNotEmpty()) {
                        Almacen.guardar(this, nuevo)
                    }
                }
        }
    }

    fun mostrar(e: Estado) {
        estado = e
        origen = null
        if (web.url?.startsWith(CONEXION) == true) puente.avisarEstado() else web.loadUrl(CONEXION)
    }

    // ---------- emparejar (hypazo://emparejar?w=…&t=…&p=…&h=…&c=…) ----------
    /** Escáner de Google Play: no pide permiso de cámara; la imagen no llega a la app, solo el texto del QR. */
    fun escanear() {
        val opciones = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
        GmsBarcodeScanning.getClient(this, opciones).startScan()
            .addOnSuccessListener { b ->
                if (!abrirEnlace(Intent(Intent.ACTION_VIEW, Uri.parse(b.rawValue ?: ""))))
                    mostrar(Estado("sin_emparejar", "Ese QR no es de Hypazo. Escanea el de Ajustes → Conectar el móvil.", emptyList()))
            }
            .addOnFailureListener { e ->
                mostrar(Estado("sin_emparejar", "No se pudo abrir el escáner. Teclea la IP y el código.", listOfNotNull(e.message)))
            }
    }

    private fun abrirEnlace(i: Intent?): Boolean {
        val u: Uri = i?.data ?: return false
        if (u.scheme != "hypazo" || u.host != "emparejar") return false
        val wifi = u.getQueryParameter("w").orEmpty().split(",").filter { it.isNotBlank() }
        val ts = u.getQueryParameter("t").orEmpty().split(",").filter { it.isNotBlank() }
        val puerto = u.getQueryParameter("p")?.toIntOrNull() ?: 8766
        val huella = u.getQueryParameter("h").orEmpty()
        val codigo = u.getQueryParameter("c").orEmpty()
        if (huella.length != 64 || codigo.isBlank() || (wifi + ts).isEmpty()) {
            mostrar(Estado("sin_emparejar", "Ese QR no es de Hypazo o está incompleto.", emptyList()))
            return true
        }
        emparejar(wifi, ts, puerto, huella, codigo) { _ -> }
        return true
    }

    /** Canjea el código probando wifi y luego Tailscale. huella null = emparejado a mano (se fija la que se vea). */
    fun emparejar(wifi: List<String>, ts: List<String>, puerto: Int, huella: String?, codigo: String, listo: (String?) -> Unit) {
        mostrar(Estado("emparejando", "Emparejando con tu PC…", emptyList()))
        hilo.execute {
            val fallos = mutableListOf<String>()
            for (ip in wifi + ts) {
                try {
                    val (token, vista) = Red.canjear(ip, puerto, huella, codigo, nombreMovil(), Almacen.leer(this)?.token)
                    val pc = Pc(wifi, ts, puerto, huella ?: vista, token)
                    Almacen.guardar(this, pc)
                    runOnUiThread { listo(vista); if (huella != null) conectar() }
                    return@execute
                } catch (e: IllegalStateException) {
                    fallos += e.message ?: "Error"; break       // el PC respondió: el código no vale, no seguir probando
                } catch (e: Exception) {
                    fallos += "$ip: ${Red.motivo(e)}"
                }
            }
            runOnUiThread { mostrar(Estado("sin_emparejar", "No se pudo emparejar.", fallos)); listo(null) }
        }
    }

    /** El nombre que el usuario ve en Ajustes del móvil («POCO F7»), no el código de modelo. */
    private fun nombreMovil(): String =
        android.provider.Settings.Global.getString(contentResolver, "device_name")?.takeIf { it.isNotBlank() }
            ?: "${Build.MANUFACTURER} ${Build.MODEL}"

    fun olvidar() {
        Almacen.olvidar(this)
        AvisosServicio.apagar(this)
        CookieManager.getInstance().removeAllCookies(null)
        mostrar(Estado("sin_emparejar", "Empareja este móvil con Hypazo del PC.", emptyList()))
    }

    fun pedirPermisoAvisos() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
    }

    // ---------- atrás: diálogo → panel → pestaña Cazar → salir ----------
    private fun atras(cb: OnBackPressedCallback) {
        if (pantallaCompleta != null) { web.webChromeClient?.onHideCustomView(); return }
        if (origen == null) { cb.isEnabled = false; onBackPressedDispatcher.onBackPressed(); cb.isEnabled = true; return }
        web.evaluateJavascript("window.hypazoAtras ? hypazoAtras() : false") { r ->
            if (r != "true") { cb.isEnabled = false; onBackPressedDispatcher.onBackPressed(); cb.isEnabled = true }
        }
    }

    private fun esNuestro(url: String) = url.startsWith("$LOCAL/") || (origen?.let { url.startsWith("$it/") } ?: false)

    inner class Cliente : WebViewClient() {
        override fun shouldInterceptRequest(view: WebView, req: WebResourceRequest): WebResourceResponse? {
            val url = req.url.toString()
            if (url.startsWith("$LOCAL/")) return cargador.shouldInterceptRequest(req.url)
            val o = origen ?: return null
            if (req.isForMainFrame && req.method == "GET" && url == "$o/") return portada(o)
            return null
        }

        /** La página del PC con la capa del móvil (movil.css y movil.js del APK) ya puesta: sin parpadeo de escritorio. */
        private fun portada(o: String): WebResourceResponse? {
            val pc = Almacen.leer(this@MainActivity) ?: return null
            return try {
                Red.cliente(pc).newCall(Request.Builder().url("$o/").header("Authorization", "Bearer ${pc.token}").build()).execute().use { r ->
                    if (!r.isSuccessful) return null
                    val html = (r.body?.string() ?: "").replaceFirst("</head>",
                        "<link rel=\"stylesheet\" href=\"$LOCAL/assets/movil/movil.css\">" +
                            "<script src=\"$LOCAL/assets/movil/movil.js\" defer></script></head>")
                    WebResourceResponse("text/html", "utf-8", html.byteInputStream()).apply {
                        setStatusCodeAndReasonPhrase(200, "OK")
                        responseHeaders = mapOf("Cache-Control" to "no-store")
                    }
                }
            } catch (e: Exception) { null }
        }

        override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
            val pc = Almacen.leer(this@MainActivity)
            val host = Uri.parse(error.url).host
            val der = error.certificate.x509Certificate?.encoded
            if (pc != null && der != null && host in pc.ips() && Red.huella(der).equals(pc.huella, true)) handler.proceed()
            else handler.cancel()        // cualquier otro certificado: no se carga nada
        }

        override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
            val url = req.url.toString()
            if (esNuestro(url)) return false
            if (req.url.scheme == "https" || req.url.scheme == "http")
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, req.url)) }   // enlaces de fuera: al navegador
            return true
        }

        override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
            if (req.isForMainFrame && origen != null) mostrar(Estado("sin_pc", "Se perdió la conexión con el PC.", listOf(err.description.toString())))
        }

        override fun onReceivedHttpError(view: WebView, req: WebResourceRequest, resp: WebResourceResponse) {
            if (req.isForMainFrame && resp.statusCode == 401) mostrar(Estado("revocado", "El PC ha quitado el permiso a este móvil. Vuelve a emparejarlo.", emptyList()))
        }

        override fun onPageFinished(view: WebView, url: String) {
            if (url.startsWith(CONEXION)) puente.avisarEstado()
        }
    }

    inner class Cromo : WebChromeClient() {
        private var alSalir: CustomViewCallback? = null
        override fun onShowCustomView(view: View, callback: CustomViewCallback) {
            pantallaCompleta = view; alSalir = callback
            raiz.setPadding(0, 0, 0, 0)
            raiz.addView(view, FrameLayout.LayoutParams(-1, -1))
            if (Build.VERSION.SDK_INT >= 30) window.insetsController?.apply {
                hide(WindowInsets.Type.systemBars())
                systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        }
        override fun onHideCustomView() {
            pantallaCompleta?.let { raiz.removeView(it) }
            pantallaCompleta = null
            alSalir?.onCustomViewHidden(); alSalir = null
            if (Build.VERSION.SDK_INT >= 30) window.insetsController?.show(WindowInsets.Type.systemBars())
            raiz.requestApplyInsets()
        }
    }
}
