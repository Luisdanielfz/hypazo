/* Capa de Hypazo para Android, encima de app.js del PC. Solo usa HypazoMovil (el puente del APK),
   que no da acceso al token ni a nada del móvil salvo vibrar, avisos y descargar un clip. */
(() => {
  "use strict";
  const puente = window.HypazoMovil;
  const pedir = (a, extra) => puente && puente.postMessage(JSON.stringify({ a, ...extra }));
  document.documentElement.classList.add("hz-movil");
  const $ = id => document.getElementById(id);
  // La cabecera es de cristal (backdrop-filter) y eso atrapa a sus hijos «fixed»: las pestañas salen de ella para ir abajo.
  const nav = document.querySelector("header [role=tablist]");
  if (nav) document.body.append(nav);

  // Atrás de Android: diálogo → asistente → subvista → pestaña Cazar → salir de la app.
  window.hypazoAtras = () => {
    const d = [...document.querySelectorAll("dialog[open]")].pop();
    if (d) { d.dispatchEvent(new Event("cancel", { cancelable: true })); if (d.open) d.close(); return true; }
    const asis = $("tab-asistente");
    if (asis && !asis.hidden && typeof cerrarAsistente === "function") { cerrarAsistente(); return true; }
    if (typeof tab !== "undefined" && typeof irA === "function") {
      if (tab === "revisar" || tab === "limpieza") { irA("clips"); return true; }
      if (tab !== "cazar") { irA("cazar"); return true; }
    }
    return false;
  };

  const escribe = el => el && el.matches && el.matches("input:not([type=checkbox]):not([type=radio]), textarea, [contenteditable]");
  document.addEventListener("focusin", e => { if (escribe(e.target)) document.documentElement.classList.add("hz-teclado"); });
  document.addEventListener("focusout", () => setTimeout(() => {
    if (!escribe(document.activeElement)) document.documentElement.classList.remove("hz-teclado");
  }, 50));

  // Un toque de vibración en lo que se pulsa a ciegas mientras se mira el directo.
  document.addEventListener("click", e => {
    const b = e.target.closest("#ya, #ya2, #btn, #pausa, [data-estado], .btn.si, .btn.peligro");
    if (b) pedir("vibrar", { ms: b.id === "ya" || b.id === "ya2" ? 60 : 25 });
  }, true);

  // Editor: guardar el clip en el móvil (Descargas/Hypazo).
  const ed = $("editor");
  if (ed) {
    const cab = $("edCerrar") && $("edCerrar").parentElement;
    const g = document.createElement("button");
    g.className = "btn hz-guardar"; g.type = "button";
    g.innerHTML = '<svg class="ic"><use href="#i-upload"/></svg><span>Guardar en el móvil</span>';
    g.onclick = () => {
      const src = $("edVideo").getAttribute("src") || "";
      const ruta = src.startsWith("http") ? new URL(src).pathname + new URL(src).search : src;
      const nombre = decodeURIComponent(ruta.split("?")[0].split("/").pop() || "clip.mp4");
      pedir("descargar", { url: ruta.split("?")[0], nombre });
    };
    if (cab) cab.insertBefore(g, $("edCerrar"));
  }

  // Ajustes → Este móvil: avisos y pantalla de conexión.
  const aj = document.querySelector("#tab-ajustes .ajustes");
  if (aj) {
    const p = document.createElement("div");
    p.className = "glass panel hz-este"; p.style.setProperty("--i", "0");
    p.innerHTML = '<h2 class="titulo">Este móvil</h2>' +
      '<p class="ayuda" id="hzVia">Conectado a tu PC.</p>' +
      '<label class="check"><input type="checkbox" id="hzAvisos"> <span>Avisarme de clips nuevos y cazas<br><small>También con la app cerrada. Deja un aviso fijo mientras está activo.</small></span></label>' +
      '<div class="botones"><button class="btn" id="hzConexion" type="button"><svg class="ic"><use href="#i-activity"/></svg><span>Conexión con el PC</span></button></div>';
    aj.prepend(p);
    $("hzAvisos").onchange = () => pedir("avisos", { on: $("hzAvisos").checked });
    $("hzConexion").onclick = () => pedir("conexion");
  }
  if (puente) {
    puente.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.tipo === "info") {
        if ($("hzAvisos")) $("hzAvisos").checked = m.avisos;
        if ($("hzVia")) $("hzVia").textContent = `Conectado a tu PC por ${m.via || "la red"}. App ${m.version}.`;
      }
    };
    pedir("info");
  }
})();
