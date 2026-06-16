#!/usr/bin/env python3
"""
=============================================================
  SISMOGRAFO - ENES Morelia / Geociencias UNAM
  Version: Laptop Windows con hotspot Raspberry Pi 3
  Autor: Itzel Rojas Lopez
=============================================================

INSTALACION (ejecutar UNA SOLA VEZ en PowerShell):
  pip install obspy matplotlib Pillow flask

USO:
  python shake_laptop_2.py
=============================================================
"""

# ── Librerias del sistema operativo ──────────────────────────────────────────
import subprocess   # permite ejecutar comandos del sistema (para instalar paquetes)
import sys          # acceso al interprete de Python (para saber la ruta de python.exe)
import os           # funciones del sistema operativo (abrir archivos, rutas)
import time         # funciones de tiempo (pausas, timestamps)
import logging      # sistema de registro de mensajes (INFO, ERROR, WARNING)
import shutil       # operaciones de archivos (copiar archivos entre carpetas)
import threading    # permite correr multiples tareas al mismo tiempo (hilos)
from datetime import datetime, timezone  # manejo de fechas y horas con zona horaria
from pathlib import Path                 # manejo de rutas de archivos de forma segura

# ── Instalacion automatica de librerias si no estan instaladas ────────────────
# Lista de paquetes necesarios para que el sistema funcione
PAQUETES = ['obspy', 'matplotlib', 'Pillow', 'flask', 'qrcode[pil]', 'requests']

# Recorre cada paquete e intenta importarlo; si falla, lo instala automaticamente
for paquete in PAQUETES:
    try:
        # Intenta importar el paquete
        __import__(paquete.replace('-', '_').split('==')[0])
    except ImportError:
        # Si no esta instalado, lo instala con pip
        print('Instalando ' + paquete + '...')
        subprocess.call([sys.executable, '-m', 'pip', 'install', paquete, '--quiet'])

# ── Importar librerias y de servidor web ─────────────────────────
from obspy import Stream                                    # clase para almacenar datos sismicos en memoria
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient  # cliente para recibir datos en tiempo real via SeedLink
import numpy as np                                          # operaciones matematicas sobre arreglos de datos
import matplotlib                                           # libreria de graficas
matplotlib.use('Agg')                                       # modo sin pantalla (headless): genera imagenes sin mostrar ventanas
import matplotlib.pyplot as plt                             # interfaz principal para crear graficas
from matplotlib.ticker import AutoMinorLocator              # agrega marcas menores en los ejes de las graficas
from PIL import Image, ImageDraw, ImageFont                 # procesamiento de imagenes para generar la impresion
from flask import Flask, render_template_string, send_file, jsonify  # servidor web 
import requests

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACION PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

# Direccion IP del Raspberry Shake en la red del hotspot del Pi 3
SHAKE_IP   = '192.168.1.145'   # <IP del RS1D>
SHAKE_PORT = 18000             # puerto SeedLink del RS1D 

# Identificacion de la estacion sismica
NETWORK  = 'AM'     # red a la que pertenece la estacion 
STATION  = 'R087B'  # codigo unico de la estacion 
LOCATION = '00'     # codigo de localizacion 
CHANNEL  = 'EHZ'    # canal vertical de alta frecuencia (EHZ = Extra High freq, Z = vertical)

# Carpetas donde se guardan las imagenes generadas
OUTPUT_DIR     = Path('C:/sismogramas')          # carpeta principal de salida
LOGO_ENES      = Path('logos/logo_enes.png')      # logo de ENES Morelia (izquierda del header)
LOGO_GEO       = Path('logos/logo_geociencias.png') # logo de Geociencias (derecha del header)
PLOT_PATH      = OUTPUT_DIR / 'sismograma.png'   # imagen del sismograma actual
TICKET_PATH    = OUTPUT_DIR / 'ticket.png'        # imagen para imprimir
WEB_STATIC_DIR = Path('webapp/static')            # carpeta publica accesible desde el navegador

# Archivo de sonido de alarma sismica 
AUDIO_ALARMA   = Path('alarma_sismica.mp3')        # sonido que suena al detectar un evento

# Parametros del algoritmo de deteccion de eventos sismicos (STA/LTA)
# STA = Short Term Average: promedio de energia en ventana corta (detecta inicio del evento)
# LTA = Long Term Average: promedio de energia en ventana larga (nivel de ruido de fondo)
# Cuando STA/LTA > UMBRAL_ON, se considera que hay un evento sismico
STA_SEC    = 1.0   # duracion de la ventana corta en segundos (sensible a cambios rapidos)
LTA_SEC    = 8.0   # duracion de la ventana larga en segundos (8s: baseline estable, deteccion arranca en ~14s)
UMBRAL_ON  = 6.0   # ratio minimo para declarar un evento (mas alto = menos falsos positivos)
UMBRAL_OFF = 2.5   # ratio para declarar que el evento termino

# Configuracion de visualizacion
VENTANA_SEG = 30   # cuantos segundos de datos se muestran en la grafica

# Tiempo minimo entre dos eventos detectados consecutivos 
COOLDOWN_EVENTO = 15   # segundos de espera entre detecciones 

# Puerto del servidor web (5000 es el estandar para Flask)
WEB_PORT = 5000

# Credenciales del hotspot del Raspberry Pi
WIFI_SSID     = 'RasPiEnesMor'    # nombre del hotspot del Pi
WIFI_PASSWORD = 'RaspberryShake3n3s'   # contraseña del hotspot del Pi

# Ancho en pixeles de la impresora termica de 58mm
PRINTER_WIDTH_PX = 384

# Sensibilidad del sensor RS1D para convertir cuentas digitales a velocidad real
# El geofono del RS1D genera aproximadamente 1,500,000,000 cuentas por cada m/s de movimiento
# Esto permite convertir los datos crudos a nanometros/segundo (nm/s) para la grafica
SENSITIVITY = 1.5e9   # cuentas / (m/s)
RENDER_URL = 'https://raspberry-shake-project-fmdr.onrender.com'
URL_PUBLICA = RENDER_URL
# ══════════════════════════════════════════════════════════════════════════════
#  ESTADO GLOBAL - Variables compartidas entre los hilos de ejecucion
# ══════════════════════════════════════════════════════════════════════════════

# Diccionario que almacena el estado actual del sistema
# Es accedido por multiples hilos simultaneamente, por eso se usa un Lock
estado = {
    'buffer'        : Stream(),  # almacen circular de datos sismicos en tiempo real
    'ultimo_evento' : None,      # hora (string HH:MM:SS) del ultimo evento detectado
    'eventos_hoy'   : 0,         # contador de eventos detectados en esta sesion
    'evento_activo' : False,     # True cuando se acaba de detectar un evento (activa alerta visual)
    'ultimo_evento_t': 0,        # timestamp (time.time()) del ultimo evento para el cooldown
    'alarma_activa' : False,     # True mientras suena la alarma (suprime deteccion para evitar falsos positivos)
    'conectado'     : False,     # True cuando el SeedLink esta recibiendo datos del Shake
}

# IP local de la laptop (se detecta al arrancar)
LOCAL_IP = 'localhost'

# Lock (candado) para evitar que dos hilos modifiquen el estado al mismo tiempo
# Sin esto podria haber corrupcion de datos si dos hilos escriben simultaneamente
lock = threading.Lock()


