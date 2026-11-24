package es.hypazo.movil

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** Conexión con el PC: HTTPS que solo acepta el certificado del PC emparejado (su huella SHA-256). */
object Red {
    const val WIFI_MS = 1500L          // en casa responde al momento; si no, se pasa a Tailscale
    const val TAILSCALE_MS = 5000L

    fun huella(der: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }

    /** Acepta solo el certificado con esta huella. Si huella es null, acepta cualquiera y la apunta (emparejar a mano). */
    class Fijado(private val huella: String?) : X509TrustManager {
        @Volatile var vista: String? = null
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            val h = huella(chain[0].encoded)
            vista = h
            if (huella != null && !h.equals(huella, ignoreCase = true)) throw CertificateException("No es el certificado del PC emparejado")
        }
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = throw CertificateException()
        override fun getAcceptedIssuers() = arrayOf<X509Certificate>()
    }

    fun cliente(tm: X509TrustManager, timeoutMs: Long): OkHttpClient {
        val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }
        return OkHttpClient.Builder()
            .sslSocketFactory(ssl.socketFactory, tm)
            .hostnameVerifier { _, _ -> true }       // el certificado ya está fijado por huella; la IP no lleva nombre
            .connectTimeout(timeoutMs, TimeUnit.MILLISECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    fun cliente(pc: Pc, timeoutMs: Long = TAILSCALE_MS) = cliente(Fijado(pc.huella), timeoutMs)

    sealed class Busqueda {
        data class Ok(val origen: String, val via: String) : Busqueda()
        object Revocado : Busqueda()
        data class Nada(val detalle: List<String>) : Busqueda()
    }

    /** Prueba primero el wifi y luego Tailscale. Sin red de ningún tipo, Nada. */
    fun buscar(pc: Pc): Busqueda {
        val detalle = mutableListOf<String>()
        val intentos = pc.wifi.map { Triple(it, "wifi", WIFI_MS) } + pc.tailscale.map { Triple(it, "Tailscale", TAILSCALE_MS) }
        for ((ip, via, ms) in intentos) {
            val origen = "https://$ip:${pc.puerto}"
            val t0 = System.currentTimeMillis()
            try {
                cliente(pc, ms).newCall(
                    Request.Builder().url("$origen/api/progreso").header("Authorization", "Bearer ${pc.token}").build()
                ).execute().use { r ->
                    val t = System.currentTimeMillis() - t0
                    when (r.code) {
                        200 -> { detalle += "$via $ip: responde en $t ms"; return Busqueda.Ok(origen, via) }
                        401 -> return Busqueda.Revocado
                        else -> detalle += "$via $ip: respondió ${r.code}"
                    }
                }
            } catch (e: Exception) {
                detalle += "$via $ip: ${motivo(e)}"
            }
        }
        return Busqueda.Nada(detalle)
    }

    fun motivo(e: Exception): String = when {
        e is java.net.SocketTimeoutException || e.message?.contains("timeout", true) == true -> "no contesta"
        e is java.net.ConnectException -> "conexión rechazada (¿Hypazo cerrado o «Conectar el móvil» apagado?)"
        e is javax.net.ssl.SSLException -> "el certificado no es el del PC emparejado"
        e is java.net.NoRouteToHostException -> "inalcanzable desde esta red"
        else -> e.javaClass.simpleName
    }

    /** Canjea el código del QR por el token de este móvil. Devuelve (token, huella vista). */
    fun canjear(ip: String, puerto: Int, huella: String?, codigo: String, nombre: String, anterior: String?): Pair<String, String> {
        val tm = Fijado(huella)
        // anterior: el token de antes, para que el PC sustituya este móvil en vez de duplicarlo
        val cuerpo = JSONObject().put("codigo", codigo).put("nombre", nombre).put("anterior", anterior ?: "").toString()
            .toRequestBody("application/json".toMediaType())
        cliente(tm, TAILSCALE_MS).newCall(Request.Builder().url("https://$ip:$puerto/api/movil/canjear").post(cuerpo).build())
            .execute().use { r ->
                val j = JSONObject(r.body?.string() ?: "{}")
                if (!r.isSuccessful) throw IllegalStateException(j.optString("detail", "El PC respondió ${r.code}"))
                return j.getString("token") to (tm.vista ?: "")
            }
    }
}
