"""Crédito al canal: todo clip lo lleva (regla del piloto de Hypazo)."""

WEB = {"twitch": "twitch.tv", "kick": "kick.com"}


def credito_final(credito: str, canal: str, plataforma: str) -> str:
    """El crédito que escribió el usuario o, si está vacío, el enlace al canal."""
    propio = (credito or "").strip()
    if propio:
        return propio
    return f"{WEB.get(plataforma, WEB['twitch'])}/{canal.lower()}"
