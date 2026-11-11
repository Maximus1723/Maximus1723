#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Te Divina - generador de videos cortos verticales (9:16) para redes sociales.

Uso:
    python generar_video.py                 # usa config.yaml
    python generar_video.py --config otro.yaml

Lee el guion de config.yaml, arma la animación con los PNG de ./imagenes/,
genera (o usa) la narración y escribe el MP4 en ./salida/.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependencias: avisar en español si falta algo
# ---------------------------------------------------------------------------
try:
    import numpy as np
    import yaml
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError as e:  # pragma: no cover
    print(f"\n[ERROR] Falta instalar una librería: {e.name}")
    print("Ejecuta:  pip install -r requirements.txt\n")
    sys.exit(1)

BASE = Path(__file__).resolve().parent
AVISOS: list[str] = []


def aviso(msg: str) -> None:
    AVISOS.append(msg)
    print(f"  [AVISO] {msg}")


def info(msg: str) -> None:
    print(f"  {msg}")


def titulo(msg: str) -> None:
    print(f"\n== {msg} ==")


def error_fatal(msg: str) -> None:
    print(f"\n[ERROR] {msg}\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------
INSTRUCCIONES_FFMPEG = """
  ffmpeg no está instalado en tu computadora. Cómo instalarlo:
    - Windows:  abre "Símbolo del sistema" y escribe:  winget install ffmpeg
                (luego cierra y vuelve a abrir la ventana)
    - Mac:      instala Homebrew (https://brew.sh) y escribe:  brew install ffmpeg
    - Linux:    sudo apt install ffmpeg
"""


def buscar_ffmpeg() -> str:
    ruta = shutil.which("ffmpeg")
    if ruta:
        info(f"ffmpeg encontrado: {ruta}")
        return ruta
    print(INSTRUCCIONES_FFMPEG)
    try:
        import imageio_ffmpeg

        ruta = imageio_ffmpeg.get_ffmpeg_exe()
        aviso("ffmpeg no está instalado; uso temporalmente la copia que trae "
              "moviepy (imageio-ffmpeg). Te recomiendo instalarlo.")
        return ruta
    except Exception:
        error_fatal("No encontré ffmpeg. Instálalo con las instrucciones de arriba.")
    return ""


def ffmpeg_info(ffmpeg: str, archivo: Path) -> str:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(archivo)],
                       capture_output=True, text=True)
    return r.stderr


def duracion_ffmpeg(ffmpeg: str, archivo: Path) -> float:
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", ffmpeg_info(ffmpeg, archivo))
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------------------------------------------------------------------------
# Reglas de contenido (COFEPRIS) - no negociables
# ---------------------------------------------------------------------------
REGLAS_PROHIBIDAS = [
    (r"\bdetox\w*", "la palabra 'detox'"),
    (r"\bdesintoxic\w*", "desintoxicar"),
    (r"\btoxinas?\b", "eliminar toxinas"),
    (r"\b(baja\w*|perde\w*|perd[ií]\w*|p[eé]rdida|reduc\w*|control\w*)\s+(de\s+)?(peso|kilos?|tallas?|medidas)",
     "promesas de pérdida de peso, kilos o tallas"),
    (r"\bkilos?\b|\bkg\b|\btallas?\b", "kilos o tallas"),
    (r"\bpeso\b", "el peso corporal"),
    (r"\badelgaz\w*|\bquema\w*\s+grasa|\bgrasa\s+abdominal|\bvientre\s+plano|\babdomen\s+plano|\bmetabolismo",
     "adelgazar / quemar grasa"),
    (r"\ben\s+(\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|quince|treinta)\s+(d[ií]as|semanas|meses)",
     "resultados en X días"),
    (r"\bcur(a|an|ar|aci[oó]n|ativ\w*)\b", "que cura enfermedades"),
    (r"\bprevien\w*|\bprevenir\b|\bprevenci[oó]n\b", "que previene enfermedades"),
    (r"\bdesinflam\w*|\binflamaci[oó]n\b|\bantiinflamatori\w*", "que desinflama"),
    (r"\btrat(a|an|ar|amiento)\s+(la|el|las|los|tu|tus|su|sus)?\s*\w*(enfermedad|diabetes|presi[oó]n|colesterol|ansiedad|insomnio|gastritis|colitis)",
     "que trata enfermedades"),
    (r"\benfermedad\w*|\bdiabetes\b|\bhipertensi[oó]n\b|\bc[aá]ncer\b", "mencionar enfermedades"),
    (r"\bantes\s+y\s+despu[eé]s\b", "imágenes de antes y después"),
    (r"\bmilagr\w*", "promesas milagrosas"),
]

PALABRAS_IMAGEN_PROHIBIDAS = [
    "antes", "despues", "after", "before", "cuerpo", "body", "abdomen",
    "cintura", "bascula", "pesa_corporal", "panza", "bikini",
]


def quitar_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def revisar_reglas(cfg: dict) -> None:
    titulo("Revisando reglas de contenido (COFEPRIS)")
    textos: list[tuple[str, str]] = []
    for i, esc in enumerate(cfg["escenas"], 1):
        textos.append((f"escena {i} - narración", esc.get("narracion", "")))
        textos.append((f"escena {i} - texto", esc.get("texto", "")))
    textos.append(("leyenda", cfg.get("leyenda", {}).get("texto", "")))

    problemas = []
    for donde, texto in textos:
        bajo = texto.lower()
        for patron, desc in REGLAS_PROHIBIDAS:
            if re.search(patron, bajo) or re.search(patron, quitar_acentos(bajo)):
                problemas.append(f"{donde}: \"{texto}\"  ->  no se permite {desc}")

    for i, esc in enumerate(cfg["escenas"], 1):
        for el in esc.get("elementos", []):
            for nombre in (el.get("imagen", ""), el.get("imagen_final", "")):
                n = quitar_acentos(nombre.lower())
                for p in PALABRAS_IMAGEN_PROHIBIDAS:
                    if p in n:
                        problemas.append(
                            f"escena {i} - imagen \"{nombre}\": no se permiten imágenes "
                            "de cuerpos ni de antes/después")

    if problemas:
        print("\n[ALTO] El guion rompe las reglas de publicidad de suplementos:")
        for p in problemas:
            print("   -", p)
        print("\nCorrige config.yaml y vuelve a correr el programa. "
              "No se generó el video.\n")
        sys.exit(2)
    info("OK: sin promesas de peso, curas, 'detox' ni imágenes de cuerpos.")


