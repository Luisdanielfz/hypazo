package es.hypazo.movil

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** El PC emparejado. El token va cifrado con una clave del Android Keystore (no sale del chip). */
data class Pc(
    val wifi: List<String>,
    val tailscale: List<String>,
    val puerto: Int,
    val huella: String,
    val token: String,
) {
    fun ips() = wifi + tailscale
    fun origenes() = ips().map { "https://$it:$puerto" }
}

object Almacen {
    private const val ALIAS = "hypazo-pc"
    private const val PREFS = "hypazo"
    private const val CLAVE = "pc"

    private fun clave(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as SecretKey?)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
        )
        return gen.generateKey()
    }

    fun leer(ctx: Context): Pc? {
        val guardado = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(CLAVE, null) ?: return null
        return try {
            val bytes = Base64.decode(guardado, Base64.NO_WRAP)
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, clave(), GCMParameterSpec(128, bytes, 0, 12))
            val j = JSONObject(String(c.doFinal(bytes, 12, bytes.size - 12)))
            Pc(lista(j.getJSONArray("wifi")), lista(j.getJSONArray("tailscale")), j.getInt("puerto"),
                j.getString("huella"), j.getString("token"))
        } catch (e: Exception) {
            null            // clave del Keystore perdida (p. ej. tras restaurar): toca emparejar otra vez
        }
    }

    fun guardar(ctx: Context, pc: Pc) {
        val j = JSONObject()
            .put("wifi", JSONArray(pc.wifi)).put("tailscale", JSONArray(pc.tailscale))
            .put("puerto", pc.puerto).put("huella", pc.huella).put("token", pc.token)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, clave())
        val datos = c.iv + c.doFinal(j.toString().toByteArray())
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(CLAVE, Base64.encodeToString(datos, Base64.NO_WRAP)).apply()
    }

    fun olvidar(ctx: Context) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(CLAVE).apply()
    }

    /** Preferencias sin secretos (avisos encendidos). */
    fun prefs(ctx: Context) = ctx.getSharedPreferences("$PREFS-ajustes", Context.MODE_PRIVATE)

    private fun lista(a: JSONArray) = (0 until a.length()).map { a.getString(it) }.filter { it.isNotBlank() }
}
