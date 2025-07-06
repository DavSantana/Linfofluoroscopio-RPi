# app.py (Versión final con objeto de cámara compartido)

import os
import sqlite3
from datetime import datetime
from flask import Flask, Response, render_template, jsonify
from camera import Camera # No hay cambios en camera.py, se queda como está

# 1. Inicialización de la aplicación Flask
app = Flask(__name__)

# --- CAMBIO 1: CREAMOS UNA ÚNICA INSTANCIA DE LA CÁMARA AQUÍ ---
# Este objeto 'camera' será compartido por todas las funciones.
camera = Camera()
# -------------------------------------------------------------

# 2. Configuración inicial de la base de datos
def init_db():
    try:
        conn = sqlite3.connect('linfoscopio.db')
        print("Base de datos abierta con éxito")
        conn.execute('CREATE TABLE IF NOT EXISTS captures (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, image_path TEXT)')
        print("Tabla creada o ya existente.")
        conn.close()
    except Exception as e:
        print(f"Error al inicializar la base de datos: {e}")
init_db()

# 3. Definición de las rutas
@app.route('/')
def index():
    return render_template('index.html')

def gen(camera_obj):
    """Función generadora que ahora recibe el objeto de cámara."""
    while True:
        frame = camera_obj.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    # --- CAMBIO 2: PASAMOS EL OBJETO GLOBAL A LA FUNCIÓN 'gen' ---
    return Response(gen(camera),
                    mimetype='multipart/x-mixed-replace; boundary=frame')
    # -----------------------------------------------------------

@app.route('/capture')
def capture():
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"captures/capture_{timestamp}.jpg"
        
        if not os.path.exists('captures'):
            os.makedirs('captures')
        
        # --- CAMBIO 3: USAMOS EL OBJETO GLOBAL, NO CREAMOS UNO NUEVO ---
        frame_bytes = camera.get_frame()
        # ---------------------------------------------------------------
        
        # Guardamos la imagen en un archivo
        with open(filename, 'wb') as f:
            f.write(frame_bytes)
        
        # Guardamos el registro en la base de datos
        with sqlite3.connect("linfoscopio.db") as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO captures (timestamp, image_path) VALUES (?,?)", (timestamp, filename))
            conn.commit()
            message = f"¡Imagen guardada en {filename} y registrada en la DB!"
            
    except Exception as e:
        message = f"Error en la captura: {e}"

    return jsonify(message=message)

# 4. El bloque que inicia el servidor
if __name__ == '__main__':
    print("Iniciando servidor Flask...")
    # Usamos threaded=True para un mejor manejo de peticiones simultáneas
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True, use_reloader=False)