# ── Configuracion del sistema de registro de mensajes (log) ──────────────────
logging.basicConfig(
    level=logging.INFO,   # nivel minimo de mensajes a mostrar (INFO incluye INFO, WARNING, ERROR)
    format='%(asctime)s [%(levelname)s] %(message)s',   # formato: "2026-05-11 18:00:00 [INFO] mensaje"
    handlers=[
        # Guarda los mensajes en un archivo de texto para revisar errores despues
        logging.FileHandler(str(OUTPUT_DIR / 'shake.log') if OUTPUT_DIR.exists() else 'shake.log'),
        # Tambien muestra los mensajes en la terminal de PowerShell
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)   # crea un logger con el nombre del modulo actual


# ══════════════════════════════════════════════════════════════════════════════
#  FUNCIONES
# ══════════════════════════════════════════════════════════════════════════════

import socket   # para obtener la IP local de la laptop


def get_local_ip():
    """
    Detecta la IP local de la laptop en la red del hotspot.
    Se usa para generar el QR con la URL correcta.
    """
    try:
        # Abre una conexion UDP falsa para que el SO elija la interfaz correcta
        # No se envia ningun dato real
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.168.1.1', 1))   # apunta al gateway del hotspot
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return 'localhost'


def _hacer_qr(datos, ruta, box_size=6):
    """Genera un QR PNG generico y lo guarda en ruta."""
    import qrcode
    qr = qrcode.QRCode(
        version=None,                                    # version automatica segun longitud
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # maxima correccion de errores
        box_size=box_size,
        border=2,
    )
    qr.add_data(datos)
    qr.make(fit=True)
    qr.make_image(fill_color='black', back_color='white').save(str(ruta))


def generar_qr():
    """
    Genera un solo QR con la URL pública del sismógrafo en Render.
    """
    try:
        _hacer_qr(URL_PUBLICA, WEB_STATIC_DIR / 'url_qr.png')
        log.info('QR generado — URL pública: %s', URL_PUBLICA)
    except ImportError:
        log.warning('qrcode no instalado. Ejecuta: pip install qrcode[pil]')
    except Exception as e:
        log.warning('No se pudo generar QR: %s', str(e))
    return get_local_ip()   # sigue retornando la IP local (la usa LOCAL_IP internamente)


def init_dirs():
    """Crea todas las carpetas necesarias si no existen."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)      # crea C:/sismogramas y subcarpetas
    WEB_STATIC_DIR.mkdir(parents=True, exist_ok=True)  # crea webapp/static para las imagenes web
    Path('logos').mkdir(exist_ok=True)                  # crea la carpeta para los logos institucionales
    log.info('Carpetas listas en %s', str(OUTPUT_DIR))  # registra que todo esta listo

    # Copia el archivo de alarma a la carpeta web para que el navegador pueda reproducirlo
    if AUDIO_ALARMA.exists():
        shutil.copy(str(AUDIO_ALARMA), str(WEB_STATIC_DIR / AUDIO_ALARMA.name))
        log.info('Archivo de alarma copiado al directorio web.')
    else:
        log.warning('Archivo de alarma no encontrado: %s', str(AUDIO_ALARMA))

    # Genera el codigo QR con la URL del servidor
    global LOCAL_IP
    LOCAL_IP = generar_qr()


def detect_event(trace):
    """
    Aplica el algoritmo STA/LTA para detectar eventos sismicos.
    
    El algoritmo compara la energia de la senal en dos ventanas de tiempo:
    - STA (Short Term Average): ventana corta, sensible a cambios bruscos
    - LTA (Long Term Average): ventana larga, representa el nivel de ruido de fondo
    
    Cuando la relacion STA/LTA supera UMBRAL_ON, hay un evento sismico.
    
    Retorna True si se detecto un evento, False si no.
    """
    from obspy.signal.trigger import classic_sta_lta, trigger_onset

    df  = trace.stats.sampling_rate           # frecuencia de muestreo en Hz (100 para el RS1D)
    sta = int(STA_SEC * df)                   # convierte segundos a numero de muestras para STA
    lta = int(LTA_SEC * df)                   # convierte segundos a numero de muestras para LTA

    # Verifica que haya suficientes datos para calcular el LTA (necesita al menos 2x la ventana larga)
    if len(trace.data) < lta * 2:
        return False   # no hay suficientes datos, no se puede detectar evento

    # Calcula la funcion caracteristica STA/LTA punto por punto en toda la traza
    cft = classic_sta_lta(trace.data, sta, lta)

    # Encuentra los momentos donde el ratio supera el umbral
    on_off = trigger_onset(cft, UMBRAL_ON, UMBRAL_OFF)

    if len(on_off) == 0:
        return False

    # Verifica que la amplitud real sea significativa (evita falsas alarmas por ruido electrico)
    # Solo declara evento si la amplitud maxima supera 5x el nivel de ruido de fondo
    amplitud_max  = np.max(np.abs(trace.data))
    ruido_fondo   = np.percentile(np.abs(trace.data), 50)   # mediana como referencia de ruido
    if ruido_fondo > 0 and amplitud_max < ruido_fondo * 5:
        return False   # amplitud insuficiente, no es un evento real

    return True


def generate_plot(trace):
    """
    Genera la imagen del sismograma 
    
    Usa una escala Y inteligente basada en la Desviacion Absoluta de la Mediana (MAD)
    para que las ondas siempre sean visibles sin importar si hubo un golpe cercano.
    La imagen se guarda en PLOT_PATH 
    """
    # ── Cadena de procesamiento de la senal sismica ──────────────────────────────
    tr_filtrado = trace.copy()

    # FILTRO 1 – Detrend lineal
    # Elimina cualquier tendencia de largo periodo (deriva termica del sensor, inclinacion
    # lenta). Si se omite este paso, el filtro pasa-altas puede producir oscilaciones
    # de gran amplitud al principio y al final de la ventana (efecto Gibbs).
    tr_filtrado.detrend('linear')

    # FILTRO 2 – Remocion de componente DC (demean)
    # Garantiza que la senal este centrada en cero antes de aplicar cualquier filtro.
    # Evita que un offset constante se amplifique o distorsione el filtro siguiente.
    tr_filtrado.detrend('demean')

    # FILTRO 3 – Ventana coseno (taper) al 5 % de cada extremo
    # Multiplica los extremos de la señal por una rampa coseno suave para que lleguen
    # a cero gradualmente. Sin este paso, los bordes abruptos del buffer (especialmente
    # tras un evento fuerte donde el ADC puede saturarse) generan oscilaciones
    # artificiales de alta amplitud ("lineas rectas") al pasar por el filtro pasa-bandas.
    # Solución estandar en sismologia para el fenomeno de Gibbs / ringing del filtro.
    tr_filtrado.taper(max_percentage=0.05, type='cosine')

    # FILTRO 4 – Pasa-bandas Butterworth de fase cero, 1 – 20 Hz, 4 polos
    # Deja pasar solo las frecuencias donde ocurren sismos y vibraciones del suelo.
    # - freqmin=1.0 Hz : elimina ruido microsiSmico y vibraciones muy lentas (< 1 Hz)
    # - freqmax=20.0 Hz: elimina ruido electrico de alta frecuencia (> 20 Hz)
    # - corners=4      : pendiente de 80 dB/decada; buen compromiso rechazo/estabilidad
    # - zerophase=True : aplica el filtro dos veces (ida y vuelta) para no desfasar la señal
    tr_filtrado.filter('bandpass', freqmin=3.0, freqmax=20.0, corners=4, zerophase=True)

    # Convierte los datos filtrados de cuentas digitales a nanometros/segundo
    datos_nmps = (tr_filtrado.data / SENSITIVITY) * 1e9

    # Frecuencia de muestreo y total de muestras necesarias para la ventana
    fs           = trace.stats.sampling_rate        # 100 Hz para el RS1D
    muestras_tot = int(VENTANA_SEG * fs)            # muestras totales para la ventana completa

    # Si hay menos datos que la ventana completa, rellena con ceros a la izquierda
    n = len(datos_nmps)
    if n < muestras_tot:
        padding    = np.zeros(muestras_tot - n)
        datos_plot = np.concatenate([padding, datos_nmps])
    else:
        datos_plot = datos_nmps[-muestras_tot:]

    # ── Escala Y robusta sobre la ventana COMPLETA (30 s) ────────────────────────
    # Se calcula la escala sobre toda la ventana visible de 30 s y se usa el
    # percentil 99.5 del valor absoluto.  Esto significa:
    #   - El 99.5 % de las amplitudes cabe dentro del rango visible sin recorte.
    #   - Solo el 0.5 % mas extremo (picos instantaneos de ADC saturado) puede salir.
    #   - La escala es estable durante periodos quietos y se expande limpiamente
    #     cuando llega un evento, mostrando la forma de onda completa y legible.
    pico = np.percentile(np.abs(datos_plot), 99.5)
    ymax = max(pico * 1.3, 200)

    # Eje de tiempo fijo: siempre de -VENTANA_SEG a 0
    t = np.linspace(-VENTANA_SEG, 0, muestras_tot)

    # ── Colores de la interfaz ────────────────────────────────────────────────
    COLOR_FONDO = '#0d1117'
    COLOR_SENAL = '#ff4444'
    COLOR_TEXTO = '#8b949e'
    COLOR_GRID  = '#21262d'

    # Crea la figura y ejes de matplotlib
    fig, ax = plt.subplots(figsize=(10, 3))
    fig.patch.set_facecolor(COLOR_FONDO)

    # Dibuja una linea horizontal en y=0 (linea base del sismograma)
    ax.axhline(y=0, color='#30363d', linewidth=0.6, zorder=1)

    # Dibuja la senal sismica
    # linewidth=0.7: linea delgada para mostrar detalles de alta frecuencia
    # rasterized=True: optimiza el renderizado de lineas muy densas
    # zorder=2: se dibuja encima de la cuadricula y la linea base
    ax.plot(t, datos_plot, color=COLOR_SENAL, linewidth=0.7, rasterized=True, zorder=2)

    # Fija el eje X siempre en la ventana completa
    ax.set_xlim(-VENTANA_SEG, 0)

    # Aplica la escala Y inteligente calculada arriba
    # Esto hace que la senal ocupe siempre ~60-70% de la altura de la grafica
    ax.set_ylim(-ymax, ymax)

    # Obtiene la hora actual en UTC y en hora de Mexico para mostrar en el titulo
    ahora_utc = datetime.now(tz=timezone.utc).strftime('%H:%M:%S UTC')
    ahora_mx  = datetime.now().strftime('%H:%M:%S CST')

    # Etiquetas de los ejes
    ax.set_xlabel('Segundos', fontsize=8, color=COLOR_TEXTO)
    ax.set_ylabel('Velocidad\n(nm/s)', fontsize=8, color=COLOR_TEXTO)  # eje Y: velocidad en nm/s

    # Configura el tamaño de los numeros en los ejes
    ax.tick_params(labelsize=7, colors=COLOR_TEXTO)

    # Agrega marcas menores entre los numeros principales del eje X
    ax.xaxis.set_minor_locator(AutoMinorLocator())

    # Dibuja la cuadricula de fondo
    ax.grid(True, alpha=0.4, linewidth=0.4, color=COLOR_GRID, zorder=0)

    # Cambia el color del borde de la grafica
    for spine in ax.spines.values():
        spine.set_color('#30363d')

    # Titulo de la grafica con informacion de la estacion y hora actual
    titulo = ('Estacion: ' + STATION +
              '  |  Canal: ' + CHANNEL +
              '  |  ' + str(int(trace.stats.sampling_rate)) + ' muestras/s' +
              '  |  UTC: ' + ahora_utc +
              '  |  CST: ' + ahora_mx)
    ax.set_title(titulo, fontsize=7, color=COLOR_TEXTO, pad=5)

    # Ajusta los margenes de la figura para aprovechar el espacio
    fig.tight_layout(pad=0.8)

    # Guarda la imagen en disco 
    fig.savefig(str(PLOT_PATH), dpi=180, bbox_inches='tight',
                facecolor=COLOR_FONDO, edgecolor='none')

    # Cierra la figura para liberar memoria
    plt.close(fig)

    # Restaura la configuracion por defecto de matplotlib para no afectar otras graficas
    plt.rcParams.update(plt.rcParamsDefault)

    # Copia la imagen al directorio web
    shutil.copy(str(PLOT_PATH), str(WEB_STATIC_DIR / 'sismograma.png'))
    log.info('Sismograma actualizado.')   # registra que la imagen fue actualizada
    upload_a_render()

def load_logo(path, size):
    if Path(path).exists():   # verifica que el archivo existe antes de intentar abrirlo
        try:
            # Abre la imagen, convierte a escala de grises ('L' = Luminance) y redimensiona
            # Image.LANCZOS es el algoritmo de redimension de mayor calidad
            return Image.open(str(path)).convert('L').resize(size, Image.LANCZOS)
        except Exception as e:
            log.warning('Logo no cargado: %s', str(e))   # registra el error pero no falla
    return None   # retorna None si el logo no existe o tuvo error


def create_ticket(fecha):
    """
    Genera la imagen para impresion.
    
    El ticket tiene:
    - Header: logos institucionales + titulo + fecha + info de estacion
    - Cuerpo: sismograma
    - Pie: creditos institucionales
    
    Se guarda en TICKET_PATH listo para descargar.
    """
    W = PRINTER_WIDTH_PX   # ancho total del ticket en pixeles (384px para impresora de 58mm)

    # Carga el sismograma y lo escala al ancho del ticket manteniendo proporciones
    sismo_img = Image.open(str(PLOT_PATH)).convert('L')   # abre en escala de grises
    aspect    = sismo_img.height / sismo_img.width         # calcula la relacion alto/ancho
    new_w     = W - 8                                       # deja un margen de 4px a cada lado
    sismo_img = sismo_img.resize(
        (new_w, int(new_w * aspect)),   # nuevo ancho y alto proporcional
        Image.LANCZOS                    # algoritmo de alta calidad
    )

    # Define las alturas de cada seccion del ticket
    HEADER_H = 54    # altura del encabezado con logos y texto
    FOOTER_H = 20    # altura del pie de pagina
    total_h  = HEADER_H + sismo_img.height + FOOTER_H   # altura total del ticket

    # Crea el lienzo del ticket: modo 'L' (escala de grises), fondo blanco (255)
    canvas = Image.new('L', (W, total_h), 255)
    draw   = ImageDraw.Draw(canvas)   # objeto para dibujar texto y lineas sobre el lienzo

    # Carga las fuentes de Windows para el texto del ticket
    try:
        font_title  = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 13)  # Arial negrita para el titulo
        font_normal = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 9)      # Arial normal para la fecha
        font_small  = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 7)      # Arial pequeño para detalles
    except Exception:
        font_title  = ImageFont.load_default()   # fuente de emergencia si Arial no esta disponible
        font_normal = font_title
        font_small  = font_title

    def text_w(txt, font):
        """Calcula el ancho en pixeles de un texto dado"""
        try:
            bb = draw.textbbox((0, 0), txt, font=font)   # Pillow >= 9.2.0
            return bb[2] - bb[0]   # ancho = coordenada derecha - coordenada izquierda
        except AttributeError:
            return draw.textsize(txt, font=font)[0]   # Pillow < 9.2.0 (metodo antiguo)

    # ── Logos institucionales ─────────────────────────────────────────────────
    logo_l = load_logo(LOGO_ENES, (48, 22))   # logo ENES redimensionado a 48x22 pixeles
    logo_r = load_logo(LOGO_GEO, (48, 22))    # logo Geociencias redimensionado a 48x22 pixeles
    if logo_l:
        canvas.paste(logo_l, (3, 3))        # pega logo ENES en la esquina superior izquierda
    if logo_r:
        canvas.paste(logo_r, (W - 51, 3))   # pega logo Geociencias en la esquina superior derecha

    # ── Texto del encabezado ──────────────────────────────────────────────────
    # Titulo "SISMOGRAMA" centrado horizontalmente
    titulo = 'SISMOGRAMA'
    draw.text(
        ((W - text_w(titulo, font_title)) // 2, 3),   # posicion X centrada, Y=3px desde arriba
        titulo, font=font_title, fill=0                 # texto negro (fill=0 en escala de grises)
    )

    # Fecha y hora centradas debajo del titulo
    draw.text(
        ((W - text_w(fecha, font_normal)) // 2, 19),   # Y=19px desde arriba
        fecha, font=font_normal, fill=0
    )

    # Informacion de la estacion (nombre, red, frecuencia) centrada
    info = 'Estacion: ' + STATION + '  |  Red: ' + NETWORK + '  |  100 muestras/s'
    draw.text(
        ((W - text_w(info, font_small)) // 2, 32),   # Y=32px desde arriba
        info, font=font_small, fill=80                 # gris oscuro (80 en escala de grises)
    )

    # Linea separadora horizontal entre el header y el sismograma
    draw.line([(0, HEADER_H - 3), (W, HEADER_H - 3)], fill=160, width=1)

    # ── Sismograma ────────────────────────────────────────────────────────────
    # Pega el sismograma centrado horizontalmente debajo del header
    canvas.paste(sismo_img, ((W - sismo_img.width) // 2, HEADER_H))

    # ── Pie de pagina ─────────────────────────────────────────────────────────
    pie = 'Geociencias ENES Morelia - UNAM'
    draw.text(
        ((W - text_w(pie, font_small)) // 2,           # centrado horizontalmente
         HEADER_H + sismo_img.height + 5),              # debajo del sismograma con 5px de margen
        pie, font=font_small, fill=100                  # gris medio
    )

    # Guarda el ticket como imagen PNG con resolucion de 203 DPI
    canvas.save(str(TICKET_PATH), dpi=(203, 203))
    log.info('Ticket guardado: %s', str(TICKET_PATH))


# ══════════════════════════════════════════════════════════════════════════════
#  CLIENTE SEEDLINK - Recibe datos en tiempo real del RS1D
# ══════════════════════════════════════════════════════════════════════════════

class ShakeClient(EasySeedLinkClient):
    """
    Cliente SeedLink que se conecta al RS1D y recibe datos sismicos en tiempo real.
    
    SeedLink es el protocolo estandar para transmitir datos sismicos en tiempo real.
    El RS1D publica sus datos en el puerto 18000 usando este protocolo.
    Cada vez que llegan nuevos datos, se llama automaticamente al metodo on_data().
    """

    def on_data(self, trace):
        """
        Metodo llamado automaticamente cada vez que llegan nuevos datos del RS1D.
        Agrega los datos al buffer circular y descarta los datos mas antiguos.
        """
        with lock:   # bloquea el acceso al estado mientras se modifican los datos
            # Agrega la nueva traza de datos al buffer
            estado['buffer'] += trace
            # Fusiona trazas fragmentadas en una sola traza continua
            # method=1: rellena huecos con el valor anterior
            # fill_value=0: rellena con cero si no hay datos previos
            estado['buffer'].merge(method=1, fill_value=0)
            # Marca el sistema como conectado
            estado['conectado'] = True

            # Mantiene solo los ultimos VENTANA_SEG segundos de datos en memoria
            # Esto evita que el buffer crezca indefinidamente y consuma toda la RAM
            if len(estado['buffer']) > 0:
                tr = estado['buffer'][0]   # obtiene la primera (y unica) traza del buffer
                # Calcula el numero maximo de muestras a guardar
                max_muestras = int(VENTANA_SEG * tr.stats.sampling_rate)
                if tr.stats.npts > max_muestras:
                    # El dato de fondo (starttime) debe avanzar con cada recorte 
                    # SOLUCION: mover starttime hacia adelante exactamente tantas muestras
                    # como se van a eliminar, de modo que la traza siempre termine en
                    # el instante mas reciente y merge() no genere huecos artificiales.
                    n_exceso = tr.stats.npts - max_muestras
                    tr.stats.starttime += n_exceso / tr.stats.sampling_rate
                    # Conserva solo las ultimas max_muestras muestras (las mas recientes)
                    # ObsPy actualiza tr.stats.npts automaticamente al reasignar .data
                    tr.data = tr.data[-max_muestras:]

    def on_seedlink_error(self):
        """Llamado cuando hay un error de conexion con el servidor SeedLink."""
        with lock:
            estado['conectado'] = False   # marca el sistema como desconectado
        log.error('Error de conexion SeedLink. Reintentando...')


def hilo_seedlink():
    """
    Hilo que mantiene la conexion con el RS1D activa permanentemente.
    
    Si la conexion falla (corte de red, Shake apagado, etc.), 
    espera 10 segundos y reintenta automaticamente.
    Esto garantiza que el sistema se recupera solo sin intervencion manual.
    """
    while True:   # bucle infinito: siempre intenta reconectarse si falla
        try:
            log.info('Conectando al RS1D en %s:%s...', SHAKE_IP, SHAKE_PORT)
            # Crea el cliente SeedLink apuntando a la IP y puerto del Shake
            client = ShakeClient(SHAKE_IP + ':' + str(SHAKE_PORT))
            # Selecciona el canal a recibir: red AM, estacion R087B, canal EHZ
            client.select_stream(NETWORK, STATION, CHANNEL)
            # Inicia la recepcion de datos (bloquea hasta que haya un error)
            client.run()
        except Exception as e:
            # Si hay cualquier error, registralo y espera antes de reconectar
            log.error('SeedLink desconectado: %s. Reintentando en 10s...', str(e))
            with lock:
                estado['conectado'] = False   # actualiza el estado para la interfaz web
            time.sleep(10)   # espera 10 segundos antes de intentar reconectar


# ══════════════════════════════════════════════════════════════════════════════
#  HILO DE PROCESAMIENTO - Genera graficas y detecta eventos
# ══════════════════════════════════════════════════════════════════════════════

def hilo_procesamiento():
    """
    Hilo que revisa deteccion cada 1 segundo y regenera el sismograma cada 5 segundos.
    
    Realiza dos tareas:
    1. Genera una nueva imagen del sismograma y la publica en la web (cada 5s)
    2. Aplica el algoritmo STA/LTA para detectar eventos sismicos (cada 1s)
    
    Este hilo corre en paralelo con el cliente SeedLink y el servidor web.
    """
    ultimo_plot = 0   # timestamp de la ultima vez que se genero una grafica

    while True:   # bucle infinito: procesa continuamente mientras el sistema este corriendo
        time.sleep(1)   # revisa cada 1 segundo para deteccion rapida (plot sigue siendo cada 5s)
        try:
            # Obtiene una copia de los datos actuales de forma segura (con el lock)
            with lock:
                if len(estado['buffer']) == 0:
                    continue   # si no hay datos todavia, salta este ciclo
                tr = estado['buffer'][0].copy()   # copia para no modificar el original

            ahora = time.time()   # timestamp actual en segundos

            # Genera el sismograma cada 5 segundos
            if ahora - ultimo_plot >= 5:
                generate_plot(tr)    # dibuja la grafica y la guarda en disco
                ultimo_plot = ahora  # actualiza cuando fue la ultima generacion

            # Aplica el detector STA/LTA para buscar eventos sismicos
            # Salta la deteccion mientras la alarma esta sonando (evita falsos positivos)
            with lock:
                alarma_ok = not estado['alarma_activa']
            if not alarma_ok:
                continue

            if detect_event(tr):
                with lock:
                    # Verifica que haya pasado suficiente tiempo desde el ultimo evento
                    cooldown_ok = (ahora - estado['ultimo_evento_t']) >= COOLDOWN_EVENTO

                if cooldown_ok:
                    # Registra el evento detectado
                    log.info('*** EVENTO SISMICO DETECTADO *** %s',
                             datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

                    # Reproduce la alarma y suprime la deteccion mientras suena
                    def _reproducir_alarma():
                        try:
                            # Activa la bandera: el detector ignorara senales durante este tiempo
                            with lock:
                                estado['alarma_activa'] = True

                            if AUDIO_ALARMA.exists():
                                ruta = str(AUDIO_ALARMA.resolve())
                                cmd = (
                                    'Add-Type -AssemblyName presentationCore; '
                                    '$p = [System.Windows.Media.MediaPlayer]::new(); '
                                    '$p.Open([uri]"' + ruta + '"); '
                                    '$p.Play(); '
                                    'Start-Sleep -Seconds 15'   # ajusta si el audio dura mas de 15s
                                )
                                subprocess.Popen(
                                    ['powershell', '-WindowStyle', 'Hidden', '-Command', cmd],
                                    creationflags=subprocess.CREATE_NO_WINDOW
                                )

                            # Espera duracion de la alarma (3s reales) + margen de resonancia mecanica
                            # para asegurarse de que el geofonos dejo de vibrar antes de reactivar
                            time.sleep(20)
                        except Exception as e_audio:
                            log.warning('No se pudo reproducir alarma de audio: %s', str(e_audio))
                        finally:
                            # Reactiva la deteccion pase lo que pase
                            with lock:
                                estado['alarma_activa'] = False
                            log.info('Deteccion reactivada tras alarma.')
                    threading.Thread(target=_reproducir_alarma, daemon=True).start()

                    # Actualiza el estado para que la interfaz web muestre la alerta
                    with lock:
                        estado['ultimo_evento']   = datetime.now().strftime('%H:%M:%S')
                        estado['eventos_hoy']    += 1     # incrementa el contador
                        estado['evento_activo']   = True  # activa el banner rojo en la web
                        estado['ultimo_evento_t'] = ahora # guarda el timestamp para el cooldown

                    # Inicia un hilo secundario que apaga la alerta visual despues de 10 segundos
                    def apagar_alerta():
                        time.sleep(7)   # espera 10 segundos
                        with lock:
                            estado['evento_activo'] = False   # desactiva el banner rojo
                    threading.Thread(target=apagar_alerta, daemon=True).start()

        except Exception as e:
            # Si hay cualquier error al procesar, lo registra pero no detiene el sistema
            log.error('Error en procesamiento: %s', str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  SERVIDOR WEB
# ══════════════════════════════════════════════════════════════════════════════
def upload_a_render():
    """
    Envía el sismograma actual y el estado del sistema al servidor en Render.

    Se llama automáticamente cada 5 segundos (al final de generate_plot).
    Si no hay conexión a internet, registra el error silenciosamente
    y continúa sin interrumpir el procesamiento local.
    """
    import requests   # import local por si acaso no está en scope global

    try:
        # Lee el estado actual de forma segura
        with lock:
            estado_actual = {
                'ultimo_evento' : str(estado['ultimo_evento']) if estado['ultimo_evento'] else '',
                'eventos_hoy'   : str(estado['eventos_hoy']),
                'evento_activo' : str(estado['evento_activo']),
                'conectado'     : str(estado['conectado']),
                'hora'          : datetime.now().strftime('%H:%M:%S'),
            }

        # Prepara los archivos a enviar (sismograma + ticket si existe)
        files = {}

        img_path = WEB_STATIC_DIR / 'sismograma.png'
        if img_path.exists():
            files['sismograma'] = ('sismograma.png',
                                   open(str(img_path), 'rb'),
                                   'image/png')

        if TICKET_PATH.exists():
            files['ticket'] = ('ticket.png',
                                open(str(TICKET_PATH), 'rb'),
                                'image/png')

        # Envía el POST a Render con un timeout de 8 segundos
        resp = requests.post(
            RENDER_URL + '/update_data',
            data  = estado_actual,
            files = files if files else None,
            timeout = 8,
        )

        # Cierra los descriptores de archivo abiertos
        for f in files.values():
            f[1].close()

        if resp.status_code == 200:
            log.debug('Datos enviados a Render OK')
        else:
            log.warning('Render respondió %s: %s', resp.status_code, resp.text[:80])

    except requests.exceptions.ConnectionError:
        log.debug('Sin conexión a internet — datos no enviados a Render')
    except requests.exceptions.Timeout:
        log.warning('Timeout enviando datos a Render')
    except Exception as e:
        log.warning('Error enviando a Render: %s', str(e))

# Crea la aplicacion Flask con la carpeta de archivos estaticos configurada
app = Flask(__name__, static_folder=str(WEB_STATIC_DIR))

# Plantilla HTML de la pagina web
# Esta cadena contiene todo el HTML, CSS y JavaScript de la interfaz
HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sismografo ENES Morelia</title>
  <style>
    /* Reset de estilos: elimina margenes y paddings por defecto de todos los elementos */
    * { box-sizing: border-box; margin: 0; padding: 0; }

    /* Estilo del cuerpo de la pagina */
    body {
      font-family: Arial, sans-serif;
      background: #0d1117;   /* fondo negro azulado */
      color: #e6edf3;        /* texto gris claro */
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
      padding: 12px;
    }

    /* Encabezado con logos, titulo y badge de estado */
    header {
      width: 100%; max-width: 780px;
      display: flex; justify-content: space-between; align-items: center;
      padding: 8px 0 12px;
      border-bottom: 1px solid #30363d;
      margin-bottom: 12px;
    }
    .logos { display: flex; gap: 10px; align-items: center; }
    .logos img { height: 40px; object-fit: contain; filter: brightness(1.8); }
    .titulo { text-align: center; flex: 1; }
    .titulo h1 { font-size: 17px; font-weight: 700; color: #e6edf3; }
    .titulo .sub { font-size: 11px; color: #8b949e; margin-top: 2px; }

    /* Badge de estado (En vivo / EVENTO / Sin conexion) */
    .badge {
      font-size: 11px; padding: 5px 14px;
      border-radius: 12px; background: #1a7f37; color: #fff;
      font-weight: 600; white-space: nowrap;
    }
    .badge.alerta { background: #da3633; animation: pulsar 0.8s infinite; }
    .badge.offline { background: #484f58; }

    /* Animacion de parpadeo para alertas de eventos */
    @keyframes pulsar { 0%,100%{opacity:1} 50%{opacity:.3} }

    /* Contenedor del sismograma */
    .sismo-box {
      width: 100%; max-width: 780px;
      border: 1px solid #30363d; border-radius: 10px;
      overflow: hidden; background: #0d1117;
      margin-bottom: 10px;
    }
    .sismo-box img { width: 100%; display: block; }

    /* Grid de dos columnas para los relojes */
    .relojes {
      width: 100%; max-width: 780px;
      display: grid; grid-template-columns: 1fr 1fr;
      gap: 8px; margin-bottom: 10px;
    }
    .reloj {
      background: #161b22; border: 1px solid #30363d;
      border-radius: 8px; padding: 10px; text-align: center;
    }
    .reloj .val { font-size: 20px; font-weight: 700; color: #58a6ff; font-family: monospace; }
    .reloj .lbl { font-size: 10px; color: #8b949e; margin-top: 2px; }

    /* Grid de tres columnas para las tarjetas de informacion */
    .grid {
      width: 100%; max-width: 780px;
      display: grid; grid-template-columns: repeat(3,1fr);
      gap: 8px; margin-bottom: 10px;
    }
    .card {
      background: #161b22; border: 1px solid #30363d;
      border-radius: 8px; padding: 10px; text-align: center;
    }
    .card .val { font-size: 18px; font-weight: 700; color: #ff4444; }
    .card .lbl { font-size: 10px; color: #8b949e; margin-top: 3px; }

    /* Seccion de explicacion del funcionamiento */
    .explicacion {
      width: 100%; max-width: 780px;
      background: #161b22; border: 1px solid #30363d;
      border-radius: 8px; padding: 12px;
      margin-bottom: 10px;
    }
    .explicacion h3 { font-size: 12px; color: #58a6ff; margin-bottom: 6px; }
    .explicacion p  { font-size: 11px; color: #8b949e; line-height: 1.6; }
    .explicacion .dato { color: #ff4444; font-weight: 600; }

    /* Boton de descarga del ticket */
    .btn {
      width: 100%; max-width: 780px; padding: 13px;
      font-size: 15px; font-weight: 600;
      background: #238636; color: white;
      border: none; border-radius: 8px; cursor: pointer;
      margin-bottom: 8px;
    }
    .btn:hover { background: #2ea043; }
    .btn:disabled { background: #484f58; cursor: not-allowed; }

    /* Banner rojo de alerta de evento sismico */
    .evento-banner {
      display: none;
      width: 100%; max-width: 780px;
      background: #da3633; color: white;
      border-radius: 8px; padding: 12px;
      text-align: center; font-weight: 700;
      font-size: 15px; margin-bottom: 10px;
      animation: pulsar 0.8s infinite;
    }
    .evento-banner.visible { display: block; }

    /* Texto de ultima actualizacion */
    .ts { font-size: 10px; color: #484f58; margin-bottom: 12px; }
  /* Boton QR en el header */
    .btn-qr {
      background: none; border: 1px solid #30363d; border-radius: 8px;
      color: #8b949e; font-size: 20px; cursor: pointer;
      padding: 4px 10px; line-height: 1; transition: border-color .2s;
    }
    .btn-qr:hover { border-color: #8b949e; color: #e6edf3; }

    /* Modal de codigos QR */
    .qr-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,.75); z-index: 100;
      align-items: center; justify-content: center;
    }
    .qr-overlay.open { display: flex; }
    .qr-modal {
      background: #161b22; border: 1px solid #30363d; border-radius: 12px;
      padding: 24px 28px; text-align: center; max-width: 360px; width: 90%;
    }
    .qr-modal h2 { font-size: 15px; color: #e6edf3; margin-bottom: 18px; }
    .qr-pair { display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; }
    .qr-item { flex: 1; min-width: 130px; }
    .qr-item p { font-size: 11px; color: #8b949e; margin-bottom: 8px; font-weight: 600; }
    .qr-item .qr-num {
      display: inline-block; background: #21262d; border-radius: 50%;
      width: 20px; height: 20px; line-height: 20px; font-size: 11px;
      color: #58a6ff; font-weight: 700; margin-bottom: 4px;
    }
    .qr-frame {
      display: inline-block; padding: 8px; background: white; border-radius: 8px;
    }
    .qr-frame img { display: block; width: 140px; height: 140px; }
    .qr-url {
      font-size: 11px; color: #58a6ff; font-family: monospace;
      margin-top: 12px; word-break: break-all;
    }
    .btn-cerrar {
      margin-top: 16px; background: #21262d; border: 1px solid #30363d;
      border-radius: 6px; color: #8b949e; font-size: 12px;
      padding: 6px 18px; cursor: pointer;
    }
    .btn-cerrar:hover { background: #30363d; color: #e6edf3; }
  </style>
</head>
<body>

  <!-- Encabezado con logos, titulo y estado de conexion -->
  <header>
    <div class="logos">
      <!-- Los logos se cargan desde el servidor; si no existen se ocultan automaticamente -->
      <img src="/logo/enes" alt="ENES" onerror="this.style.display='none'">
      <img src="/logo/geo"  alt="Geociencias" onerror="this.style.display='none'">
    </div>
    <div class="titulo">
      <h1>Sismografo ENES Morelia</h1>
      <!-- {{ station }} es reemplazado por el servidor con el codigo de la estacion -->
      <div class="sub">Red AM — Estacion {{ station }} </div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;">
      <div class="badge" id="badge">En vivo</div>
      <button class="btn-qr" onclick="document.getElementById('qr-overlay').classList.add('open')" title="Ver codigo QR">&#128242; QR</button>
    </div>
  </header>

  <!-- Modal con los dos codigos QR -->
  <div class="qr-overlay" id="qr-overlay" onclick="if(event.target===this)this.classList.remove('open')">
    <div class="qr-modal">
      <h2>Conectar otro dispositivo</h2>
      <div class="qr-pair">
        <div class="qr-item">
          <div class="qr-num">1</div>
          <p>Conecta al WiFi del Pi</p>
          <div class="qr-frame">
            <img src="/qr/wifi" alt="WiFi QR"
                 onerror="this.parentElement.innerHTML='<div style=\'font-size:10px;color:#8b949e;padding:10px;width:140px;\'>Instala:<br><code>pip install<br>qrcode[pil]</code></div>'">
          </div>
          <div style="font-size:11px;color:#8b949e;margin-top:6px;">Red: <b style="color:#e6edf3">{{ wifi_ssid }}</b></div>
        </div>
        <div class="qr-item">
          <div class="qr-num">2</div>
          <p>Abre el sismografo</p>
          <div class="qr-frame">
            <img src="/qr/url" alt="URL QR"
                 onerror="this.parentElement.innerHTML='<div style=\'font-size:10px;color:#8b949e;padding:10px;width:140px;\'>Instala:<br><code>pip install<br>qrcode[pil]</code></div>'">
          </div>
          <div class="qr-url">{{ url_publica }}</div>
        </div>
      </div>
      <button class="btn-cerrar" onclick="document.getElementById('qr-overlay').classList.remove('open')">Cerrar</button>
    </div>
  </div>

  <!-- Banner rojo que aparece cuando se detecta un evento sismico -->
  <div class="evento-banner" id="banner">
    &#9888; EVENTO SISMICO DETECTADO
  </div>

  <!-- Imagen del sismograma en tiempo real -->
  <div class="sismo-box">
    <img id="img" src="/sismograma" alt="Sismograma en tiempo real">
  </div>

  <!-- Relojes con hora UTC y hora de Mexico -->
  <div class="relojes">
    <div class="reloj">
      <div class="val" id="hora-utc">--:--:--</div>
      <div class="lbl">Hora UTC (Tiempo Universal)</div>
    </div>
    <div class="reloj">
      <div class="val" id="hora-mx">--:--:--</div>
      <div class="lbl">Hora Mexico (CST = UTC-6)</div>
    </div>
  </div>

  <!-- Tarjetas de informacion: ultimo evento, contador, frecuencia -->
  <div class="grid">
    <div class="card">
      <div class="val" id="ultimo">&#8212;</div>
      <div class="lbl">Ultimo evento detectado</div>
    </div>
    <div class="card">
      <div class="val" id="nevents">0</div>
      <div class="lbl">Eventos en esta sesion</div>
    </div>
    <div class="card">
      <div class="val" id="frec">100 Hz</div>
      <div class="lbl">Frecuencia de muestreo</div>
    </div>
  </div>

  <!-- Explicacion del funcionamiento del RS1D -->
  <div class="explicacion">
    <h3>Como funciona el RS1D</h3>
    <p>
      El RS1D contiene un <span class="dato">geofono</span>, un sensor de velocidad que funciona
      como un microfono de la Tierra. Dentro hay una bobina suspendida sobre un iman por un resorte.
      Cuando el suelo se mueve, la bobina se desplaza y genera una señal electrica proporcional a la
      <span class="dato">velocidad del suelo</span> en nanometros por segundo (nm/s).
      Esta señal es digitalizada a <span class="dato">100 muestras por segundo</span>.
      El eje horizontal es el tiempo en segundos y el vertical la velocidad en nm/s.
      El sistema detecta eventos comparando la energia en una ventana corta de
      <span class="dato">1 segundo</span> vs una larga de <span class="dato">10 segundos</span>
      (algoritmo STA/LTA). Detecta sismos, trafico, personas caminando y cualquier vibracion.
    </p>
  </div>

  <!-- Boton para descargar el ticket  -->
  <button class="btn" id="btn" onclick="descargarTicket()">
    Descargar 
  </button>
  <div class="ts" id="ts">Actualizando...</div>



  <script>
    // ── Alarma de audio ───────────────────────────────────────────────────────
    // Elemento de audio oculto que reproduce la alarma sismica
    const audioAlarma = new Audio('/alarma');
    audioAlarma.preload = 'auto';   // precarga el archivo al cargar la pagina

    // Bandera para no repetir el sonido mientras ya esta sonando
    let alertaSonando = false;

    function reproducirAlarma() {
      if (alertaSonando) return;   // evita solapamiento si ya esta sonando
      alertaSonando = true;
      audioAlarma.currentTime = 0;  // reinicia desde el inicio
      audioAlarma.play().catch(e => console.warn('Audio bloqueado por el navegador:', e));
      // Cuando termina el sonido, permite volver a reproducirlo
      audioAlarma.onended = () => { alertaSonando = false; };
    }

    // Actualiza la imagen del sismograma cada 5 segundos
    // Usa un objeto Image temporal para precargar antes de mostrar (evita parpadeo)
    function actualizarImg() {
      const img = document.getElementById('img');
      const src = '/sismograma?t=' + Date.now();   // agrega timestamp para forzar recarga
      const tmp = new Image();
      tmp.onload = () => { img.src = src; };         // solo actualiza cuando la nueva imagen cargo
      tmp.src = src;
    }

    // Actualiza los relojes con la hora actual cada segundo
    function actualizarRelojes() {
      const ahora = new Date();
      // Extrae la hora UTC del string de fecha UTC (formato "Mon, 11 May 2026 18:00:00 GMT")
      const utc = ahora.toUTCString().slice(-12, -4);
      // Obtiene la hora en zona horaria de Mexico City
      const mx  = ahora.toLocaleTimeString('es-MX', {
        timeZone: 'America/Mexico_City', hour12: false
      });
      document.getElementById('hora-utc').textContent = utc;
      document.getElementById('hora-mx').textContent  = mx;
    }

    // Consulta el estado del servidor cada 3 segundos y actualiza la interfaz
    function actualizarEstado() {
      fetch('/estado')
        .then(r => r.json())
        .then(d => {
          // Actualiza las tarjetas de informacion
          document.getElementById('ultimo').textContent  = d.ultimo_evento || '—';
          document.getElementById('nevents').textContent = d.eventos_hoy;
          document.getElementById('ts').textContent      = 'Actualizado: ' + d.hora;

          const b      = document.getElementById('badge');
          const banner = document.getElementById('banner');

          // Actualiza el badge y banner segun el estado del sistema
          if (!d.conectado) {
            b.textContent = 'Sin conexion'; b.className = 'badge offline';
            banner.classList.remove('visible');
          } else if (d.evento_activo) {
            b.textContent = 'EVENTO'; b.className = 'badge alerta';
            banner.classList.add('visible');
            reproducirAlarma();   // <-- reproduce el sonido de alarma
          } else {
            b.textContent = 'En vivo'; b.className = 'badge';
            banner.classList.remove('visible');
          }
        })
        .catch(() => {});   // ignora errores de red silenciosamente
    }

    // Descarga el ticket de impresion al presionar el boton
    function descargarTicket() {
      const btn = document.getElementById('btn');
      btn.disabled = true;
      btn.textContent = 'Generando ticket...';

      // Pide al servidor que genere el ticket con el sismograma actual
      fetch('/generar_ticket', {method: 'POST'})
        .then(r => r.json())
        .then(d => {
          if (d.ok) {
            // Crea un enlace invisible y hace clic automaticamente para descargar
            const a = document.createElement('a');
            a.href = '/ticket?t=' + Date.now();
            // Nombre del archivo incluye fecha y hora para identificarlo facilmente
            a.download = 'sismograma_' + new Date().toISOString().slice(0,19).replace(/:/g,'-') + '.png';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            btn.textContent = 'Descargado';
          } else {
            btn.textContent = 'Error al generar ticket';
          }
          // Restaura el boton despues de 4 segundos
          setTimeout(() => {
            btn.textContent = 'Descargar ticket para imprimir';
            btn.disabled = false;
          }, 4000);
        })
        .catch(() => {
          btn.textContent = 'Error de conexion';
          btn.disabled = false;
        });
    }

    // Inicia los intervalos de actualizacion automatica
    setInterval(actualizarImg,     5000);   // imagen del sismograma: cada 5 segundos
    setInterval(actualizarEstado,  3000);   // estado del sistema: cada 3 segundos
    setInterval(actualizarRelojes, 1000);   // relojes: cada 1 segundo

    // Ejecuta una actualizacion inicial inmediata al cargar la pagina
    actualizarEstado();
    actualizarRelojes();
  </script>
</body>
</html>
"""


# ── Rutas del servidor web (endpoints) ───────────────────────────────────────

@app.route('/')
def index():
    """Sirve la pagina principal con el sismograma en tiempo real."""
    # render_template_string reemplaza {{ station }} con el codigo real de la estacion
    return render_template_string(HTML, station=STATION, local_ip=LOCAL_IP, web_port=WEB_PORT, wifi_ssid=WIFI_SSID)


@app.route('/logo/enes')
def logo_enes_route():
    """Sirve el logo de ENES Morelia para el header de la pagina."""
    if LOGO_ENES.exists():
        return send_file(str(LOGO_ENES), mimetype='image/png')
    return '', 404   # retorna 404 si el logo no esta, la pagina lo oculta automaticamente


@app.route('/logo/geo')
def logo_geo_route():
    """Sirve el logo de Geociencias UNAM para el header de la pagina."""
    if LOGO_GEO.exists():
        return send_file(str(LOGO_GEO), mimetype='image/png')
    return '', 404


@app.route('/qr/url')
def servir_qr_url():
    """Sirve el QR con la URL del sismografo."""
    f = WEB_STATIC_DIR / 'url_qr.png'
    return send_file(str(f), mimetype='image/png') if f.exists() else ('QR no disponible', 404)


@app.route('/alarma')
def servir_alarma():
    """Sirve el archivo de audio de alarma sismica para que el navegador lo reproduzca."""
    audio_web = WEB_STATIC_DIR / AUDIO_ALARMA.name
    if audio_web.exists():
        return send_file(str(audio_web), mimetype='audio/mpeg')
    return 'Audio no disponible', 404


@app.route('/sismograma')
def sismograma():
    """Sirve la imagen del sismograma actualizada cada 5 segundos."""
    img = WEB_STATIC_DIR / 'sismograma.png'
    if img.exists():
        return send_file(str(img), mimetype='image/png')
    return 'Sin datos aun', 404


@app.route('/estado')
def get_estado():
    """
    Retorna el estado actual del sistema en formato JSON.
    La pagina web lo consulta cada 3 segundos para actualizar la interfaz.
    """
    with lock:   # accede al estado de forma segura
        return jsonify(
            hora          = datetime.now().strftime('%H:%M:%S'),   # hora actual para el timestamp
            ultimo_evento = estado['ultimo_evento'],                # hora del ultimo evento (o None)
            eventos_hoy   = estado['eventos_hoy'],                  # contador de eventos
            evento_activo = estado['evento_activo'],                # True si hay alerta activa
            conectado     = estado['conectado'],                    # True si hay conexion con el Shake
        )


@app.route('/generar_ticket', methods=['POST'])
def generar_ticket():
    """
    Genera el ticket de impresion con el sismograma actual.
    Llamado cuando el usuario presiona el boton.
    """
    try:
        # Obtiene una copia de los datos actuales de forma segura
        with lock:
            if len(estado['buffer']) == 0:
                return jsonify(ok=False, mensaje='Sin datos del sismometro')
            tr = estado['buffer'][0].copy()

        # Genera la fecha y hora actuales para el ticket
        fecha = datetime.now().strftime('%Y-%m-%d  %H:%M:%S')

        # Genera primero la imagen del sismograma
        generate_plot(tr)

        # Verifica que la imagen se genero correctamente antes de crear el ticket
        if not PLOT_PATH.exists():
            return jsonify(ok=False, mensaje='Error generando imagen del sismograma')

        # Genera el ticket con la imagen del sismograma
        create_ticket(fecha)

        # Verifica que el ticket se genero correctamente
        if not TICKET_PATH.exists():
            return jsonify(ok=False, mensaje='Error generando el ticket')

        return jsonify(ok=True)   # exito

    except Exception as e:
        log.error('Error generando ticket: %s', str(e), exc_info=True)
        return jsonify(ok=False, mensaje=str(e)), 500


@app.route('/ticket')
def descargar_ticket():
    """
    Sirve el archivo del ticket para descarga directa en cualquier dispositivo.
    El archivo se descarga como adjunto con el nombre 'sismograma_ENES.png'.
    """
    if TICKET_PATH.exists():
        return send_file(
            str(TICKET_PATH),
            mimetype='image/png',
            as_attachment=True,           # indica al navegador que debe descargarlo
            download_name='sismograma_ENES.png'   # nombre del archivo descargado
        )
    return 'Ticket no disponible aun', 404


# ══════════════════════════════════════════════════════════════════════════════
#  FUNCION PRINCIPAL - Punto de entrada del programa
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """
    Inicia el sistema completo:
    1. Crea las carpetas necesarias
    2. Inicia el hilo de recepcion de datos del Shake (SeedLink)
    3. Inicia el hilo de procesamiento y deteccion de eventos
    4. Inicia el servidor web 
    """
    # Crea las carpetas de salida si no existen
    init_dirs()

    # Agrega un handler de log al archivo ahora que la carpeta ya existe
    fh = logging.FileHandler(str(OUTPUT_DIR / 'shake.log'))
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    log.addHandler(fh)

    # Muestra informacion de inicio en la terminal
    log.info('=' * 55)
    log.info('  Sistema sismico ENES Morelia - Laptop Windows')
    log.info('  Shake IP: %s:%s', SHAKE_IP, SHAKE_PORT)
    log.info('  Servidor web: http://localhost:%s', WEB_PORT)
    log.info('=' * 55)

    # Hilo 1: recibe datos del RS1D en tiempo real via SeedLink
    # daemon=True: el hilo se detiene automaticamente cuando se cierra el programa
    t1 = threading.Thread(target=hilo_seedlink, daemon=True)
    t1.start()

    # Hilo 2: procesa los datos y detecta eventos cada 5 segundos
    t2 = threading.Thread(target=hilo_procesamiento, daemon=True)
    t2.start()

    # Servidor web: corre en el hilo principal (bloquea hasta que se cierra con Ctrl+C)
    # host='0.0.0.0': acepta conexiones de cualquier dispositivo en la red (tablet, telefono)
    # use_reloader=False: evita que Flask inicie dos procesos al mismo tiempo
    log.info('Acceso desde otro dispositivo: http://<IP-LAPTOP>:%s', WEB_PORT)
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)


# Punto de entrada: solo ejecuta main() si se corre directamente (no al importar)
if __name__ == '__main__':
    main()
