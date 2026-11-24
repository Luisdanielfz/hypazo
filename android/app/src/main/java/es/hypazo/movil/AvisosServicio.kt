package es.hypazo.movil

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import okhttp3.Request
import org.json.JSONObject

/**
 * Avisos con la app cerrada: mientras estén encendidos, pregunta al PC cada 15 s por /api/status
 * y avisa de cada clip listo y de cada caza que arranca (también las del centinela).
 */
class AvisosServicio : Service() {
    companion object {
        private const val CADA_MS = 15_000L
        private const val FIJO = 1
        private const val CANAL_FIJO = "conexion"
        private const val CANAL_CLIPS = "clips"

        fun encender(ctx: Context) {
            val i = Intent(ctx, AvisosServicio::class.java)
            runCatching { ctx.startForegroundService(i) }
        }

        fun apagar(ctx: Context) { ctx.stopService(Intent(ctx, AvisosServicio::class.java)) }

        /** Lo que importa de /api/status para avisar. */
        data class Pulso(val corriendo: Boolean, val canal: String, val centinela: String, val listos: List<Pair<String, Any?>>)

        fun pulso(j: JSONObject): Pulso {
            val vivos = j.optJSONArray("vivos")
            val listos = (0 until (vivos?.length() ?: 0)).map { vivos!!.getJSONObject(it) }
                .filter { it.optString("estado") == "listo" }.map { "${it.opt("hora")}-${it.opt("n")}" to it.opt("n") }
            return Pulso(j.optBoolean("corriendo"), j.optString("canal"), j.optString("centinela", "Apagado."), listos)
        }

        /** Qué avisar comparando dos pulsos. Puro: lo prueban los tests. La primera vez solo apunta lo que ya había. */
        fun novedades(antes: Pulso?, ahora: Pulso, vistos: MutableSet<String>): List<Pair<String, String>> {
            val salida = mutableListOf<Pair<String, String>>()
            for ((id, n) in ahora.listos)
                if (vistos.add(id) && antes != null) salida += "Clip listo" to "Clip $n de ${ahora.canal} guardado. Revísalo en Clips."
            if (antes != null && !antes.corriendo && ahora.corriendo) {
                val porCentinela = antes.centinela != "Apagado."    // con el centinela encendido, casi siempre es él
                salida += (if (porCentinela) "El centinela arrancó una caza" else "Caza en marcha") to "Cazando en ${ahora.canal}."
            }
            return salida
        }
    }

    @Volatile private var vivo = true
    private var hilo: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CANAL_FIJO, "Conexión con el PC", NotificationManager.IMPORTANCE_MIN))
        nm.createNotificationChannel(NotificationChannel(CANAL_CLIPS, "Clips y cazas", NotificationManager.IMPORTANCE_HIGH).apply { enableVibration(true) })
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val n = fijo("Pendiente de clips nuevos y cazas de tu PC")
        if (Build.VERSION.SDK_INT >= 34) startForeground(FIJO, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(FIJO, n)
        if (hilo == null) hilo = Thread(::bucle).also { it.start() }
        return START_STICKY
    }

    override fun onDestroy() { vivo = false; hilo?.interrupt(); super.onDestroy() }

    private fun abrirApp() = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java)
        .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)

    private fun fijo(texto: String): Notification = Notification.Builder(this, CANAL_FIJO)
        .setSmallIcon(R.drawable.ic_aviso).setContentTitle("Hypazo").setContentText(texto)
        .setContentIntent(abrirApp()).setOngoing(true).build()

    private fun bucle() {
        val nm = getSystemService(NotificationManager::class.java)
        var origen: String? = null
        var antes: Pulso? = null
        val vistos = mutableSetOf<String>()
        var conectado: Boolean? = null
        var id = 100
        while (vivo) {
            val pc = Almacen.leer(this) ?: run { stopSelf(); return }
            val ahora = runCatching {
                val o = origen ?: (Red.buscar(pc) as? Red.Busqueda.Ok)?.origen ?: error("sin PC")
                origen = o
                Red.cliente(pc).newCall(Request.Builder().url("$o/api/status").header("Authorization", "Bearer ${pc.token}").build())
                    .execute().use { r -> check(r.isSuccessful); pulso(JSONObject(r.body!!.string())) }
            }.getOrNull()
            if (ahora == null) origen = null        // la próxima vez vuelve a probar wifi y Tailscale
            if ((ahora != null) != conectado) {
                conectado = ahora != null
                nm.notify(FIJO, fijo(if (conectado) "Pendiente de clips nuevos y cazas de tu PC" else "Sin conexión con el PC: lo reintento solo"))
            }
            if (ahora != null) {
                for ((t, txt) in novedades(antes, ahora, vistos)) nm.notify(id++, Notification.Builder(this, CANAL_CLIPS)
                    .setSmallIcon(R.drawable.ic_aviso).setContentTitle(t).setContentText(txt)
                    .setContentIntent(abrirApp()).setAutoCancel(true).build())
                antes = ahora
            }
            try { Thread.sleep(CADA_MS) } catch (e: InterruptedException) { return }
        }
    }
}
