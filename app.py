# app.py (Versión con Capturas Asociadas a Pacientes)

import os
import sqlite3
from datetime import datetime
from flask import Flask, Response, render_template, jsonify, request
from camera import Camera

# --- INICIALIZACIÓN CENTRAL ---
app = Flask(__name__)
# Creamos UNA SOLA instancia de la cámara que será compartida por toda la aplicación.
camera = Camera()
# -----------------------------

def init_db():
    """Inicializa la base de datos y crea las tablas si no existen."""
    try:
        with sqlite3.connect('linfoscopio.db') as conn:
            print("Base de datos abierta con éxito")
            conn.execute('''
                CREATE TABLE IF NOT EXISTS patients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cedula TEXT NOT NULL UNIQUE,
                    nombre TEXT NOT NULL,
                    apellido TEXT NOT NULL,
                    edad INTEGER,
                    telefono TEXT
                )
            ''')
            print("Tabla 'patients' creada o ya existente.")
            
            # --- CAMBIO 1: MODIFICAMOS LA TABLA 'captures' ---
            # Añadimos la columna 'patient_id' y la definimos como una clave foránea
            # que se relaciona con la tabla 'patients'.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER, 
                    timestamp TEXT,
                    image_path TEXT,
                    FOREIGN KEY (patient_id) REFERENCES patients (id)
                )
            ''')
            print("Tabla 'captures' actualizada o ya existente.")
            # ----------------------------------------------------
    except Exception as e:
        print(f"Error al inicializar la base de datos: {e}")

init_db()

# --- RUTAS DE LA APLICACIÓN ---

@app.route('/')
def index():
    """Consulta la lista de pacientes y la pasa a la plantilla."""
    patients = []
    try:
        with sqlite3.connect("linfoscopio.db") as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT id, nombre, apellido, cedula FROM patients ORDER BY apellido, nombre")
            patients = cur.fetchall()
    except Exception as e:
        print(f"Error al obtener la lista de pacientes: {e}")
    
    return render_template('index.html', patients=patients)

@app.route('/add_patient', methods=['POST'])
def add_patient():
    """Añade un nuevo paciente a la base de datos."""
    try:
        cedula = request.form['cedula']
        nombre = request.form['nombre']
        apellido = request.form['apellido']
        edad = request.form['edad']
        telefono = request.form['telefono']

        with sqlite3.connect("linfoscopio.db") as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO patients (cedula, nombre, apellido, edad, telefono) VALUES (?,?,?,?,?)",
                        (cedula, nombre, apellido, edad, telefono))
            conn.commit()
        return "Paciente guardado con éxito. <a href='/'>Volver</a>"
    except sqlite3.IntegrityError:
        return "Error: Ya existe un paciente con esa cédula. <a href='/'>Volver</a>"
    except Exception as e:
        return f"Error al guardar el paciente: {e}. <a href='/'>Volver</a>"

# --- RUTA DE CAPTURA MODIFICADA ---
@app.route('/capture')
def capture():
    """
    Captura una imagen y la asocia con el ID del paciente seleccionado,
    que se recibe como un parámetro en la URL.
    """
    # Obtenemos el ID del paciente desde la URL (ej: /capture?patient_id=1)
    patient_id = request.args.get('patient_id', default=None, type=int)

    if not patient_id:
        return jsonify(message="Error: Por favor, seleccione un paciente primero."), 400

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # Nombramos el archivo con el ID del paciente para fácil identificación
        filename = f"captures/capture_p{patient_id}_{timestamp}.jpg"
        
        if not os.path.exists('captures'):
            os.makedirs('captures')
        
        frame_bytes = camera.get_frame()
        
        with open(filename, 'wb') as f:
            f.write(frame_bytes)
        
        # Guardamos el registro en la base de datos, INCLUYENDO EL PATIENT_ID
        with sqlite3.connect("linfoscopio.db") as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO captures (patient_id, timestamp, image_path) VALUES (?,?,?)", 
                        (patient_id, timestamp, filename))
            conn.commit()
            message = f"¡Captura para paciente ID {patient_id} guardada!"
            
    except Exception as e:
        message = f"Error en la captura: {e}"

    return jsonify(message=message)
# -------------------------------------

def gen(camera_instance):
    while True:
        frame = camera_instance.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen(camera),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    print("Iniciando servidor Flask...")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False, threaded=True)