def revisar_textos(cfg: dict) -> None:
    for i, esc in enumerate(cfg["escenas"], 1):
        n = len(esc.get("texto", "").split())
        if n > 5:
            aviso(f"Escena {i}: el texto en pantalla tiene {n} palabras "
                  f"(máximo recomendado: 5): \"{esc['texto']}\"")
    if "X" in str(cfg.get("whatsapp", "")).upper():
        aviso("El número de WhatsApp todavía es el de ejemplo "
              f"({cfg.get('whatsapp')}). Cámbialo en config.yaml.")


# ---------------------------------------------------------------------------
# Colores y fuentes
# ---------------------------------------------------------------------------
def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def mezclar(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


ALIAS_FUENTES = {
    "arialroundedmtbold": ["arlrdbd", "arialroundedbold", "arialroundedmtbold"],
    "segoeui": ["segoeuib", "segoeuibold", "segoeuiblack", "seguibl"],
    "verdana": ["verdanab", "verdanabold"],
    "dejavusans": ["dejavusansbold"],
}
PESOS = ["black", "heavy", "extrabold", "ultrabold", "bold", "semibold", "demibold", "medium", ""]
EXCLUIR = ["mono", "condensed", "italic", "oblique", "light", "thin", "narrow", "slanted"]


def carpetas_fuentes() -> list[Path]:
    home = Path.home()
    carpetas = [BASE / "fuentes"]
    if sys.platform.startswith("win"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        carpetas += [windir / "Fonts",
                     Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    elif sys.platform == "darwin":
        carpetas += [home / "Library/Fonts", Path("/Library/Fonts"),
                     Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
    else:
        carpetas += [home / ".local/share/fonts", home / ".fonts",
                     Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
    return [c for c in carpetas if c.exists()]


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", quitar_acentos(t.lower()))


def fuente_valida(ruta: Path) -> bool:
    try:
        ImageFont.truetype(str(ruta), 20)
        return True
    except Exception:
        return False


def buscar_fuente(preferidas: list[str]) -> Path | None:
    archivos: list[Path] = []
    propias: list[Path] = []
    for c in carpetas_fuentes():
        for ext in ("*.ttf", "*.otf", "*.TTF", "*.OTF", "*.ttc"):
            encontrados = list(c.rglob(ext))
            if c == BASE / "fuentes":
                propias += encontrados
            archivos += encontrados
    if propias:
        propias.sort(key=lambda p: next((i for i, w in enumerate(PESOS) if w and w in norm(p.stem)), 99))
        for p in propias:
            if fuente_valida(p):
                return p

    for familia in preferidas:
        clave = norm(familia)
        candidatos = []
        alias = ALIAS_FUENTES.get(clave, [])
        for f in archivos:
            n = norm(f.stem)
            if n in alias:
                candidatos.append((0, f))
                continue
            if not n.startswith(clave):
                continue
            resto = n[len(clave):]
            if any(x in resto for x in EXCLUIR):
                continue
            if "wght" in resto:  # fuente variable
                candidatos.append((1, f))
                continue
            peso = next((i for i, w in enumerate(PESOS) if w and w in resto), None)
            if peso is None:
                peso = len(PESOS) if resto in ("", "regular") else 99
            if peso < 99:
                candidatos.append((2 + peso, f))
        if candidatos:
            candidatos.sort(key=lambda x: x[0])
            for _, f in candidatos:
                if fuente_valida(f):
                    return f
    return None


class Fuentes:
    def __init__(self, preferidas: list[str]):
        self.ruta = buscar_fuente(preferidas)
        if self.ruta:
            info(f"Fuente: {self.ruta.name}")
        else:
            aviso("No encontré ninguna de las fuentes preferidas; uso la fuente "
                  "básica de Pillow. Instala 'Nunito' para un look más amigable.")

    @lru_cache(maxsize=64)
    def get(self, tam: int) -> ImageFont.FreeTypeFont:
        if not self.ruta:
            return ImageFont.load_default(size=tam)
        f = ImageFont.truetype(str(self.ruta), tam)
        try:  # fuentes variables: elegir la variante más gruesa disponible
            nombres = [n.decode() if isinstance(n, bytes) else n for n in f.get_variation_names()]
            for deseada in ("ExtraBold", "Black", "Bold", "SemiBold"):
                if deseada in nombres:
                    f.set_variation_by_name(deseada)
                    break
        except Exception:
            pass
        return f


# ---------------------------------------------------------------------------
# Imágenes
# ---------------------------------------------------------------------------
def marcador(nombre: str, color, fuentes: Fuentes, tam: int = 640) -> Image.Image:
    im = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((8, 8, tam - 8, tam - 8), fill=color + (255,), outline=(255, 255, 255, 255), width=14)
    d.ellipse((50, 50, tam - 50, tam - 50), outline=(255, 255, 255, 120), width=6)
    texto = Path(nombre).stem.replace("_", " ")
    tam_f = 110
    while tam_f > 30:
        f = fuentes.get(tam_f)
        if d.textlength(texto, font=f) < tam * 0.78:
            break
        tam_f -= 6
    d.text((tam / 2, tam / 2), texto, font=fuentes.get(tam_f), fill="white", anchor="mm")
    return im


class Imagenes:
    def __init__(self, carpeta: Path, fuentes: Fuentes, colores: dict, salida: Path):
        self.carpeta = carpeta
        self.fuentes = fuentes
        self.cache: dict[str, Image.Image] = {}
        self.faltantes: list[str] = []
        self.sin_alfa: list[str] = []
        self.paleta = [hex_rgb(colores["morado"]), (214, 92, 140), (196, 128, 70),
                       (120, 160, 90), (90, 140, 190), (230, 150, 60), (150, 90, 160)]
        self.dir_marcadores = salida / "marcadores"

    def cargar(self, nombre: str) -> Image.Image:
        if nombre in self.cache:
            return self.cache[nombre]
        ruta = self.carpeta / nombre
        if not ruta.exists():
            self.faltantes.append(nombre)
            color = self.paleta[len(self.faltantes) % len(self.paleta)]
            im = marcador(nombre, color, self.fuentes)
            self.dir_marcadores.mkdir(parents=True, exist_ok=True)
            im.save(self.dir_marcadores / nombre)
        else:
            im = Image.open(ruta)
            tiene_alfa = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            im = im.convert("RGBA")
            if not tiene_alfa:
                self.sin_alfa.append(f"{nombre} (no tiene canal alfa: se verá con fondo)")
            else:
                alfa = im.getchannel("A")
                if alfa.getextrema()[0] == 255:
                    self.sin_alfa.append(f"{nombre} (tiene canal alfa pero ningún pixel "
                                         "transparente: se verá con fondo)")
                else:
                    caja = alfa.getbbox()  # recortar bordes vacíos
                    if caja:
                        im = im.crop(caja)
        self.cache[nombre] = im
        return im

    def reportar(self) -> None:
        if self.faltantes:
            aviso("Faltan estas imágenes en ./imagenes/ (puse un círculo de color "
                  "con el nombre en su lugar): " + ", ".join(sorted(set(self.faltantes))))
        if self.sin_alfa:
            for s in self.sin_alfa:
                aviso("Imagen sin transparencia: " + s)
        if not self.faltantes and not self.sin_alfa:
            info("Todas las imágenes existen y tienen transparencia.")


# ---------------------------------------------------------------------------
# Audio / narración
# ---------------------------------------------------------------------------
@dataclass
class Palabra:
    texto: str
    inicio: float  # segundos, relativo al inicio del audio de la escena
    fin: float


@dataclass
class AudioEscena:
    archivo: Path | None
    desde: float          # recorte dentro del archivo (voz grabada)
    duracion: float
    palabras: list[Palabra] = field(default_factory=list)


def tokens(texto: str) -> list[str]:
    return texto.split()


def tiempos_proporcionales(texto: str, ini: float, fin: float) -> list[Palabra]:
    toks = tokens(texto)
    pesos = []
    for t in toks:
        p = len(norm(t)) + 1.5
        if re.search(r"[.?!:]$", t):
            p += 6
        elif t.endswith(","):
            p += 3.5
        pesos.append(p)
    total = sum(pesos) or 1
    res, t0 = [], ini
    for tok, p in zip(toks, pesos):
        d = (fin - ini) * p / total
        res.append(Palabra(tok, t0, t0 + d * 0.8))
        t0 += d
    return res


def alinear(texto: str, limites: list[tuple[str, float, float]], duracion: float) -> list[Palabra]:
    """Asigna a cada palabra del guion (con puntuación) su tiempo según edge-tts."""
    toks = tokens(texto)
    res: list[Palabra | None] = [None] * len(toks)
    j = 0
    for i, tok in enumerate(toks):
        n = norm(tok)
        for k in range(j, min(j + 4, len(limites))):
            if norm(limites[k][0]) == n:
                res[i] = Palabra(tok, limites[k][1], limites[k][2])
                j = k + 1
                break
    if all(r is None for r in res):
        return tiempos_proporcionales(texto, 0.1, duracion - 0.2)
    # interpolar los que no coincidieron
    for i in range(len(toks)):
        if res[i] is None:
            prev = next((res[k] for k in range(i - 1, -1, -1) if res[k]), None)
            nxt = next((res[k] for k in range(i + 1, len(toks)) if res[k]), None)
            a = prev.fin if prev else 0.0
            b = nxt.inicio if nxt else duracion
            res[i] = Palabra(toks[i], a, max(a, b))
    return res  # type: ignore


async def _tts(texto: str, voz: str, velocidad: str, destino: Path):
    import edge_tts

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
    try:
        com = edge_tts.Communicate(texto, voz, rate=velocidad,
                                   boundary="WordBoundary", proxy=proxy)
    except TypeError:  # versiones antiguas de edge-tts
        com = edge_tts.Communicate(texto, voz, rate=velocidad, proxy=proxy)
    limites = []
    with open(destino, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                ini = ch["offset"] / 1e7
                limites.append((ch["text"], ini, ini + ch["duration"] / 1e7))
    return limites


def narracion_tts(cfg: dict, tmp: Path, ffmpeg: str, velocidad: str) -> list[AudioEscena] | None:
    voz = cfg["voz"]["nombre"]
    res = []
    for i, esc in enumerate(cfg["escenas"], 1):
        texto = esc["narracion"]
        h = hashlib.md5(f"{voz}|{velocidad}|{texto}".encode()).hexdigest()[:10]
        mp3 = tmp / f"voz_escena{i}_{h}.mp3"
        js = mp3.with_suffix(".json")
        if not (mp3.exists() and js.exists() and mp3.stat().st_size > 0):
            try:
                limites = asyncio.run(_tts(texto, voz, velocidad, mp3))
            except Exception as e:
                mp3.unlink(missing_ok=True)
                aviso("No pude generar la voz con edge-tts (¿hay internet?). "
                      f"Detalle: {type(e).__name__}. Armo el video con tiempos "
                      "estimados y SIN voz para que puedas revisarlo.")
                return None
            js.write_text(json.dumps(limites, ensure_ascii=False))
        limites = json.loads(js.read_text())
        dur = duracion_ffmpeg(ffmpeg, mp3)
        res.append(AudioEscena(mp3, 0.0, dur, alinear(texto, limites, dur)))
    return res


def narracion_estimada(cfg: dict) -> list[AudioEscena]:
    res = []
    for esc in cfg["escenas"]:
        texto = esc["narracion"]
        dur = len(texto) / 14.5 + 0.4
        res.append(AudioEscena(None, 0.0, dur, tiempos_proporcionales(texto, 0.1, dur - 0.2)))
    return res


def silencios(ffmpeg: str, archivo: Path) -> list[tuple[float, float]]:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(archivo), "-af",
                        "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"],
                       capture_output=True, text=True)
    ini = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    fin = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(ini, fin))


def narracion_grabada(cfg: dict, ruta: Path, ffmpeg: str) -> list[AudioEscena]:
    n = len(cfg["escenas"])
    total = duracion_ffmpeg(ffmpeg, ruta)
    sil = silencios(ffmpeg, ruta)
    cortes = list(cfg["voz"].get("cortes_grabada") or [])
    if cortes:
        if len(cortes) != n:
            error_fatal(f"'cortes_grabada' debe tener {n} números (uno por escena).")
        cortes = [float(c) for c in cortes] + [total]
        info("Uso los cortes de escena escritos en config.yaml.")
    else:
        internos = [s for s in sil if s[0] > 0.05 and s[1] < total - 0.05]
        if len(internos) >= n - 1:
            mayores = sorted(internos, key=lambda s: s[1] - s[0], reverse=True)[: n - 1]
            cortes = [0.0] + sorted((a + b) / 2 for a, b in mayores) + [total]
            info("Detecté las pausas de la grabación para separar las escenas.")
        else:
            largos = [len(e["narracion"]) for e in cfg["escenas"]]
            acum, cortes = 0.0, [0.0]
            for l in largos[:-1]:
                acum += total * l / sum(largos)
                cortes.append(acum)
            cortes.append(total)
            aviso("No encontré pausas claras en narracion.mp3; separé las escenas "
                  "según el largo del texto. Si no queda bien sincronizado, escribe "
                  "'cortes_grabada' en config.yaml.")
    res = []
    for i, esc in enumerate(cfg["escenas"]):
        a, b = cortes[i], cortes[i + 1]
        # dónde empieza y termina realmente la voz dentro del tramo
        habla_ini, habla_fin = a, b
        for s0, s1 in sil:
            if s0 <= habla_ini + 0.05 and s1 > habla_ini:
                habla_ini = min(s1, b)
            if s1 >= habla_fin - 0.05 and s0 < habla_fin:
                habla_fin = max(s0, habla_ini + 0.3)
        palabras = tiempos_proporcionales(esc["narracion"], habla_ini - a, habla_fin - a)
        res.append(AudioEscena(ruta, a, b - a, palabras))
    return res


# ---------------------------------------------------------------------------
# Línea de tiempo
# ---------------------------------------------------------------------------
PAD_INI, PAD_FIN = 0.35, 0.45
PAD_INI_MIN, PAD_FIN_MIN = 0.22, 0.2


@dataclass
class Escena:
    num: int
    cfg: dict
    audio: AudioEscena
    inicio: float = 0.0
    duracion: float = 0.0
    pad_ini: float = PAD_INI

    @property
    def fin(self) -> float:
        return self.inicio + self.duracion

    @property
    def voz_inicio(self) -> float:
        return self.inicio + self.pad_ini


def armar_linea_tiempo(audios: list[AudioEscena], cfg: dict, pad_ini=PAD_INI, pad_fin=PAD_FIN):
    vmin = float(cfg["video"]["duracion_minima"])
    escenas = [Escena(i + 1, e, a, pad_ini=pad_ini, duracion=pad_ini + a.duracion + pad_fin)
               for i, (e, a) in enumerate(zip(cfg["escenas"], audios))]
    total = sum(e.duracion for e in escenas)
    if total < vmin + 0.3:
        extra = vmin + 0.3 - total
        ultimo = min(extra, 2.0)
        escenas[-1].duracion += ultimo
        extra -= ultimo
        for e in escenas:
            e.duracion += extra / len(escenas)
    t = 0.0
    for e in escenas:
        e.inicio = t
        t += e.duracion
    return escenas, t


# ---------------------------------------------------------------------------
# Animación
# ---------------------------------------------------------------------------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out_back(t, s=1.7):
    t = clamp(t) - 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


def resorte(t):
    """Rebote tipo resorte: 0 -> 1 con sobrepaso y oscilación amortiguada."""
    if t <= 0:
        return 0.0
    return 1 - math.exp(-6.5 * t) * math.cos(13 * t)


def ease_out_bounce(t):
    t = clamp(t)
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


def con_opacidad(im: Image.Image, o: float) -> Image.Image:
    if o >= 0.999:
        return im
    im = im.copy()
    a = im.getchannel("A").point(lambda v: int(v * o))
    im.putalpha(a)
    return im


def pegar(base: Image.Image, im: Image.Image, cx: float, cy: float) -> None:
    """Pega im centrada en (cx, cy) recortando lo que salga del cuadro."""
    w, h = im.size
    x, y = int(round(cx - w / 2)), int(round(cy - h / 2))
    W, H = base.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    trozo = im.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    base.alpha_composite(trozo, dest=(x0, y0))


def escalar(im: Image.Image, s: float) -> Image.Image:
    if abs(s - 1) < 0.004:
        return im
    w, h = max(1, int(im.width * s)), max(1, int(im.height * s))
    return im.resize((w, h), Image.BILINEAR)


# ---------------------------------------------------------------------------
# Render de texto
# ---------------------------------------------------------------------------
def envolver(draw, texto, fuente, ancho_max):
    palabras, lineas, actual = texto.split(), [], ""
    for p in palabras:
        prueba = (actual + " " + p).strip()
        if draw.textlength(prueba, font=fuente) <= ancho_max or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas


def render_titulo(texto: str, fuentes: Fuentes, W: int, color, borde) -> Image.Image:
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tam = 128
    while True:
        f = fuentes.get(tam)
        lineas = envolver(tmp, texto, f, W * 0.84)
        if (len(lineas) <= 2 and max(tmp.textlength(l, font=f) for l in lineas) <= W * 0.86) or tam <= 60:
            break
        tam -= 4
    alto_l = int(tam * 1.12)
    trazo = max(6, tam // 11)
    ancho = int(max(tmp.textlength(l, font=f) for l in lineas)) + trazo * 2 + 40
    alto = alto_l * len(lineas) + trazo * 2 + 40
    capa = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    for i, l in enumerate(lineas):
        d.text((ancho / 2, 20 + trazo + alto_l * (i + 0.5)), l, font=f, fill=color + (255,),
               anchor="mm", stroke_width=trazo, stroke_fill=borde + (255,))
    sombra = Image.new("RGBA", capa.size, (0, 0, 0, 0))
    sombra.putalpha(capa.getchannel("A").point(lambda v: int(v * 0.25)))
    sombra = sombra.filter(ImageFilter.GaussianBlur(8))
    final = Image.new("RGBA", (ancho, alto + 10), (0, 0, 0, 0))
    final.alpha_composite(sombra, dest=(0, 10))
    final.alpha_composite(capa, dest=(0, 0))
    return final


def render_pastilla(texto: str, fuente, fondo, color_texto, pad_x=36, pad_y=18, radio=None,
                    ancho_max=None, opacidad=255) -> Image.Image:
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    lineas = envolver(tmp, texto, fuente, ancho_max) if ancho_max else [texto]
    asc, desc = fuente.getmetrics()
    alto_l = int((asc + desc) * 1.08)
    ancho = int(max(tmp.textlength(l, font=fuente) for l in lineas)) + pad_x * 2
    alto = alto_l * len(lineas) + pad_y * 2
    im = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, ancho - 1, alto - 1), radius=radio or alto_l // 2 + pad_y,
                        fill=fondo + (opacidad,))
    for i, l in enumerate(lineas):
        d.text((ancho / 2, pad_y + alto_l * (i + 0.5)), l, font=fuente, fill=color_texto, anchor="mm")
    return im


def _largo(ps):
    return len(" ".join(p.texto for p in ps))


def bloques_subtitulos(palabras: list[Palabra], max_chars=50, tolerancia=54):
    """Agrupa palabras en bloques cortos (máx. 2 renglones), cortando en la
    puntuación y repartiendo parejo las frases largas."""
    frases, actual = [], []
    for p in palabras:
        actual.append(p)
        if re.search(r"[.?!:,;]$", p.texto):
            frases.append(actual)
            actual = []
    if actual:
        frases.append(actual)
    # una frase corta que termina en coma se une con la que sigue
    adelante: list[list[Palabra]] = []
    arrastre: list[Palabra] = []
    for f in frases:
        f = arrastre + f
        arrastre = []
        if len(f) <= 2 and f[-1].texto.endswith(",") and f is not frases[-1]:
            arrastre = f
        else:
            adelante.append(f)
    if arrastre:
        adelante.append(arrastre)
    unidas: list[list[Palabra]] = []
    for f in adelante:
        if unidas and (len(unidas[-1]) <= 2 or len(f) <= 2) and _largo(unidas[-1] + f) <= tolerancia:
            unidas[-1] = unidas[-1] + f
        else:
            unidas.append(f)
    bloques = []
    for f in unidas:
        partes = math.ceil(_largo(f) / max_chars)
        if partes <= 1:
            bloques.append(f)
            continue
        objetivo = _largo(f) / partes
        actual = []
        for k, p in enumerate(f):
            actual.append(p)
            quedan = f[k + 1:]
            if _largo(actual) >= objetivo - 2 and len(quedan) >= 2:
                bloques.append(actual)
                actual = []
        if actual:
            bloques.append(actual)
    return bloques


# ---------------------------------------------------------------------------
# Generador de cuadros
# ---------------------------------------------------------------------------
class Animador:
    def __init__(self, cfg, escenas: list[Escena], total: float, fuentes: Fuentes, imgs: Imagenes):
        v = cfg["video"]
        self.W, self.H = int(v["ancho"]), int(v["alto"])
        self.T = float(v["transicion"])
        self.cfg = cfg
        self.escenas = escenas
        self.total = total
        self.fuentes = fuentes
        self.imgs = imgs
        col = cfg["colores"]
        self.morado, self.rosa, self.crema = hex_rgb(col["morado"]), hex_rgb(col["rosa"]), hex_rgb(col["crema"])
        self.verde = hex_rgb(col.get("verde_whatsapp", "#25D366"))
        self.fondo = self._fondo()
        self.cajas_texto: list[tuple[str, tuple[int, int, int, int]]] = []
        self._preparar()

    # -- fondo ---------------------------------------------------------------
    def _fondo(self) -> Image.Image:
        W, H = self.W, self.H
        abajo = mezclar(self.rosa, self.morado, 0.28)
        y = np.linspace(0, 1, H)[:, None]
        arr = np.zeros((H, W, 3), dtype=np.float32)
        for c in range(3):
            arriba_c, medio_c, abajo_c = self.crema[c], self.rosa[c], abajo[c]
            v = np.where(y < 0.55, arriba_c + (medio_c - arriba_c) * (y / 0.55),
                         medio_c + (abajo_c - medio_c) * ((y - 0.55) / 0.45))
            arr[:, :, c] = np.broadcast_to(v, (H, W))
        fondo = Image.fromarray(arr.clip(0, 255).astype(np.uint8)).convert("RGBA")
        deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(deco)
        circulos = [(-0.12, 0.06, 0.32, self.rosa, 150), (1.05, 0.2, 0.26, self.rosa, 170),
                    (0.95, 0.9, 0.36, self.crema, 70), (-0.05, 0.78, 0.22, self.crema, 80),
                    (0.82, 0.04, 0.08, self.morado, 30), (0.12, 0.35, 0.05, self.morado, 25),
                    (0.9, 0.6, 0.04, self.morado, 28)]
        for cx, cy, r, color, a in circulos:
            R = r * W
            d.ellipse((cx * W - R, cy * H - R, cx * W + R, cy * H + R), fill=color + (a,))
        fondo.alpha_composite(deco.filter(ImageFilter.GaussianBlur(2)))
        return fondo

    # -- preparación de capas por escena --------------------------------------
    def _base_elemento(self, nombre: str, ancho_frac: float, alto_max=0.34) -> Image.Image:
        im = self.imgs.cargar(nombre)
        w = ancho_frac * self.W
        s = w / im.width
        if im.height * s > alto_max * self.H:
            s = alto_max * self.H / im.height
        return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)

    def tiempo_palabra(self, esc: Escena, valor, nombre_campo: str) -> float:
        """Convierte 'inicio' (segundos o {palabra: ...}) a segundos desde el inicio de la escena."""
        if valor is None:
            return 0.0
        if isinstance(valor, (int, float)):
            return float(valor)
        if isinstance(valor, dict) and "palabra" in valor:
            buscada = norm(str(valor["palabra"]))
            for p in esc.audio.palabras:
                if norm(p.texto) == buscada or norm(p.texto).startswith(buscada):
                    return esc.pad_ini + p.inicio - 0.1
            aviso(f"Escena {esc.num}: no encontré la palabra \"{valor['palabra']}\" en la "
                  f"narración ({nombre_campo}); la imagen aparece al inicio.")
            return 0.3
        try:
            return float(valor)
        except (TypeError, ValueError):
            aviso(f"Escena {esc.num}: valor no válido para {nombre_campo}: {valor}")
            return 0.0

    def _preparar(self):
        W, H = self.W, self.H
        leyenda = self.cfg.get("leyenda", {})
        f_sub = self.fuentes.get(56)
        f_ley = self.fuentes.get(34)
        f_num = self.fuentes.get(78)
        for esc in self.escenas:
            c = esc.cfg
            # elementos
            esc.elems = []
            for k, el in enumerate(c.get("elementos", [])):
                d = dict(el)
                d["base"] = self._base_elemento(el["imagen"], float(el.get("ancho", 0.45)),
                                                float(el.get("alto_max", 0.34)))
                if el.get("imagen_final"):
                    d["base_final"] = self._base_elemento(el["imagen_final"], float(el.get("ancho", 0.45)),
                                                          float(el.get("alto_max", 0.34)))
                d["t0"] = self.tiempo_palabra(esc, el.get("inicio"), f"inicio de {el['imagen']}")
                d["t_cambio"] = self.tiempo_palabra(esc, el.get("cambio"), "cambio") if el.get("cambio") else None
                d["t_salida"] = self.tiempo_palabra(esc, el.get("salida"), "salida") if el.get("salida") else None
                d["orden"] = -1 if el.get("atras") else k
                d["fase"] = k * 1.7
                esc.elems.append(d)
            esc.elems.sort(key=lambda d: d["orden"])

            # título
            esc.titulo = render_titulo(c.get("texto", ""), self.fuentes, W, self.morado, self.crema) \
                if c.get("texto") else None
            y_tit = 0.115 * H + (esc.titulo.height / 2 if esc.titulo else 0)
            esc.y_titulo = y_tit
            if esc.titulo:
                self._registrar(f"Escena {esc.num} texto", esc.titulo, W / 2, y_tit, 1.06)

            # número de WhatsApp
            esc.pastilla = None
            if c.get("mostrar_whatsapp"):
                esc.pastilla = render_pastilla(str(self.cfg.get("whatsapp", "")), f_num, self.verde,
                                               (255, 255, 255, 255), pad_x=44, pad_y=14)
                esc.y_pastilla = 0.115 * H + esc.titulo.height + esc.pastilla.height / 2 - 6
                self._registrar(f"Escena {esc.num} WhatsApp", esc.pastilla, W / 2, esc.y_pastilla, 1.06)

            # subtítulos
            esc.subs = []
            bloques = bloques_subtitulos(esc.audio.palabras)
            for i, b in enumerate(bloques):
                ini = esc.pad_ini + b[0].inicio - 0.05
                if i + 1 < len(bloques):
                    fin = esc.pad_ini + bloques[i + 1][0].inicio - 0.05
                else:
                    fin = min(esc.duracion - 0.05, esc.pad_ini + b[-1].fin + 0.6)
                im = render_pastilla(" ".join(p.texto for p in b), f_sub, self.morado,
                                     (255, 255, 255, 255), pad_x=34, pad_y=16, radio=30,
                                     ancho_max=W * 0.80, opacidad=232)
                esc.subs.append((ini, fin, im))
                self._registrar(f"Escena {esc.num} subtítulo", im, W / 2, self._y_sub(im), 1.0)

            # leyenda legal
            esc.leyenda = None
            if leyenda.get("texto") and esc.num in (leyenda.get("escenas") or []):
                esc.leyenda = render_pastilla(leyenda["texto"], f_ley, self.crema, self.morado + (255,),
                                              pad_x=24, pad_y=8, opacidad=215)
                self._registrar(f"Escena {esc.num} leyenda", esc.leyenda, W / 2, self._y_leyenda(esc.leyenda), 1.0)

    def _y_sub(self, im):  # parte de abajo del subtítulo en el 79% de la altura
        return 0.79 * self.H - im.height / 2

    def _y_leyenda(self, im):  # parte de abajo de la leyenda en el 84% de la altura
        return 0.84 * self.H - im.height / 2

    def _registrar(self, nombre, im, cx, cy, escala_max):
        w, h = im.width * escala_max, im.height * escala_max
        self.cajas_texto.append((nombre, (int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2))))

    def revisar_zonas_seguras(self) -> list[str]:
        malos = []
        top, bottom = 0.10 * self.H, 0.85 * self.H
        for nombre, (x0, y0, x1, y1) in self.cajas_texto:
            if y0 < top or y1 > bottom or x0 < 0 or x1 > self.W:
                malos.append(f"{nombre}: y={y0}-{y1}px (permitido {int(top)}-{int(bottom)}px)")
        return malos

    # -- dibujo ----------------------------------------------------------------
    def opacidad_escena(self, esc: Escena, t: float) -> float:
        T2 = self.T / 2
        o = 1.0
        if esc.num > 1:
            o *= clamp((t - (esc.inicio - T2)) / self.T)
        if esc.num < len(self.escenas):
            o *= clamp(((esc.fin + T2) - t) / self.T)
        return o

    def dibujar_elemento(self, base, esc: Escena, d: dict, tl: float, o_esc: float):
        W, H = self.W, self.H
        t = tl - d["t0"]
        if t < 0:
            return
        anim = d.get("animacion", "aparecer")
        cx, cy = float(d.get("x", 0.5)) * W, float(d.get("y", 0.5)) * H
        escala, alfa = 1.0, 1.0
        im = d["base"]
        flotar = True

        if anim == "rebote":
            escala = max(0.01, resorte(t / 1.0 * 1.0))
            alfa = clamp(t / 0.12)
        elif anim in ("deslizar_izquierda", "deslizar_derecha"):
            p = ease_out_back(t / 0.75, 1.3)
            origen = -0.45 * W if anim == "deslizar_izquierda" else 1.45 * W
            cx = origen + (cx - origen) * p
            alfa = clamp(t / 0.2)
        elif anim == "zoom":
            alfa = ease_in_out(t / 0.6)
            dur = max(1.0, esc.duracion - d["t0"])
            escala = 0.9 + 0.16 * ease_in_out(t / dur)  # Ken Burns
            cy -= 0.012 * H * ease_in_out(t / dur)
            flotar = False
        elif anim == "caer":
            desde = float(d.get("desde_y", 0.15)) * H
            p = ease_out_bounce(t / 0.9)
            cy = desde + (cy - desde) * p
            alfa = clamp(t / 0.15)
            flotar = False
        elif anim == "transformar":
            alfa = ease_in_out(t / 0.5)
            escala = 0.94 + 0.06 * ease_out_cubic(t / 0.5)
            if d.get("t_cambio") is not None and "base_final" in d:
                tc = tl - d["t_cambio"]
                if tc > 0:
                    p = ease_in_out(tc / 0.7)
                    escala *= 1 + 0.08 * math.sin(math.pi * clamp(tc / 0.7))
                    a1 = escalar(con_opacidad(d["base"], alfa * (1 - p) * o_esc), escala)
                    a2 = escalar(con_opacidad(d["base_final"], alfa * p * o_esc), escala)
                    dy = 5 * math.sin(2 * math.pi * tl / 3.2 + d["fase"])
                    if p < 1:
                        pegar(base, a1, cx, cy + dy)
                    pegar(base, a2, cx, cy + dy)
                    return
        else:  # aparecer
            alfa = ease_in_out(t / 0.5)
            escala = 0.95 + 0.05 * ease_out_cubic(t / 0.5)

        if d.get("t_salida") is not None:
            ts = tl - d["t_salida"]
            if ts > 0:
                alfa *= 1 - clamp(ts / 0.35)
                escala *= 1 - 0.15 * clamp(ts / 0.35)
                if ts > 0.35:
                    return

        if flotar and t > 0.8:
            cy += 6 * math.sin(2 * math.pi * (tl - d["t0"] - 0.8) / 3.2 + d["fase"]) * clamp((t - 0.8) / 0.5)
        a = alfa * o_esc
        if a <= 0.003:
            return
        pegar(base, escalar(con_opacidad(im, a), escala), cx, cy)

    def dibujar_textos(self, base, esc: Escena, tl: float, o_esc: float):
        W = self.W
        if esc.titulo is not None:
            t = tl - 0.15
            if t > 0:
                s = 0.7 + 0.3 * ease_out_back(t / 0.55, 2.0)
                a = clamp(t / 0.25) * o_esc
                dy = 30 * (1 - ease_out_cubic(t / 0.5))
                pegar(base, escalar(con_opacidad(esc.titulo, a), s), W / 2, esc.y_titulo + dy)
        if esc.pastilla is not None:
            t = tl - 0.65
            if t > 0:
                s = max(0.01, resorte(t))
                pegar(base, escalar(con_opacidad(esc.pastilla, clamp(t / 0.12) * o_esc), s), W / 2, esc.y_pastilla)
        for ini, fin, im in esc.subs:
            if ini <= tl <= fin:
                a = clamp((tl - ini) / 0.12) * clamp((fin - tl) / 0.12) * o_esc
                dy = 12 * (1 - ease_out_cubic((tl - ini) / 0.2))
                pegar(base, con_opacidad(im, a), W / 2, self._y_sub(im) + dy)
        if esc.leyenda is not None:
            pegar(base, con_opacidad(esc.leyenda, clamp(tl / 0.4) * o_esc), W / 2, self._y_leyenda(esc.leyenda))

    def cuadro(self, t: float) -> np.ndarray:
        base = self.fondo.copy()
        T2 = self.T / 2
        for esc in self.escenas:
            if esc.inicio - T2 <= t <= esc.fin + T2 or (esc.num == len(self.escenas) and t >= esc.inicio):
                o = self.opacidad_escena(esc, t)
                if o <= 0:
                    continue
                tl = t - esc.inicio
                for d in esc.elems:
                    self.dibujar_elemento(base, esc, d, tl, o)
                self.dibujar_textos(base, esc, tl, o)
        return np.asarray(base.convert("RGB"))


