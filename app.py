# app.py (Versión con corrección de jsonify)

import os
import sqlite3
from datetime import datetime
# --- CORRECCIÓN: Se añade jsonify a la lista de imports ---
from flask import Flask, Response, render_template, jsonify, request, redirect, url_for
from camera import Camera

# --- IMPORTS DE FIREBASE ---
import firebase_admin
from firebase_admin import credentials, firestore, storage

# --- INICIALIZACIÓN CENTRAL ---
app = Flask(__name__)
camera = Camera()

# --- INICIALIZACIÓN DE FIREBASE ---
try:
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'linfofluoroscopio-tesis.firebasestorage.app' # Reemplaza con tu bucket
    })
    db_firestore = firestore.client()
    bucket = storage.bucket()
    print("Firebase inicializado con éxito.")
except Exception as e:
    print(f"Error al inicializar Firebase: {e}")
    db_firestore = None
    bucket = None

# --- BASE DE DATOS LOCAL ---
def get_db_connection():
    conn = sqlite3.connect('linfoscopio.db')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cedula TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL, apellido TEXT NOT NULL, edad INTEGER, telefono TEXT,
            firestore_id TEXT UNIQUE
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT, patient_firestore_id TEXT, timestamp TEXT,
            storage_path TEXT, firestore_id TEXT UNIQUE, cloud_url TEXT,
            FOREIGN KEY (patient_firestore_id) REFERENCES patients (firestore_id) ON DELETE CASCADE
        )
    ''')
    conn.close()

init_db()

# --- FUNCIONES DE FIREBASE ---
def sync_to_firestore(collection_name, data, document_id=None):
    if not db_firestore: return None
    try:
        doc_ref = db_firestore.collection(collection_name).document(document_id)
        doc_ref.set(data, merge=True)
        print(f"Dato sincronizado en Firestore: {collection_name}/{doc_ref.id}")
        return doc_ref.id
    except Exception as e:
        print(f"Error al sincronizar con Firestore: {e}")
        return None

def upload_to_storage(source_file_path, destination_blob_name):
    if not bucket: return None
    try:
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_path)
        blob.make_public()
        print(f"Archivo {source_file_path} subido a Storage como {destination_blob_name}.")
        return blob.public_url
    except Exception as e:
        print(f"Error al subir a Storage: {e}")
        return None

def delete_from_firestore(collection_name, document_id):
    if not db_firestore: return
    try:
        db_firestore.collection(collection_name).document(str(document_id)).delete()
        print(f"Documento {collection_name}/{document_id} eliminado de Firestore.")
    except Exception as e:
        print(f"Error al eliminar de Firestore: {e}")

def delete_from_storage(blob_name):
    if not bucket: return
    try:
        blob = bucket.blob(blob_name)
        if blob.exists():
            blob.delete()
            print(f"Archivo {blob_name} eliminado de Storage.")
        else:
            print(f"Archivo {blob_name} no encontrado en Storage para eliminar.")
    except Exception as e:
        print(f"Error al eliminar de Storage: {e}")

# --- RUTAS DE LA APLICACIÓN ---
@app.route('/')
def index():
    patients_list = []
    if db_firestore:
        try:
            docs = db_firestore.collection('patients').order_by('apellido').stream()
            for doc in docs:
                patient_data = doc.to_dict()
                patient_data['firestore_id'] = doc.id
                patients_list.append(patient_data)
        except Exception as e:
            print(f"Error al leer pacientes de Firestore: {e}")
    return render_template('index.html', patients=patients_list)


@app.route('/patient/<string:firestore_patient_id>')
def patient_detail(firestore_patient_id):
    patient_data = None
    captures_list = []
    if db_firestore:
        try:
            doc_ref = db_firestore.collection('patients').document(firestore_patient_id)
            patient = doc_ref.get()
            if patient.exists:
                patient_data = patient.to_dict()
                patient_data['firestore_id'] = patient.id

                captures_query = db_firestore.collection('captures').where('patient_firestore_id', '==', firestore_patient_id).order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
                for capture in captures_query:
                    capture_data = capture.to_dict()
                    capture_data['firestore_id'] = capture.id
                    captures_list.append(capture_data)
        except Exception as e:
            print(f"Error al leer detalles de Firestore: {e}")

    if not patient_data:
        return "Paciente no encontrado", 404
        
    return render_template('patient_detail.html', patient=patient_data, captures=captures_list)


@app.route('/add_patient', methods=['POST'])
def add_patient():
    try:
        cedula = request.form['cedula']
        patient_data_for_cloud = {
            'cedula': cedula, 'nombre': request.form['nombre'], 'apellido': request.form['apellido'],
            'edad': int(request.form['edad']) if request.form['edad'] else None,
            'telefono': request.form['telefono'], 'createdAt': firestore.SERVER_TIMESTAMP
        }
        firestore_patient_id = sync_to_firestore('patients', patient_data_for_cloud)
        
        if firestore_patient_id:
            conn = get_db_connection()
            conn.execute(
                "INSERT INTO patients (cedula, nombre, apellido, edad, telefono, firestore_id) VALUES (?,?,?,?,?,?)",
                (cedula, request.form['nombre'], request.form['apellido'], request.form['edad'], request.form['telefono'], firestore_patient_id)
            )
            conn.commit()
            conn.close()

        return redirect(url_for('index'))
    except Exception as e:
        return f"Error al guardar el paciente: {e}"

@app.route('/capture')
def capture():
    firestore_patient_id = request.args.get('firestore_patient_id')
    if not firestore_patient_id:
        # Aquí es donde ocurría el error porque 'jsonify' no estaba importado
        return jsonify(message="Error: ID de paciente no proporcionado."), 400
    
    try:
        timestamp_obj = datetime.now()
        timestamp_str = timestamp_obj.strftime("%Y-%m-%d_%H-%M-%S")
        destination_blob_name = f"pacientes/{firestore_patient_id}/capturas/{timestamp_str}.jpg"
        
        temp_dir = 'temp_captures'
        os.makedirs(temp_dir, exist_ok=True)
        local_file_path = os.path.join(temp_dir, f"{timestamp_str}.jpg")

        frame_bytes = camera.get_frame()
        with open(local_file_path, 'wb') as f: f.write(frame_bytes)
            
        cloud_image_url = upload_to_storage(local_file_path, destination_blob_name)
        os.remove(local_file_path)

        if cloud_image_url:
            capture_data = {
                'patient_firestore_id': firestore_patient_id, 'cloud_url': cloud_image_url,
                'storage_path': destination_blob_name, 'timestamp': timestamp_obj
            }
            firestore_capture_id = sync_to_firestore('captures', capture_data)

            conn = get_db_connection()
            conn.execute(
                "INSERT INTO captures (patient_firestore_id, timestamp, storage_path, firestore_id, cloud_url) VALUES (?,?,?,?,?)",
                (firestore_patient_id, timestamp_str, destination_blob_name, firestore_capture_id, cloud_image_url)
            )
            conn.commit()
            conn.close()
        return jsonify(message="¡Captura guardada y sincronizada!")
    except Exception as e:
        return jsonify(message=f"Error en la captura: {e}"), 500

@app.route('/delete_patient/<string:firestore_patient_id>', methods=['POST'])
def delete_patient(firestore_patient_id):
    captures_query = db_firestore.collection('captures').where('patient_firestore_id', '==', firestore_patient_id).stream()
    for capture in captures_query:
        capture_data = capture.to_dict()
        delete_from_storage(capture_data['storage_path'])
        capture.reference.delete()
    
    delete_from_firestore('patients', firestore_patient_id)
    
    conn = get_db_connection()
    conn.execute('DELETE FROM patients WHERE firestore_id = ?', (firestore_patient_id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))

@app.route('/delete_capture/<string:firestore_capture_id>', methods=['POST'])
def delete_capture(firestore_capture_id):
    doc_ref = db_firestore.collection('captures').document(firestore_capture_id)
    doc = doc_ref.get()
    if doc.exists:
        capture_data = doc.to_dict()
        patient_id = capture_data.get('patient_firestore_id')
        
        delete_from_storage(capture_data['storage_path'])
        delete_from_firestore('captures', firestore_capture_id)
        
        conn = get_db_connection()
        conn.execute('DELETE FROM captures WHERE firestore_id = ?', (firestore_capture_id,))
        conn.commit()
        conn.close()
        
        return redirect(url_for('patient_detail', firestore_patient_id=patient_id))
    return redirect(url_for('index'))

@app.route('/video_feed')
def video_feed():
    def gen(camera_instance):
        while True:
            frame = camera_instance.get_frame()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    return Response(gen(camera), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    print("Iniciando servidor Flask...")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False, threaded=True)