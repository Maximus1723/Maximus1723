# ☕ Te Divina – Generador de videos

Este programa arma **solo** un video vertical (para TikTok, Reels y Shorts) de
35 a 40 segundos, con animaciones, textos, subtítulos y voz.

Resultado: `salida/te_divina_prototipo.mp4`

---

## 1. Instalar (solo la primera vez)

Necesitas tres cosas: **Python**, **ffmpeg** y las librerías del proyecto.

### a) Python
- Descárgalo de <https://www.python.org/downloads/> (versión 3.10 o más nueva).
- En Windows, **marca la casilla "Add Python to PATH"** al instalar.

### b) ffmpeg (programa para hacer videos)
- **Windows:** abre "Símbolo del sistema" y escribe `winget install ffmpeg`.
  Luego cierra la ventana y ábrela otra vez.
- **Mac:** instala Homebrew (<https://brew.sh>) y escribe `brew install ffmpeg`.
- **Linux:** `sudo apt install ffmpeg`

Para comprobarlo, escribe `ffmpeg -version`. Si aparece texto con números, ya
está instalado.

### c) Librerías
Abre una terminal **dentro de esta carpeta** (`te_divina`) y escribe:

```
pip install -r requirements.txt
```

### d) Fuente redondeada (recomendado)
El programa usa una fuente que ya esté instalada en tu computadora. Para que
se vea más amigable, instala **Nunito** (gratis):
<https://fonts.google.com/specimen/Nunito>. Descárgala, abre el archivo y
haz clic en "Instalar". Si no la encuentra, usa otra fuente parecida que
tengas instalada.

---

## 2. Poner las imágenes

Copia los dibujos en la carpeta **`imagenes/`**. Deben ser **PNG sin fondo**
(con transparencia) y llamarse exactamente así:

| Archivo | Escena |
|---|---|
| `taza.png` | 1, 3 y 4 |
| `jamaica.png`, `canela.png`, `manzanilla.png` | 2 |
| `bolsita.png`, `reloj.png` | 3 |
| `vaso_hielo.png` | 4 |
| `comida.png`, `agua.png`, `tenis.png` | 5 |
| `logo.png`, `paquete.png` | 6 |

- Si falta alguna, el programa **no falla**: pone un círculo de color con el
  nombre y te avisa cuáles faltan.
- Si alguna tiene fondo (no es transparente), también te avisa.
- Para quitarle el fondo a una imagen puedes usar <https://www.remove.bg>.

---

## 3. Poner el audio (opcional)

En la carpeta **`audio/`**:

- **`narracion.mp3`**: si grabas tu propia voz leyendo el guion, ponla aquí y
  el video usará tu voz en lugar de la voz automática.
  Consejo: haz una **pausa de 1 segundo entre cada escena**; así el programa
  sabe dónde termina una escena y empieza la otra.
- **`musica.mp3`**: música de fondo. Se pone bajita (12 %) debajo de la voz y
  se desvanece al final. Usa música libre de derechos.

Si no hay `narracion.mp3`, se usa la voz automática "Dalia" (español de
México). **Para eso se necesita internet.**

---

## 4. Hacer el video

En la terminal, dentro de la carpeta `te_divina`:

```
python generar_video.py
```

(En Mac o Linux puede ser `python3 generar_video.py`.)

Tarda uno o dos minutos. Al final verás:
- el video en `salida/te_divina_prototipo.mp4`;
- una foto de cada escena en `salida/fotogramas/` y una hoja con todas en
  `salida/fotogramas/resumen.png`, para revisar rápido;
- una lista de **"Cosas que revisar"** (imágenes que faltan, número de
  WhatsApp de ejemplo, etc.).

El programa también revisa solo que el video dure entre 35 y 40 segundos, que
tenga el tamaño correcto y que ningún texto quede debajo de los botones de
TikTok o Instagram.

---

## 5. Cambiar el guion (sin programar)

Todo se cambia en el archivo **`config.yaml`** (ábrelo con el Bloc de notas o
TextEdit):

- **Número de WhatsApp:** cambia `whatsapp: "XX XXXX XXXX"`.
- **Lo que dice la voz:** cambia `narracion:` en cada escena.
- **Texto grande en pantalla:** cambia `texto:` (máximo 5 palabras).
- **Imágenes:** cambia `imagen:`; la posición con `x` y `y`; el tamaño con
  `ancho`.
- **Cuándo aparece una imagen:** `inicio: 1.5` (segundos) o
  `inicio: {palabra: "canela"}` (aparece cuando la voz dice esa palabra).
- **Animaciones:** `rebote`, `deslizar_izquierda`, `deslizar_derecha`,
  `zoom`, `aparecer`, `caer`, `transformar`.
- **Colores, voz, velocidad y volumen de la música:** también están ahí.

⚠️ Respeta los espacios al inicio de cada línea y deja los textos entre
comillas. Si algo se rompe, el programa te dice en qué línea.

---

## 6. Reglas de publicidad (COFEPRIS)

Por ser suplementos alimenticios, el programa **se detiene y te avisa** si el
guion:

- promete bajar de peso, kilos, tallas o "resultados en X días";
- dice que cura, previene, desinflama o trata enfermedades, o usa "detox";
- usa imágenes con nombres como "antes", "después" o "cuerpo".

Aun así, **revisa tú las imágenes**: no uses fotos de cuerpos ni de
antes y después.
