#!/bin/bash
# =============================================================
#  INSTALADOR COMPLETO — Raspberry Pi 3 como Hotspot
#  Sistema Sismográfico ENES Morelia / Geociencias UNAM
#
#  USO: bash instalar_pi3.sh
#
#  EJECUTAR MIENTRAS EL PI 3 ESTÁ CONECTADO AL ROUTER DEL WIFI
#  Este script configura todo automáticamente:
#  - Hotspot WiFi "RasPiEnesMor"
#  - DHCP para WiFi y ethernet
#  - IP fija para el RS1D
#  - Enrutamiento NAT entre WiFi y ethernet
#  - Arranque automático de todos los servicios
# =============================================================

set -e   # detener si hay error

# Colores para mensajes
VERDE='\033[0;32m'
ROJO='\033[0;31m'
AMARILLO='\033[1;33m'
NC='\033[0m'   # sin color

ok()  { echo -e "${VERDE}[OK]${NC} $1"; }
err() { echo -e "${ROJO}[ERROR]${NC} $1"; }
info(){ echo -e "${AMARILLO}[INFO]${NC} $1"; }

echo "============================================================="
echo "  Instalador Sistema Sismográfico ENES Morelia"
echo "  Raspberry Pi 3 — Hotspot + Enrutamiento"
echo "============================================================="
echo ""

# ── PASO 1: Actualizar sistema ─────────────────────────────────
info "Paso 1/8: Actualizando sistema..."
sudo apt update -q && sudo apt upgrade -y -q
ok "Sistema actualizado"

# ── PASO 2: Instalar paquetes ──────────────────────────────────
info "Paso 2/8: Instalando paquetes necesarios..."
sudo apt install -y -q hostapd dnsmasq iptables-persistent
ok "Paquetes instalados"

# ── PASO 3: Configurar hostapd ─────────────────────────────────
info "Paso 3/8: Configurando hotspot WiFi..."

sudo tee /etc/hostapd/hostapd.conf > /dev/null << 'EOF'
# Interfaz WiFi del Pi 3
interface=wlan0
driver=nl80211

# Nombre y contraseña del hotspot
ssid=RasPiEnesMor
wpa_passphrase=RaspberryShake3n3s

# Configuración regional México
country_code=MX
hw_mode=g
channel=7

# Seguridad WPA2
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
auth_algs=1
ignore_broadcast_ssid=0
EOF

sudo systemctl unmask hostapd
sudo systemctl enable hostapd
ok "Hostapd configurado — WiFi: RasPiEnesMor"

# ── PASO 4: Configurar dnsmasq ─────────────────────────────────
info "Paso 4/8: Configurando servidor DHCP..."

# Hacer backup del archivo original
sudo cp /etc/dnsmasq.conf /etc/dnsmasq.conf.backup

sudo tee -a /etc/dnsmasq.conf > /dev/null << 'EOF'

# ── Configuración ENES Morelia ──────────────────────────────────

# DHCP para dispositivos en el hotspot WiFi 
interface=wlan0
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
domain=wlan
address=/gw.wlan/192.168.4.1

# DHCP para el Raspberry Shake RS1D (por ethernet)
interface=eth0
dhcp-range=eth0,192.168.1.100,192.168.1.150,255.255.255.0,24h

# IP fija para el RS1D — actualizar la MAC si cambia el dispositivo
# Para encontrar la MAC: conectar el RS1D, esperar 2 min, ejecutar: arp -a
dhcp-host=b8:27:eb:f6:08:7b,192.168.1.145
EOF

ok "DNSMASQ configurado"

# ── PASO 5: Servicio para asignar IPs ──────────────────────────
info "Paso 5/8: Creando servicio de IPs estáticas..."

sudo tee /etc/systemd/system/wlan-ip.service > /dev/null << 'EOF'
[Unit]
Description=Asignar IPs estaticas para hotspot y ethernet
After=network.target hostapd.service
Wants=hostapd.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c '/sbin/ip addr add 192.168.4.1/24 dev wlan0 2>/dev/null || true'
ExecStartPost=/bin/bash -c 'sleep 5 && /sbin/ip addr add 192.168.1.200/24 dev eth0 2>/dev/null || true'
ExecStartPost=/bin/bash -c 'sleep 6 && /bin/systemctl restart dnsmasq'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable wlan-ip.service
ok "Servicio wlan-ip creado y habilitado"

# ── PASO 6: Configurar enrutamiento NAT ───────────────────────
info "Paso 6/8: Configurando enrutamiento NAT..."

# Activar ip_forward permanentemente
sudo sed -i '/net.ipv4.ip_forward/d' /etc/sysctl.conf
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf > /dev/null
sudo sysctl -w net.ipv4.ip_forward=1

# Crear script rc.local con todas las reglas
sudo tee /etc/rc.local > /dev/null << 'EOF'
#!/bin/bash
# Script de arranque automático — ENES Morelia
# Se ejecuta cada vez que el Pi 3 arranca

# Espera a que las interfaces estén completamente listas
sleep 20

# Activa el reenvío de paquetes entre interfaces de red
sysctl -w net.ipv4.ip_forward=1

# Limpia reglas iptables anteriores para evitar duplicados
iptables -t nat -F
iptables -F FORWARD

# NAT: disfraza el tráfico de la red WiFi (192.168.4.x)
# para que el RS1D (192.168.1.145) lo acepte
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

# Permite el reenvío de paquetes WiFi → ethernet (hacia el RS1D)
iptables -A FORWARD -i wlan0 -o eth0 -j ACCEPT

# Permite el reenvío de respuestas ethernet → WiFi (del RS1D hacia la laptop)
iptables -A FORWARD -i eth0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT

exit 0
EOF

sudo chmod +x /etc/rc.local
ok "Enrutamiento NAT configurado"

# ── PASO 7: Configurar crontab ─────────────────────────────────
info "Paso 7/8: Configurando crontab para ethernet..."

# Agregar tarea cron para asignar IP a eth0 al arrancar
(sudo crontab -l 2>/dev/null | grep -v "ip addr add 192.168.1.200"; \
 echo "@reboot sleep 15 && /sbin/ip link set eth0 up; /sbin/ip addr add 192.168.1.200/24 dev eth0 2>/dev/null; /bin/systemctl restart dnsmasq") \
 | sudo crontab -
ok "Crontab configurado"

# ── PASO 8: Verificación final ─────────────────────────────────
info "Paso 8/8: Verificación de configuración..."

echo ""
echo "============================================================="
echo "  Configuración completada exitosamente"
echo "============================================================="
echo ""
echo "  WiFi creado:      RasPiEnesMor"
echo "  Contraseña:       RaspberryShake3n3s"
echo "  IP del Pi 3:      192.168.4.1"
echo "  IP del RS1D:      192.168.1.145 (fija)"
echo ""
echo "  SIGUIENTE PASO:"
echo "  1. Desconectar el cable ethernet del router"
echo "  2. Conectar el cable ethernet del RS1D al Pi 3"
echo "  3. Reiniciar: sudo reboot"
echo ""
echo "  DESPUÉS DEL REINICIO verificar:"
echo "  - Conectarse al WiFi 'RasPiEnesMor'"
echo "  - ping 192.168.1.145 debe responder"
echo "============================================================="
