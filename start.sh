#!/bin/bash

# Activa el entorno virtual de tu proyecto
source /home/dasan/Documents/Linfofluoroscopio/venv/bin/activate

# Espera 15 segundos para dar tiempo a que los servicios de red se inicien
sleep 15

# Verifica si hay conexión a internet haciendo ping a un servidor de Google
ping -c 1 8.8.8.8

# Si el comando anterior (ping) fue exitoso (código de salida 0), inicia la app
if [ $? -eq 0 ]; then
    echo "Conexión detectada. Iniciando aplicación Linfofluoroscopio..."
    # Ejecuta tu aplicación Flask
    python3 /home/dasan/Documents/Linfofluoroscopio/app.py
else
    # Si no hay conexión, inicia el portal cautivo de WiFi Connect
    echo "No hay conexión. Iniciando portal de configuración WiFi..."
    sudo wifi-connect
fi
