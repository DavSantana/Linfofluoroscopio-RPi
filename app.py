from flask import Flask, render_template, Response, request
from camera import Camera
import time  # Para timestamp de archivos

app = Flask(__name__)
camera = Camera()

@app.route('/')
def index():
    return render_template('index.html')  # Página principal

@app.route('/video_feed')
def video_feed():
    def generate():
        while True:
            frame = camera.get_frame()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

# NUEVA FUNCIÓN AGREGADA AQUÍ ⬇️
@app.route('/capture', methods=['POST'])
def capture():
    frame = camera.get_frame()
    if frame:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        with open(f"capturas/{timestamp}.jpg", "wb") as f:
            f.write(frame)
        return "Imagen guardada", 200
    return "Error al capturar", 500

# NO olvides este bloque al final
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)



