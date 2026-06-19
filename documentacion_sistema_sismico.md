# Sistema Sismográfico Autónomo — ENES Morelia / Geociencias UNAM

**Proyecto:** Sismógrafo portátil para divulgación científica  
**Estación:** AM.R087B.00 — Raspberry Shake RS1D  
**Autores:** Itzel Rojas López, Geociencias ENES Morelia, UNAM  
**Fecha:** Mayo 2026  

---

## Índice

1. [Descripción general del sistema](#1-descripción-general-del-sistema)
2. [Materiales necesarios](#2-materiales-necesarios)
3. [Arquitectura de red](#3-arquitectura-de-red)
4. [Configuración del Raspberry Pi 3 como hotspot](#4-configuración-del-raspberry-pi-3-como-hotspot)
5. [Configuración del enrutamiento de red](#5-configuración-del-enrutamiento-de-red)
6. [Código Python — Sistema de visualización](#6-código-python--sistema-de-visualización)
7. [Configuración de la laptop Windows](#7-configuración-de-la-laptop-windows)
8. [Procedimiento de arranque](#9-procedimiento-de-arranque)
9. [Parámetros técnicos del sistema](#10-parámetros-técnicos-del-sistema)
10. [Solución de problemas frecuentes](#11-solución-de-problemas-frecuentes)
11. [Guía de replicación completa](#12-guía-de-replicación-completa)

---

## 1. Descripción general del sistema

El sistema es un sismógrafo portátil completamente autónomo diseñado para divulgación científica. Permite visualizar en tiempo real los movimientos del suelo detectados por el sensor RS1D en una tablet o laptop, sin necesidad de conexión a internet.

### Funcionamiento

El **Raspberry Shake RS1D** contiene un geófono — un sensor de velocidad que funciona como un "micrófono de la Tierra". Dentro del geófono hay una bobina suspendida sobre un imán por un resorte. Cuando el suelo se mueve, la bobina se desplaza y genera una señal eléctrica proporcional a la velocidad del suelo en nanómetros por segundo (nm/s). Esta señal es digitalizada a 100 muestras por segundo por el digitalizador Shake Board.

Los datos son transmitidos en tiempo real usando el protocolo **SeedLink** (estándar internacional para datos sísmicos) en el puerto 18000. Un script Python en la laptop lee estos datos, los procesa, genera gráficas y los publica en una página web accesible desde cualquier dispositivo en la red local.

### Flujo de datos

```
RS1D ──(ethernet)──► Raspberry Pi 3 ──(WiFi hotspot)──► Laptop
                                                              │
                                                    ┌─────────┴──────────┐
                                                  Tablet             Impresora
                                              (sismograma)           térmica
```

---

## 2. Materiales necesarios

| Material | Especificaciones | Notas |
|---|---|---|
| Raspberry Shake RS1D | Modelo con geófono vertical | Estación AM.R087B |
| Raspberry Pi 3 Model B+ | Con WiFi integrado | Actúa como hotspot |
| Laptop Windows | Python 3.x instalado | Procesa y sirve los datos |
| Tablet | Con navegador web | Visualiza el sismograma |
| Cable ethernet | Cat5e o superior | Conecta RS1D ↔ Pi 3 |
| MicroSD | 8 GB mínimo, Clase 10 | Para el Pi 3 |
| Fuente de alimentación Pi 3 | **Micro USB, mínimo 2.5A** | Crítico: cable de datos+carga |
| Fuente de alimentación RS1D | Cable USB original | Incluido con el RS1D |
| Power bank | 20,000 mAh, 2.4A por puerto | Para uso en campo |

> ⚠️ **IMPORTANTE:** El cable micro USB del Pi 3 debe ser de **datos y carga** con capacidad de al menos 2.5A. Un cable de baja calidad o solo carga causa corrupción de la microSD.

---

## 3. Arquitectura de red

El sistema usa tres redes IP diferentes que conviven simultáneamente:

| Red | Interfaz | Rango | Propósito |
|---|---|---|---|
| WiFi hotspot | Pi 3 — wlan0 | 192.168.4.0/24 | Laptop y tablet se conectan aquí |
| Ethernet interna | Pi 3 — eth0 | 192.168.1.0/24 | Comunicación Pi 3 ↔ RS1D |
| — | RS1D | 192.168.1.145 | IP fija asignada por DHCP |

El Pi 3 actúa como **router** entre las dos redes: recibe el tráfico de la red WiFi (192.168.4.x) y lo reenvía hacia el RS1D (192.168.1.145) usando NAT (Network Address Translation).

---

## 4. Configuración del Raspberry Pi 3 como hotspot

### 4.1 Instalación del sistema operativo

1. Descargar **Raspberry Pi Imager** desde https://www.raspberrypi.com/software/
2. Insertar la microSD en la laptop
3. En el Imager seleccionar:
   - **Dispositivo:** Raspberry Pi 3
   - **Sistema operativo:** Raspberry Pi OS Lite (32-bit)
   - **Almacenamiento:** la microSD
4. Hacer clic en **Editar ajustes** y configurar:

```
Hostname:     shakenes
Usuario:      shakenes
Contraseña:   shakemes
SSH:          Activado (usar contraseña)
País WiFi:    MX
Zona horaria: America/Mexico_City
```

5. Grabar y esperar a que diga "Escritura exitosa"

### 4.2 Primera conexión

Conectar el Pi 3 al router de casa por ethernet, encenderlo y esperar 1 minuto. Conectarse por SSH desde la laptop:

```bash
ssh shakenes@<IP-asignada-por-router>
# Contraseña: shakemes
```

Si no se conoce la IP, usar **Advanced IP Scanner** para encontrarla.

> **Problema encontrado:** La primera vez el SSH rechazaba la contraseña con "Permission denied". Solución: entrar por monitor/teclado físico al Pi 3, ejecutar `passwd` para resetear la contraseña, y editar `/etc/ssh/sshd_config` para asegurar que `PasswordAuthentication yes` esté activo.

### 4.3 Instalar paquetes necesarios

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y hostapd dnsmasq iptables-persistent
```

Durante la instalación de `iptables-persistent` responder **Yes** a ambas preguntas sobre guardar reglas.

### 4.4 Configurar hostapd (punto de acceso WiFi)

```bash
sudo nano /etc/hostapd/hostapd.conf
```

Contenido del archivo:

```
interface=wlan0
driver=nl80211
ssid=RasPiEnesMor
hw_mode=g
channel=7
country_code=MX
wpa=2
wpa_passphrase=RaspberryShake3n3s
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
auth_algs=1
ignore_broadcast_ssid=0
```

Activar hostapd:

```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
```

### 4.5 Configurar dnsmasq (servidor DHCP)

```bash
sudo nano /etc/dnsmasq.conf
```

Agregar al final del archivo:

```
# DHCP para la red WiFi del hotspot
interface=wlan0
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
domain=wlan
address=/gw.wlan/192.168.4.1

# DHCP para la red ethernet (RS1D)
interface=eth0
dhcp-range=eth0,192.168.1.100,192.168.1.150,255.255.255.0,24h

# IP fija para el RS1D (usar la MAC address real del RS1D)
# La MAC se obtiene con: arp -a (después de conectar el RS1D)
dhcp-host=b8:27:eb:f6:08:7b,192.168.1.145
```

### 4.6 Crear servicio para asignar IPs al arrancar

Este servicio asigna automáticamente las IPs a wlan0 y eth0 cada vez que el Pi 3 arranca:

```bash
sudo nano /etc/systemd/system/wlan-ip.service
```

Contenido:

```ini
[Unit]
Description=Asignar IPs estaticas para hotspot y ethernet
After=network.target hostapd.service sys-subsystem-net-devices-eth0.device
Wants=hostapd.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c '/sbin/ip addr add 192.168.4.1/24 dev wlan0 2>/dev/null || true'
ExecStartPost=/bin/bash -c 'sleep 5 && /sbin/ip addr add 192.168.1.200/24 dev eth0 2>/dev/null || true'
ExecStartPost=/bin/bash -c 'sleep 6 && /bin/systemctl restart dnsmasq'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable wlan-ip.service
```

### 4.7 Configurar /etc/rc.local para el enrutamiento

```bash
sudo nano /etc/rc.local
```

Reemplazar todo el contenido con:

```bash
#!/bin/bash

# Espera a que las interfaces estén listas
sleep 20

# Activa reenvío de paquetes entre interfaces
sysctl -w net.ipv4.ip_forward=1

# Limpia reglas anteriores para evitar duplicados
iptables -t nat -F
iptables -F FORWARD

# Configura NAT y reenvío entre wlan0 (WiFi) y eth0 (ethernet RS1D)
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
iptables -A FORWARD -i wlan0 -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT

exit 0
```

```bash
sudo chmod +x /etc/rc.local
```

### 4.8 Configurar crontab para la IP de ethernet

```bash
sudo crontab -e
```

Agregar esta línea:

```
@reboot sleep 15 && /sbin/ip link set eth0 up; /sbin/ip addr add 192.168.1.200/24 dev eth0 2>/dev/null; /bin/systemctl restart dnsmasq
```

### 4.9 Activar ip_forward permanentemente

```bash
sudo sed -i '/net.ipv4.ip_forward/d' /etc/sysctl.conf
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
```

### 4.10 Reiniciar y verificar

```bash
sudo reboot
```

Después del reinicio, conectar el WiFi **RasPiEnesMor** (contraseña: `RaspberryShake3n3s`) y verificar:

```bash
ssh shakenes@192.168.4.1
ip addr show wlan0   # debe mostrar 192.168.4.1
ip addr show eth0    # debe mostrar 192.168.1.200
arp -a               # debe mostrar el RS1D en 192.168.1.145
```

---

## 5. Configuración del enrutamiento de red

### 5.1 Problema encontrado y solución

El RS1D está en la red `192.168.1.x` y la laptop en la red `192.168.4.x`. Sin configuración adicional, la laptop no puede alcanzar al RS1D porque son redes diferentes.

**Solución:** Agregar una ruta estática permanente en Windows que indica que el tráfico hacia `192.168.1.x` debe pasar por el Pi 3 (`192.168.4.1`).

### 5.2 En la laptop Windows (PowerShell como Administrador)

```bash
# Agregar ruta permanente (-p = persistente, sobrevive reinicios)
route add 192.168.1.0 mask 255.255.255.0 192.168.4.1 -p
```

Verificar conectividad:

```bash
ping 192.168.1.145
# Debe responder con 0% pérdida
```

> **Problema encontrado:** La ruta existía pero el tráfico iba al WiFi de casa (`192.168.1.15`) en lugar de al Pi 3. Solución: asegurarse de estar conectado **SOLO** al WiFi `RasPiEnesMor`, no al WiFi de casa. Si hay conflicto, eliminar la ruta y agregarla de nuevo:
> ```bash
> route delete 192.168.1.0
> route add 192.168.1.0 mask 255.255.255.0 192.168.4.1 -p
> ```

> **Problema encontrado:** Tailscale instalado en la laptop interfería con las rutas. Solución: desactivar Tailscale con `tailscale down` antes de usar el sistema.

---

## 6. Código Python — Sistema de visualización

El archivo `shake_laptop.py` es el corazón del sistema. Realiza tres funciones simultáneas en hilos paralelos:

1. **Hilo SeedLink:** se conecta al RS1D y recibe datos en tiempo real
2. **Hilo de procesamiento:** filtra los datos, genera la gráfica y detecta eventos
3. **Servidor web Flask:** publica la página web accesible desde la tablet

### 6.1 Instalación de dependencias

```bash
pip install obspy matplotlib Pillow flask
```

### 6.2 Parámetros configurables

Al inicio del archivo `shake_laptop.py` se encuentran todos los parámetros que pueden necesitar ajuste:

```python
# IP del Raspberry Shake en la red del hotspot
SHAKE_IP   = '192.168.1.145'  # cambiar si el RS1D obtiene una IP diferente
SHAKE_PORT = 18000             # puerto SeedLink (nunca cambia)

# Identificación de la estación
NETWORK  = 'AM'      # red Raspberry Shake
STATION  = 'R087B'   # código único de la estación
CHANNEL  = 'EHZ'     # canal vertical de alta frecuencia

# Detección de eventos (algoritmo STA/LTA)
STA_SEC    = 1.0   # ventana corta en segundos
LTA_SEC    = 10.0  # ventana larga en segundos
UMBRAL_ON  = 6.0   # umbral de activación (más alto = menos sensible)
UMBRAL_OFF = 2.5   # umbral de desactivación

# Visualización
VENTANA_SEG = 30   # segundos mostrados en la gráfica
```

### 6.3 Algoritmo de detección STA/LTA

El algoritmo **STA/LTA** (Short Term Average / Long Term Average) es el método estándar en sismología para detectar eventos automáticamente:

- **STA:** promedio de energía en una ventana corta (1 segundo) — detecta cambios bruscos
- **LTA:** promedio de energía en una ventana larga (10 segundos) — representa el ruido de fondo
- Cuando **STA/LTA > UMBRAL_ON** (6.0), se declara un evento sísmico
- Cuando **STA/LTA < UMBRAL_OFF** (2.5), el evento termina

Además del ratio STA/LTA, se verifica que la amplitud máxima sea al menos 5 veces el nivel de ruido de fondo para evitar falsas alarmas.

### 6.4 Filtro pasa-bandas

Antes de graficar, los datos pasan por un filtro pasa-bandas de **1 a 20 Hz**:

- **< 1 Hz** se elimina: ruido lento de fondo, deriva del sensor, vibraciones de viento
- **1 a 20 Hz** se conserva: ondas sísmicas reales, pasos humanos, tráfico
- **> 20 Hz** se elimina: ruido eléctrico de alta frecuencia

### 6.5 Escala dinámica

La escala Y de la gráfica se calcula dinámicamente sobre los **últimos 5 segundos** de datos usando el percentil 99, con un margen del 30% y un mínimo de 200 nm/s. Esto garantiza que:

- La señal siempre sea visible sin saturar la pantalla
- Un golpe fuerte no "bloquee" la escala por los siguientes 30 segundos
- El ruido de fondo normal sea visible cuando no hay eventos

### 6.6 Conversión de unidades

Los datos crudos del RS1D son cuentas digitales. Se convierten a nm/s usando la sensibilidad del geófono:

```
velocidad (nm/s) = cuentas / 1,500,000,000 × 1,000,000,000
```

La sensibilidad del RS1D es aproximadamente **1.5 × 10⁹ cuentas/(m/s)**.

---

## 7. Configuración de la laptop Windows

### 7.1 Instalar Python

1. Descargar desde https://www.python.org/downloads/
2. Durante la instalación marcar **"Add Python to PATH"**
3. Verificar: `python --version`

### 7.2 Instalar librerías

```bash
pip install obspy matplotlib Pillow flask
```

### 7.3 Estructura de carpetas

```
C:\Users\<usuario>\Desktop\archivos_raspshake\
├── shake_laptop.py          ← script principal
├── logos\
│   ├── logo_enes.png        ← logo ENES Morelia
│   └── logo_geociencias.png ← logo Geociencias UNAM
└── webapp\
    └── static\              ← imágenes generadas (auto)
```

```
C:\sismogramas\              ← imágenes y tickets (auto)
├── sismograma.png
├── ticket.png
└── shake.log
```

### 7.4 Ejecutar el sistema

Siempre ejecutar desde **PowerShell como Administrador**:

```bash
cd C:\Users\<usuario>\Desktop\archivos_raspshake
python shake_laptop.py
```

Abrir el navegador en: `http://127.0.0.1:5000`

Para la tablet: `http://192.168.4.41:5000` (usar la IP que muestra el script al arrancar)

---

## 8. Procedimiento de arranque

### Orden correcto para encender el sistema

1. **Conectar el cable ethernet** entre el RS1D y el Pi 3
2. **Conectar la corriente al Pi 3** — esperar 2 minutos a que arranque
3. **Conectar la corriente al RS1D** — esperar 1 minuto a que arranque
4. **En la laptop:** conectarse al WiFi **RasPiEnesMor** (contraseña: `RaspberryShake3n3s`)
5. **En PowerShell Administrador:** ejecutar `python shake_laptop.py`
6. **Abrir navegador** en `http://127.0.0.1:5000`

### Verificación rápida

```bash
# Verificar que el RS1D es accesible
ping 192.168.1.145

# Debe responder con 0% pérdida
```

### Orden para apagar

1. Cerrar el script con `Ctrl+C`
2. Desconectar la corriente del RS1D
3. Desconectar la corriente del Pi 3

---

## 9. Parámetros técnicos del sistema

| Parámetro | Valor | Descripción |
|---|---|---|
| Frecuencia de muestreo | 100 Hz | 100 muestras por segundo |
| Canal | EHZ | Extra High freq, componente Z (vertical) |
| Sensibilidad del geófono | 1.5 × 10⁹ cuentas/(m/s) | Conversión cuentas a velocidad |
| Unidades de visualización | nm/s | Nanómetros por segundo |
| Ventana de visualización | 30 segundos | Datos mostrados en pantalla |
| Filtro pasa-bandas | 1 — 20 Hz | Elimina ruido de baja y alta frecuencia |
| STA (ventana corta) | 1 segundo | Para detección de eventos |
| LTA (ventana larga) | 10 segundos | Referencia de ruido de fondo |
| Umbral de activación | 6.0 | Ratio STA/LTA para declarar evento |
| Cooldown entre eventos | 30 segundos | Tiempo mínimo entre alertas |
| Actualización de gráfica | 5 segundos | Frecuencia de refresco |
| Puerto web | 5000 | Puerto del servidor Flask |
| Puerto SeedLink | 18000 | Puerto del RS1D |

---

## 10. Solución de problemas frecuentes

### Problema: "SeedLink desconectado" en el script

**Causa:** La laptop no puede alcanzar la IP `192.168.1.145`  
**Verificar:**
```bash
ping 192.168.1.145
```
**Soluciones:**
- Verificar que la laptop está conectada al WiFi `RasPiEnesMor` y NO al WiFi de casa
- Si la ruta no existe: `route add 192.168.1.0 mask 255.255.255.0 192.168.4.1 -p`
- Si hay conflicto de rutas: `route delete 192.168.1.0` y luego agregar de nuevo
- Desactivar Tailscale si está instalado: `tailscale down`

### Problema: El hotspot WiFi no aparece

**Causa:** El servicio `wlan-ip` no asignó la IP a wlan0  
**Solución:** Conectar el Pi 3 al monitor y ejecutar:
```bash
sudo ip addr add 192.168.4.1/24 dev wlan0
sudo systemctl restart dnsmasq
sudo systemctl restart hostapd
```

### Problema: El RS1D no aparece en `arp -a`

**Causa:** El Pi 3 no tiene IP en eth0 para servir DHCP al RS1D  
**Solución:**
```bash
sudo ip addr add 192.168.1.200/24 dev eth0
sudo systemctl restart dnsmasq
# Reiniciar el RS1D desconectando y reconectando su corriente
# Esperar 2 minutos y verificar con: arp -a
```

### Problema: La microSD del Pi 3 se corrompió

**Causa:** Cable de alimentación de mala calidad o insuficiente corriente  
**Solución:**
1. Usar un cable micro USB de calidad con al menos 2.5A
2. Usar un cargador de 67W o superior
3. Grabar la microSD de nuevo con Raspberry Pi Imager
4. Repetir toda la configuración desde la sección 4

### Problema: La gráfica se satura o las ondas no se ven

**Causa:** El nivel de ruido ambiental es alto o el sensor está cerca de una fuente de vibración  
**Soluciones:**
- Alejar el RS1D de computadoras, ventiladores y fuentes de vibración
- Colocar el RS1D sobre una superficie sólida (no sobre una mesa de madera)
- Si sigue saturado, aumentar `UMBRAL_ON` en el código (de 6.0 a 8.0)

### Problema: El sistema detecta eventos constantemente sin golpes reales

**Causa:** El umbral STA/LTA es demasiado bajo para el nivel de ruido del ambiente  
**Solución:** En `shake_laptop.py` aumentar el umbral:
```python
UMBRAL_ON = 8.0   # más restrictivo
```

### Problema: SSH dice "Permission denied"

**Causa:** La contraseña no se configuró correctamente en el Imager  
**Solución:** Conectar el Pi 3 al monitor y ejecutar:
```bash
passwd
# Ingresar nueva contraseña: shakemes
sudo nano /etc/ssh/sshd_config
# Verificar: PasswordAuthentication yes
sudo systemctl restart ssh
```

---

## 11. Guía de replicación completa

Si se necesita replicar el sistema desde cero (por formateo de microSD u otro motivo), seguir estos pasos en orden:

### Paso 1 — Grabar microSD del Pi 3
Seguir la sección 4.1 completamente.

### Paso 2 — Configurar el Pi 3
Ejecutar los comandos de las secciones 4.2 a 4.10 en orden.

### Paso 3 — Verificar la MAC del RS1D
Después de conectar el RS1D al Pi 3 por ethernet y reiniciar ambos:
```bash
arp -a
# Anotar la MAC address del raspberryshake (formato b8:27:eb:xx:xx:xx)
```
Actualizar la MAC en `/etc/dnsmasq.conf`:
```
dhcp-host=<MAC-del-RS1D>,192.168.1.145
```

### Paso 4 — Configurar la laptop
Seguir la sección 7 completa.

### Paso 5 — Agregar la ruta permanente
```bash
# En PowerShell Administrador
route add 192.168.1.0 mask 255.255.255.0 192.168.4.1 -p
```

### Paso 6 — Colocar los logos
Copiar los archivos en la carpeta del script:
```
logos/logo_enes.png
logos/logo_geociencias.png
```

### Paso 7 — Prueba final
1. Encender Pi 3 → esperar 2 min
2. Conectar RS1D → esperar 1 min
3. Conectar laptop al WiFi `RasPiEnesMor`
4. Ejecutar `python shake_laptop.py`
5. Verificar que el sismograma aparece en `http://127.0.0.1:5000`

---

## Credenciales y datos de acceso

| Servicio | Usuario | Contraseña |
|---|---|---|
| SSH al Pi 3 | shakenes | shakemes |
| WiFi hotspot | — | RaspberryShake3n3s |
| RS1D (Raspberry Shake) | myshake | shakeme |
| Página web | — | Sin contraseña (red local) |

**Nombre del WiFi:** `RasPiEnesMor`  
**IP del Pi 3:** `192.168.4.1`  
**IP del RS1D:** `192.168.1.145`  
**IP de la laptop en el hotspot:** `192.168.4.41` (puede variar)  
**Página web:** `http://192.168.4.41:5000` (desde la tablet)

---

*Itzel Rojas López, Geociencias ENES Morelia — Universidad Nacional Autónoma de México*  
*Sistema desarrollado para divulgación científica de fenómenos sísmicos*
