#!/usr/bin/env python3
"""
=============================================================
  SISMOGRAFO - ENES Morelia / Geociencias UNAM
  Versión para la Nube (Render)
=============================================================
"""
import os
import logging
from datetime import datetime
from flask import Flask, render_template_string, send_file, jsonify, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)

# Directorio temporal para guardar lo que envíe la laptop
DATA_DIR = "/tmp" if os.name != 'nt' else "C:/sismogramas_nube"
os.makedirs(DATA_DIR, exist_ok=True)

PLOT_PATH = os.path.join(DATA_DIR, 'sismograma.png')
TICKET_PATH = os.path.join(DATA_DIR, 'ticket.png')

# Estado global inicial
estado_web = {
    'ultimo_evento': None,
    'eventos_hoy': 0,
    'evento_activo': False,
    'conectado': False,
    'hora': '--:--:--'
}

STATION = 'R087B'

HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sismografo ENES Morelia</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: Arial, sans-serif;
      background: #0d1117;
      color: #e6edf3;
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
      padding: 12px;
    }
    header {
      width: 100%; max-width: 780px;
      display: flex; justify-content: space-between; align-items: center;
      padding: 8px 0 12px;
      border-bottom: 1px solid #30363d;
      margin-bottom: 12px;
    }
    .titulo { text-align: center; flex: 1; }
    .titulo h1 { font-size: 17px; font-weight: 700; color: #e6edf3; }
    .titulo .sub { font-size: 11px; color: #8b949e; margin-top: 2px; }
    .badge {
      font-size: 11px; padding: 5px 14px;
      border-radius: 12px; background: #1a7f37; color: #fff;
      font-weight: 600; white-space: nowrap;
    }
    .badge.alerta { background: #da3633; animation: pulsar 0.8s infinite; }
    .badge.offline { background: #484f58; }
    @keyframes pulsar { 0%,100%{opacity:1} 50%{opacity:.3} }
    .sismo-box {
      width: 100%; max-width: 780px;
      border: 1px solid #30363d; border-radius: 10px;
      overflow: hidden; background: #0d1117;
      margin-bottom: 10px;
    }
    .sismo-box img { width: 100%; display: block; }
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
    .explicacion {
      width: 100%; max-width: 780px;
      background: #161b22; border: 1px solid #30363d;
      border-radius: 8px; padding: 12px;
      margin-bottom: 10px;
    }
    .explicacion h3 { font-size: 12px; color: #58a6ff; margin-bottom: 6px; }
    .explicacion p  { font-size: 11px; color: #8b949e; line-height: 1.6; }
    .explicacion .dato { color: #ff4444; font-weight: 600; }
    .btn {
      width: 100%; max-width: 780px; padding: 13px;
      font-size: 15px; font-weight: 600;
      background: #238636; color: white;
      border: none; border-radius: 8px; cursor: pointer;
      margin-bottom: 8px;
    }
    .btn:hover { background: #2ea043; }
    .btn:disabled { background: #484f58; cursor: not-allowed; }
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
    .ts { font-size: 10px; color: #484f58; margin-bottom: 12px; }
  </style>
</head>
<body>

  <header>
    <div class="titulo">
      <h1>Sismógrafo ENES Morelia</h1>
      <div class="sub">Red AM — Estación {{ station }} (En la Nube)</div>
    </div>
    <div>
      <div class="badge" id="badge">Cargando...</div>
    </div>
  </header>

  <div class="evento-banner" id="banner">
    &#9888; EVENTO SÍSMICO DETECTADO
  </div>

  <div class="sismo-box">
    <img id="img" src="/sismograma" alt="Sismograma en tiempo real" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' width=\'800\' height=\'300\'><rect width=\'100%\' height=\'100%\' fill=\'%230d1117\'/><text x=\'50%\' y=\'50%\' fill=\'%238b949e\' text-anchor=\'middle\'>Esperando señal de la estación local...</text></svg>'">
  </div>

  <div class="relojes">
    <div class="reloj">
      <div class="val" id="hora-utc">--:--:--</div>
      <div class="lbl">Hora UTC (Tiempo Universal)</div>
    </div>
    <div class="reloj">
      <div class="val" id="hora-mx">--:--:--</div>
      <div class="lbl">Hora México (CST)</div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="val" id="ultimo">&#8212;</div>
      <div class="lbl">Último evento detectado</div>
    </div>
    <div class="card">
      <div class="val" id="nevents">0</div>
      <div class="lbl">Eventos en esta sesión</div>
    </div>
    <div class="card">
      <div class="val" id="frec">100 Hz</div>
      <div class="lbl">Frecuencia de muestreo</div>
    </div>
  </div>

  <div class="explicacion">
    <h3>Cómo funciona el RS1D</h3>
    <p>El RS1D contiene un <span class="dato">geófono</span> que mide la velocidad del suelo en nanómetros por segundo (nm/s). Esta señal es enviada desde la laptop local de investigación hacia este servidor en la nube en tiempo real.</p>
  </div>

  <button class="btn" id="btn" onclick="descargarTicket()">Descargar Ticket</button>
  <div class="ts" id="ts">Actualizando...</div>

  <script>
    function actualizarImg() {
      const img = document.getElementById('img');
      img.src = '/sismograma?t=' + Date.now();
    }

    function actualizarRelojes() {
      const ahora = new Date();
      const utc = ahora.toUTCString().slice(-12, -4);
      const mx  = ahora.toLocaleTimeString('es-MX', {timeZone: 'America/Mexico_City', hour12: false});
      document.getElementById('hora-utc').textContent = utc;
      document.getElementById('hora-mx').textContent  = mx;
    }

    function actualizarEstado() {
      fetch('/estado')
        .then(r => r.json())
        .then(d => {
          document.getElementById('ultimo').textContent  = d.ultimo_evento || '—';
          document.getElementById('nevents').textContent = d.eventos_hoy;
          document.getElementById('ts').textContent      = 'Último reporte de la laptop: ' + d.hora;

          const b      = document.getElementById('badge');
          const banner = document.getElementById('banner');

          if (!d.conectado) {
            b.textContent = 'Estación Offline'; b.className = 'badge offline';
            banner.classList.remove('visible');
          } else if (d.evento_activo) {
            b.textContent = 'EVENTO'; b.className = 'badge alerta';
            banner.classList.add('visible');
          } else {
            b.textContent = 'En vivo'; b.className = 'badge';
            banner.classList.remove('visible');
          }
        }).catch(() => {});
    }

    function descargarTicket() {
      const btn = document.getElementById('btn');
      btn.disabled = true;
      btn.textContent = 'Descargando...';
      
      const a = document.createElement('a');
      a.href = '/ticket?t=' + Date.now();
      a.download = 'sismograma_nube.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      
      setTimeout(() => {
        btn.textContent = 'Descargar Ticket';
        btn.disabled = false;
      }, 2000);
    }

    setInterval(actualizarImg, 5000);
    setInterval(actualizarEstado, 3000);
    setInterval(actualizarRelojes, 1000);
    actualizarEstado();
    actualizarRelojes();
  </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML, station=STATION)

@app.route('/sismograma')
def sismograma():
    if os.path.exists(PLOT_PATH):
        return send_file(PLOT_PATH, mimetype='image/png')
    return 'Sin datos aún', 404

@app.route('/ticket')
def ticket():
    if os.path.exists(TICKET_PATH):
        return send_file(TICKET_PATH, mimetype='image/png', as_attachment=True, download_name='sismograma_ENES.png')
    return 'Ticket no disponible', 404

@app.route('/estado')
def get_estado():
    return jsonify(estado_web)

# endpoint receptor: Aquí es donde tu laptop enviará los archivos y variables
@app.route('/update_data', methods=['POST'])
def update_data():
    try:
        global estado_web
        estado_web['ultimo_evento'] = request.form.get('ultimo_evento')
        estado_web['eventos_hoy'] = int(request.form.get('eventos_hoy', 0))
        estado_web['evento_activo'] = request.form.get('evento_activo') == 'True'
        estado_web['conectado'] = request.form.get('conectado') == 'True'
        estado_web['hora'] = request.form.get('hora')

        if 'sismograma' in request.files:
            request.files['sismograma'].save(PLOT_PATH)
        if 'ticket' in request.files:
            request.files['ticket'].save(TICKET_PATH)

        return jsonify(status="success")
    except Exception as e:
        return jsonify(status="error", message=str(e)), 500

if __name__ == '__main__':
    # Render asigna dinámicamente un puerto en la variable PORT
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=puerto)