# ---------------------------------------------------------------------------
# Audio final
# ---------------------------------------------------------------------------
def armar_audio(escenas: list[Escena], total: float, cfg: dict):
    from moviepy import AudioClip, AudioFileClip, CompositeAudioClip
    from moviepy import audio as _a  # noqa: F401
    from moviepy.audio.fx import AudioFadeIn, AudioFadeOut, AudioLoop, MultiplyVolume

    pistas = []
    abiertos = []
    for e in escenas:
        if e.audio.archivo is None:
            continue
        clip = AudioFileClip(str(e.audio.archivo))
        abiertos.append(clip)
        fin = min(clip.duration, e.audio.desde + e.audio.duracion)
        pistas.append(clip.subclipped(e.audio.desde, fin).with_start(e.voz_inicio))

    musica_cfg = cfg.get("musica", {}) or {}
    ruta_m = BASE / str(musica_cfg.get("archivo", "audio/musica.mp3"))
    if ruta_m.exists():
        vol = float(musica_cfg.get("volumen", 0.12))
        if not 0.10 <= vol <= 0.15:
            aviso(f"Volumen de música {vol} fuera del rango recomendado 0.10-0.15.")
        m = AudioFileClip(str(ruta_m))
        abiertos.append(m)
        m = m.with_effects([AudioLoop(duration=total)]) if m.duration < total else m.subclipped(0, total)
        m = m.with_effects([MultiplyVolume(vol), AudioFadeIn(0.8),
                            AudioFadeOut(float(musica_cfg.get("fade_out", 2.5)))])
        pistas.append(m.with_start(0))
        info(f"Música de fondo: {ruta_m.name} al {int(vol * 100)}% con fade out.")
    else:
        info("Sin música de fondo (no existe audio/musica.mp3).")

    if not pistas:
        def silencio(t):
            return np.zeros((len(t), 2)) if hasattr(t, "__len__") else np.zeros(2)
        return AudioClip(silencio, duration=total, fps=44100), abiertos
    return CompositeAudioClip(pistas).with_duration(total), abiertos


