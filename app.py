# app.py
from flask import Flask, render_template, Response, jsonify
from camera import Camera
import os
from datetime import datetime

app = Flask(__name__)

# Crea una carpeta para las capturas si no existe
if not os.path.exists('captures'):
    os.makedirs('captures')

@app.route('/')
def index():
    return render_template('index.html')

def gen(camera):
    while True:
        frame = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen(Camera()),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# --- NUEVA RUTA PARA CAPTURAR ---
@app.route('/capture')
def capture():
    # Generamos un nombre de archivo único con la fecha y hora
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"captures/capture_{timestamp}.jpg"

    # Obtenemos un frame de la cámara y lo guardamos
    camera = Camera()
    frame_bytes = camera.get_frame()
    with open(filename, 'wb') as f:
        f.write(frame_bytes)

    # Devolvemos un mensaje de éxito en formato JSON
    return jsonify(message=f"¡Imagen guardada como {filename}!")
# --------------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)