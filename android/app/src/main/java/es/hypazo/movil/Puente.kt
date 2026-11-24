package es.hypazo.movil

import android.annotation.SuppressLint
import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.MediaStore
import android.webkit.WebView
import android.widget.Toast
import androidx.webkit.JavaScriptReplyProxy
import androidx.webkit.WebMessageCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject

/**
 * El único canal entre la página y Android: `HypazoMovil.postMessage(JSON)`.
 * Solo existe en los orígenes de la app y del PC emparejado, y nunca devuelve el token.
 * Desde la página del PC solo se aceptan órdenes inofensivas (vibrar, avisos, descargar un clip).
 */
class Puente(private val act: MainActivity) {
    private var respuesta: JavaScriptReplyProxy? = null      // la pantalla de conexión, para avisarle de cambios
    private val soloLocal = setOf("estado", "reintentar", "emparejar", "escanear", "olvidar")
    private val delPc = setOf("vibrar", "avisos", "descargar", "conexion", "info")

    /**
     * Se registra una sola vez: quitar y volver a poner el listener con la página abierta tumba el WebView
     * (visto en WebView 157). Por eso acepta cualquier origen y filtra aquí: solo la app y el PC conectado ahora.
     */
    @SuppressLint("RequiresFeature")
    fun instalar() {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return
        WebViewCompat.addWebMessageListener(act.web, "HypazoMovil", setOf("*")) { _: WebView, msg: WebMessageCompat, origen: Uri, _: Boolean, rp: JavaScriptReplyProxy ->
            val o = origen.toString().trimEnd('/')
            val j = runCatching { JSONObject(msg.data ?: "") }.getOrNull() ?: return@addWebMessageListener
            val a = j.optString("a")
            val local = o == MainActivity.LOCAL
            if ((local && (a in soloLocal || a in delPc)) || (o == act.origen && a in delPc)) atender(a, j, rp, local)
        }
    }

    fun avisarEstado() { respuesta?.let { enviar(it, estadoJson()) } }

    private fun estadoJson(): JSONObject {
        val e = act.estado
        val pc = Almacen.leer(act)
        return JSONObject().put("tipo", "estado").put("clave", e.clave).put("texto", e.texto).put("detalle", JSONArray(e.detalle))
            .put("pc", pc?.let { JSONObject().put("wifi", JSONArray(it.wifi)).put("tailscale", JSONArray(it.tailscale)).put("puerto", it.puerto) } ?: JSONObject.NULL)
            .put("avisos", Almacen.prefs(act).getBoolean("avisos", false))
            .put("version", act.packageManager.getPackageInfo(act.packageName, 0).versionName)
    }

    private fun enviar(rp: JavaScriptReplyProxy, j: JSONObject) = act.runOnUiThread { runCatching { rp.postMessage(j.toString()) } }

    private fun atender(a: String, j: JSONObject, rp: JavaScriptReplyProxy, local: Boolean) {
        when (a) {
            "estado" -> { respuesta = rp; enviar(rp, estadoJson()) }
            "info" -> enviar(rp, estadoJson().put("tipo", "info").put("via", act.estado.via))
            "reintentar" -> act.conectar()
            "conexion" -> act.mostrar(act.estado.copy(clave = "manual", texto = "Conexión con tu PC", detalle = emptyList()))
            "olvidar" -> act.olvidar()
            "escanear" -> act.escanear()
            "emparejar" -> {
                // A mano: IP + código. La huella se fija con la que se vea y se enseña para compararla con la del PC.
                val ip = j.optString("ip").trim()
                val codigo = j.optString("codigo").trim()
                val puerto = j.optInt("puerto", 8766)
                if (!Regex("^[0-9.]{7,15}$").matches(ip) || codigo.length < 8) {
                    enviar(rp, JSONObject().put("tipo", "error").put("texto", "Escribe la IP del PC (p. ej. 192.168.1.50) y el código de 8 letras."))
                    return
                }
                val ts = ip.startsWith("100.")
                act.emparejar(if (ts) emptyList() else listOf(ip), if (ts) listOf(ip) else emptyList(), puerto, null, codigo) { vista ->
                    if (vista != null) enviar(rp, JSONObject().put("tipo", "huella").put("huella", vista.take(8).uppercase().chunked(4).joinToString(" ")))
                }
            }
            "vibrar" -> vibrar(j.optLong("ms", 30).coerceIn(10, 400))
            "avisos" -> {
                val on = j.optBoolean("on")
                Almacen.prefs(act).edit().putBoolean("avisos", on).apply()
                if (on) { act.pedirPermisoAvisos(); AvisosServicio.encender(act) } else AvisosServicio.apagar(act)
                enviar(rp, JSONObject().put("tipo", "avisos").put("on", on))
            }
            "descargar" -> descargar(j.optString("url"), j.optString("nombre"))
        }
    }

    private fun vibrar(ms: Long) {
        @Suppress("DEPRECATION")
        val v = act.getSystemService(Vibrator::class.java) ?: return
        v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
    }

    /** Guarda un clip del PC en Descargas/Hypazo. Solo rutas de /salida/ y .mp4. */
    private fun descargar(ruta: String, nombre: String) {
        val o = act.origen ?: return
        val pc = Almacen.leer(act) ?: return
        val limpio = nombre.replace(Regex("[^\\w .()-]"), "_").take(120)
        if (!ruta.startsWith("/salida/") || ".." in ruta || !limpio.endsWith(".mp4", true)) return
        Toast.makeText(act, "Descargando $limpio…", Toast.LENGTH_SHORT).show()
        Thread {
            val ok = runCatching {
                Red.cliente(pc).newCall(Request.Builder().url(o + ruta).header("Authorization", "Bearer ${pc.token}").build()).execute().use { r ->
                    check(r.isSuccessful)
                    val cv = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, limpio)
                        put(MediaStore.Downloads.MIME_TYPE, "video/mp4")
                        put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Hypazo")
                    }
                    val uri = act.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv)!!
                    act.contentResolver.openOutputStream(uri)!!.use { out -> r.body!!.byteStream().copyTo(out) }
                }
            }.isSuccess
            act.runOnUiThread {
                Toast.makeText(act, if (ok) "Guardado en Descargas/Hypazo" else "No se pudo descargar el clip", Toast.LENGTH_LONG).show()
            }
        }.start()
    }
}