# ---------------------------------------------------------------------------
# Validación final
# ---------------------------------------------------------------------------
def validar(ffmpeg: str, salida: Path, escenas: list[Escena], anim: Animador, cfg: dict) -> bool:
    titulo("Validando el video")
    ok = True
    meta = ffmpeg_info(ffmpeg, salida)
    dur = duracion_ffmpeg(ffmpeg, salida)
    vmin, vmax = cfg["video"]["duracion_minima"], cfg["video"]["duracion_maxima"]
    estado = "OK" if vmin <= dur <= vmax else "FUERA DE RANGO"
    ok &= estado == "OK"
    info(f"Duración: {dur:.2f} s ({estado}; debe ser {vmin}-{vmax} s)")
    for etiqueta, patron in [("Resolución 1080x1920", r"1080x1920"), ("30 fps", r"\b30 fps"),
                             ("Video H.264", r"Video: h264"), ("Audio AAC", r"Audio: aac")]:
        si = re.search(patron, meta) is not None
        ok &= si
        info(f"{etiqueta}: {'OK' if si else 'NO'}")

    malos = anim.revisar_zonas_seguras()
    if malos:
        ok = False
        for m in malos:
            aviso("Texto fuera de la zona segura: " + m)
    else:
        info("Zonas seguras: OK (ningún texto en el 10% superior ni en el 15% inferior)")

    carpeta = salida.parent / "fotogramas"
    carpeta.mkdir(parents=True, exist_ok=True)
    miniaturas = []
    for e in escenas:
        ultimo = max([d["t0"] for d in e.elems] + [d["t_cambio"] or 0 for d in e.elems] + [0])
        t = e.inicio + min(max(ultimo + 1.1, e.duracion * 0.6), e.duracion - 0.3)
        png = carpeta / f"escena_{e.num}.png"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(salida),
                        "-frames:v", "1", str(png)], check=False)
        if not png.exists():
            ok = False
            aviso(f"No pude extraer el fotograma de la escena {e.num}")
            continue
        im = Image.open(png).convert("RGB")
        variacion = float(np.asarray(im).std())
        estado = "OK" if variacion > 8 and im.size == (anim.W, anim.H) else "REVISAR"
        ok &= estado == "OK"
        info(f"Escena {e.num}: fotograma en {t:5.2f} s -> {png.relative_to(BASE)} ({estado})")
        miniaturas.append((e.num, t, im))

    if miniaturas:
        mw, mh = 360, 640
        hoja = Image.new("RGB", (mw * 3 + 40, (mh + 60) * 2 + 20), (255, 255, 255))
        d = ImageDraw.Draw(hoja)
        f = anim.fuentes.get(28)
        for i, (n, t, im) in enumerate(miniaturas):
            x, y = 10 + (i % 3) * (mw + 10), 10 + (i // 3) * (mh + 60)
            hoja.paste(im.resize((mw, mh), Image.LANCZOS), (x, y + 44))
            d.text((x + mw / 2, y + 22), f"Escena {n}  ({t:.1f} s)", font=f, fill=anim.morado, anchor="mm")
        hoja.save(carpeta / "resumen.png")
        info(f"Hoja de revisión: {(carpeta / 'resumen.png').relative_to(BASE)}")
    return ok


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Genera el video de Te Divina.")
    ap.add_argument("--config", default="config.yaml", help="archivo de configuración")
    args = ap.parse_args()

    ruta_cfg = (BASE / args.config) if not Path(args.config).is_absolute() else Path(args.config)
    if not ruta_cfg.exists():
        error_fatal(f"No encontré {ruta_cfg}")
    try:
        cfg = yaml.safe_load(ruta_cfg.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        error_fatal(f"config.yaml tiene un error de formato (revisa espacios y comillas):\n{e}")

    print("\n☕  Te Divina - generador de video")
    titulo("Revisando herramientas")
    ffmpeg = buscar_ffmpeg()
    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", ffmpeg)
    try:
        import moviepy  # noqa: F401
    except ImportError:
        error_fatal("Falta moviepy. Ejecuta:  pip install -r requirements.txt")

    revisar_reglas(cfg)
    revisar_textos(cfg)

    salida = BASE / cfg.get("salida", "salida/te_divina_prototipo.mp4")
    salida.parent.mkdir(parents=True, exist_ok=True)
    tmp = salida.parent / "tmp"
    tmp.mkdir(exist_ok=True)

    titulo("Fuente e imágenes")
    fuentes = Fuentes(cfg.get("fuentes_preferidas", []))
    imgs = Imagenes(BASE / "imagenes", fuentes, cfg["colores"], salida.parent)
    for esc in cfg["escenas"]:
        for el in esc.get("elementos", []):
            imgs.cargar(el["imagen"])
            if el.get("imagen_final"):
                imgs.cargar(el["imagen_final"])
    imgs.reportar()

    titulo("Narración")
    vmax = float(cfg["video"]["duracion_maxima"])
    grabada = BASE / str(cfg["voz"].get("grabada", "audio/narracion.mp3"))
    if grabada.exists():
        info(f"Opción B: uso la voz grabada {grabada.relative_to(BASE)}")
        audios = narracion_grabada(cfg, grabada, ffmpeg)
        escenas, total = armar_linea_tiempo(audios, cfg)
        if total > vmax:
            escenas, total = armar_linea_tiempo(audios, cfg, PAD_INI_MIN, PAD_FIN_MIN)
        if total > vmax:
            aviso(f"La voz grabada es demasiado larga: el video quedaría de {total:.1f} s "
                  f"(máximo {vmax:.0f} s). Graba un poco más rápido o recorta el guion.")
    else:
        velocidad_base = str(cfg["voz"].get("velocidad", "+0%"))
        info(f"Opción A: voz generada {cfg['voz']['nombre']} ({velocidad_base})")
        audios = narracion_tts(cfg, tmp, ffmpeg, velocidad_base)
        if audios is None:
            audios = narracion_estimada(cfg)
        escenas, total = armar_linea_tiempo(audios, cfg)
        base_pct = int(velocidad_base.replace("%", "") or 0)
        pct = base_pct
        while total > vmax and audios[0].archivo is not None and pct < base_pct + 20:
            pct += 5
            info(f"El video dura {total:.1f} s; acelero la voz a {pct:+d}% para no pasar de {vmax:.0f} s")
            nuevos = narracion_tts(cfg, tmp, ffmpeg, f"{pct:+d}%")
            if nuevos is None:
                break
            audios = nuevos
            escenas, total = armar_linea_tiempo(audios, cfg)
        if total > vmax:
            escenas, total = armar_linea_tiempo(audios, cfg, PAD_INI_MIN, PAD_FIN_MIN)
        if total > vmax:
            aviso(f"El guion es largo: el video quedaría de {total:.1f} s. Acorta la narración.")

    titulo("Línea de tiempo")
    for e in escenas:
        info(f"Escena {e.num}: {e.inicio:5.2f} - {e.fin:5.2f} s  ({e.duracion:.2f} s)  "
             f"\"{e.cfg.get('texto', '')}\"")
    info(f"Total: {total:.2f} s")

    titulo("Dibujando la animación")
    anim = Animador(cfg, escenas, total, fuentes, imgs)
    malos = anim.revisar_zonas_seguras()
    for m in malos:
        aviso("Texto fuera de la zona segura: " + m)

    from moviepy import VideoClip

    fps = int(cfg["video"]["fps"])
    video = VideoClip(anim.cuadro, duration=total)
    audio, abiertos = armar_audio(escenas, total, cfg)
    video = video.with_audio(audio)

    titulo("Escribiendo el MP4 (esto tarda unos minutos)")
    video.write_videofile(
        str(salida), fps=fps, codec="libx264", audio_codec="aac", audio_fps=44100,
        audio_bitrate="192k", preset="medium", threads=os.cpu_count() or 2,
        ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "20"],
        temp_audiofile=str(tmp / "audio_temp.m4a"), logger="bar",
    )
    for c in abiertos:
        try:
            c.close()
        except Exception:
            pass

    todo_ok = validar(ffmpeg, salida, escenas, anim, cfg)

    titulo("Resumen")
    info(f"Video: {salida.relative_to(BASE)}")
    if AVISOS:
        print("\n  Cosas que revisar:")
        for a in dict.fromkeys(AVISOS):
            print("   -", a)
    print("\n  " + ("✅ Listo. Todo en orden." if todo_ok and not AVISOS
                     else "✅ Video generado (revisa los avisos de arriba)."))
    print()


if __name__ == "__main__":
    main()
