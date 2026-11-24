package es.hypazo.movil

import es.hypazo.movil.AvisosServicio.Companion.Pulso
import es.hypazo.movil.AvisosServicio.Companion.novedades
import org.junit.Assert.assertEquals
import org.junit.Test

class AvisosTest {
    private fun p(corriendo: Boolean, vararg listos: Int, centinela: String = "Apagado.") =
        Pulso(corriendo, "ibai", centinela, listos.map { "100-$it" to it })

    @Test fun laPrimeraVezNoAvisaDeLoQueYaHabia() {
        val vistos = mutableSetOf<String>()
        assertEquals(emptyList<Pair<String, String>>(), novedades(null, p(true, 1, 2), vistos))
        assertEquals(setOf("100-1", "100-2"), vistos)
    }

    @Test fun avisaUnaVezDeCadaClipNuevo() {
        val vistos = mutableSetOf("100-1")
        val a = novedades(p(true, 1), p(true, 1, 2), vistos)
        assertEquals(listOf("Clip listo" to "Clip 2 de ibai guardado. Revísalo en Clips."), a)
        assertEquals(emptyList<Pair<String, String>>(), novedades(p(true, 1, 2), p(true, 1, 2), vistos))
    }

    @Test fun avisaCuandoArrancaLaCazaYSiEsDelCentinela() {
        assertEquals("Caza en marcha", novedades(p(false), p(true), mutableSetOf()).single().first)
        assertEquals("El centinela arrancó una caza",
            novedades(p(false, centinela = "Activado: lo miro en menos de un minuto."), p(true), mutableSetOf()).single().first)
        assertEquals(emptyList<Pair<String, String>>(), novedades(p(true), p(true), mutableSetOf()))
    }
}
