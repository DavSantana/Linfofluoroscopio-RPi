# app.py (Versión Final con Arquitectura de Equipos y Seguridad)

import os
import sqlite3
from datetime import datetime
from flask import Flask, Response, render_template, jsonify, request, redirect, url_for, session
from functools import wraps
from camera import Camera

# --- IMPORTS DE FIREBASE ---
import firebase_admin
from firebase_admin import credentials, firestore, storage, auth
from google.cloud.firestore_v1.base_query import FieldFilter

# --- INICIALIZACIÓN CENTRAL ---
app = Flask(__name__)
app.secret_key = 'clave-secreta-para-el-linfofluoroscopio'
camera = Camera()

# --- INICIALIZACIÓN DE FIREBASE ---
try:
    # Asegúrate que el archivo 'firebase_credentials.json' está en la misma carpeta.
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'linfofluoroscopio-tesis.firebasestorage.app' # Reemplaza con tu bucket de Storage
    })
    db_firestore = firestore.client()
    bucket = storage.bucket()
    print("Firebase inicializado con éxito.")
except Exception as e:
    print(f"Error al inicializar Firebase: {e}")
    db_firestore = None
    bucket = None

# --- BASE DE DATOS LOCAL (SQLite) ---
def get_db_connection():
    conn = sqlite3.connect('linfoscopio.db')
    conn.row_factory = sqlite3.Row
    # Habilitar claves foráneas para asegurar la integridad de los datos al borrar en cascada
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    # Tabla de pacientes con el firestore_id como clave única para la sincronización
    conn.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cedula TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL, apellido TEXT NOT NULL, edad INTEGER, telefono TEXT,
            firestore_id TEXT UNIQUE
        )
    ''')
    # Tabla de capturas, vinculada a los pacientes a través del firestore_id
    conn.execute('''
        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT, patient_firestore_id TEXT, timestamp TEXT,
            storage_path TEXT, firestore_id TEXT UNIQUE, cloud_url TEXT,
            FOREIGN KEY (patient_firestore_id) REFERENCES patients (firestore_id) ON DELETE CASCADE
        )
    ''')
    conn.close()

# Inicializa la base de datos al arrancar la aplicación
init_db()

# --- FUNCIONES AUXILIARES DE FIREBASE ---
def sync_to_firestore(collection_name, data, document_id=None):
    if not db_firestore: return None
    try:
        if document_id:
            doc_ref = db_firestore.collection(collection_name).document(document_id)
        else:
            # Si no se provee un ID, Firestore genera uno automáticamente
            doc_ref = db_firestore.collection(collection_name).document()
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
        blob.make_public() # Hace el archivo públicamente accesible a través de una URL
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
    except Exception as e:
        print(f"Error al eliminar de Storage: {e}")

# --- DECORADOR DE AUTENTICACIÓN ---
# Esta función protege las rutas para que solo usuarios con sesión iniciada puedan acceder
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- RUTAS DE AUTENTICACIÓN Y REGISTRO ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        team_name = request.form.get('team_name')
        team_id = request.form.get('team_id')

        if not team_name and not team_id:
            return render_template('register.html', error="Debes crear un equipo o unirte a uno.")
        if team_name and team_id:
            return render_template('register.html', error="Solo puedes crear un equipo o unirte a uno, no ambos.")

        try:
            # Crear usuario en Firebase Authentication
            new_user = auth.create_user(email=email, password=password)
            
            # Lógica para crear o validar el equipo
            if team_name:
                team_ref = db_firestore.collection('teams').document()
                team_ref.set({'name': team_name, 'owner_uid': new_user.uid})
                final_team_id = team_ref.id
            else:
                team_ref = db_firestore.collection('teams').document(team_id).get()
                if not team_ref.exists:
                    # Si el equipo no existe, se borra el usuario recién creado para evitar usuarios huérfanos
                    auth.delete_user(new_user.uid)
                    return render_template('register.html', error="El ID del equipo no es válido.")
                final_team_id = team_id

            # Asignar rol y team_id como custom claims para seguridad
            auth.set_custom_user_claims(new_user.uid, {'role': role, 'team_id': final_team_id})

            # Crear un perfil de usuario en la colección 'users' de Firestore
            db_firestore.collection('users').document(new_user.uid).set({
                'email': email, 'role': role, 'team_id': final_team_id
            })
            
            return redirect(url_for('login'))
        except Exception as e:
            return render_template('register.html', error=str(e))
            
    return render_template('register.html')


@app.route('/login', methods=['GET'])
def login():
    return render_template('login.html')

@app.route('/session_login', methods=['POST'])
def session_login():
    try:
        id_token = request.json['token']
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token['uid']

        # Obtener siempre el perfil desde Firestore para evitar problemas de sincronización de claims
        user_profile_ref = db_firestore.collection('users').document(uid)
        user_profile = user_profile_ref.get()

        if not user_profile.exists:
            return jsonify({"status": "error", "message": "El perfil de usuario no existe en la base de datos."}), 401

        profile_data = user_profile.to_dict()
        user_email = profile_data.get('email')
        user_role = profile_data.get('role')
        user_team_id = profile_data.get('team_id')

        if not user_role or not user_team_id:
             return jsonify({"status": "error", "message": "El perfil del usuario está incompleto (falta rol o team_id)."}), 401

        # Crear la sesión de Flask con los datos correctos de Firestore
        session['user'] = {
            'uid': uid, 'email': user_email,
            'role': user_role, 'team_id': user_team_id
        }
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Error en session_login: {e}")
        return jsonify({"status": "error", "message": str(e)}), 401

@app.route('/logout')
@login_required
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

# --- RUTAS PROTEGIDAS DE LA APLICACIÓN ---
@app.route('/')
@login_required
def index():
    patients_list = []
    team_id = session['user']['team_id']
    if db_firestore:
        try:
            # Consulta a Firestore que filtra por team_id y ordena por apellido
            # Requiere un índice compuesto en Firestore
            query = db_firestore.collection('patients').where(filter=FieldFilter('team_id', '==', team_id)).order_by('apellido')
            docs = query.stream()
            for doc in docs:
                patient_data = doc.to_dict()
                patient_data['firestore_id'] = doc.id
                patients_list.append(patient_data)
        except Exception as e:
            print(f"Error al leer pacientes de Firestore: {e}")
    return render_template('index.html', patients=patients_list, user=session.get('user'))

@app.route('/patient/<string:firestore_patient_id>')
@login_required
def patient_detail(firestore_patient_id):
    patient_data = None
    captures_list = []
    team_id = session['user']['team_id']
    if db_firestore:
        try:
            # Obtener el documento del paciente
            doc_ref = db_firestore.collection('patients').document(firestore_patient_id)
            patient = doc_ref.get()
            
            # Comprobar que el paciente existe y pertenece al equipo del usuario
            if patient.exists and patient.to_dict().get('team_id') == team_id:
                patient_data = patient.to_dict()
                patient_data['firestore_id'] = patient.id
                
                # Obtener las capturas asociadas al paciente, ordenadas por fecha descendente
                captures_query = db_firestore.collection('captures').where(filter=FieldFilter('patient_firestore_id', '==', firestore_patient_id)).order_by('timestamp', direction=firestore.Query.DESCENDING)
                captures_stream = captures_query.stream()
                for capture in captures_stream:
                    capture_data = capture.to_dict()
                    capture_data['firestore_id'] = capture.id
                    captures_list.append(capture_data)
            else:
                 return "Acceso denegado o paciente no encontrado.", 404
        except Exception as e:
            print(f"Error al leer detalles de Firestore: {e}")
    if not patient_data:
        return "Paciente no encontrado", 404
    return render_template('patient_detail.html', patient=patient_data, captures=captures_list, user=session.get('user'))

@app.route('/add_patient', methods=['POST'])
@login_required
def add_patient():
    allowed_roles = ['secretaria', 'doctor']
    if session['user']['role'] not in allowed_roles:
        return "Acceso denegado.", 403
    try:
        team_id = session['user']['team_id']
        patient_data = {
            'cedula': request.form['cedula'], 'nombre': request.form['nombre'], 
            'apellido': request.form['apellido'], 'edad': int(request.form['edad']) if request.form['edad'] else None,
            'telefono': request.form['telefono'], 'createdAt': firestore.SERVER_TIMESTAMP,
            'team_id': team_id
        }
        # Sincronizar con Firestore
        firestore_patient_id = sync_to_firestore('patients', patient_data)
        if firestore_patient_id:
            # Lógica de respaldo en SQLite (opcional, se puede completar si es necesario)
            pass
        return redirect(url_for('index'))
    except Exception as e:
        return f"Error al guardar el paciente: {e}"

@app.route('/capture')
@login_required
def capture():
    if session['user']['role'] != 'doctor':
        return jsonify(message="Error: Solo los doctores pueden realizar capturas."), 403
        
    firestore_patient_id = request.args.get('firestore_patient_id')
    if not firestore_patient_id:
        return jsonify(message="Error: ID de paciente no proporcionado."), 400
        
    try:
        team_id = session['user']['team_id']
        timestamp_obj = datetime.now()
        timestamp_str = timestamp_obj.strftime("%Y-%m-%d_%H-%M-%S")
        
        # Crear una ruta única en Storage para la imagen
        destination_blob_name = f"pacientes/{firestore_patient_id}/capturas/{timestamp_str}.jpg"
        
        # Guardar la imagen temporalmente en el servidor
        temp_dir = 'temp_captures'
        os.makedirs(temp_dir, exist_ok=True)
        local_file_path = os.path.join(temp_dir, f"{timestamp_str}.jpg")
        
        frame_bytes = camera.get_frame()
        with open(local_file_path, 'wb') as f:
            f.write(frame_bytes)
            
        # Subir la imagen a Firebase Storage
        cloud_image_url = upload_to_storage(local_file_path, destination_blob_name)
        
        # Eliminar la imagen temporal
        os.remove(local_file_path)
        
        if cloud_image_url:
            # Guardar la información de la captura en Firestore
            capture_data = {
                'patient_firestore_id': firestore_patient_id,
                'cloud_url': cloud_image_url,
                'storage_path': destination_blob_name,
                'timestamp': timestamp_obj,
                'team_id': team_id
            }
            sync_to_firestore('captures', capture_data)
            
        return jsonify(message="¡Captura guardada y sincronizada!")
    except Exception as e:
        return jsonify(message=f"Error en la captura: {e}"), 500

@app.route('/delete_patient/<string:firestore_patient_id>', methods=['POST'])
@login_required
def delete_patient(firestore_patient_id):
    if session['user']['role'] != 'doctor':
        return "Acceso denegado.", 403

    team_id = session['user']['team_id']
    
    patient_ref = db_firestore.collection('patients').document(firestore_patient_id)
    patient_doc = patient_ref.get()
    if not patient_doc.exists or patient_doc.to_dict().get('team_id') != team_id:
        return "Paciente no encontrado o acceso no autorizado.", 404

    try:
        # Primero, encontrar y eliminar todas las capturas asociadas en Storage y Firestore
        captures_query = db_firestore.collection('captures').where(filter=FieldFilter('patient_firestore_id', '==', firestore_patient_id)).stream()
        for capture in captures_query:
            capture_data = capture.to_dict()
            if 'storage_path' in capture_data:
                delete_from_storage(capture_data['storage_path'])
            capture.reference.delete()

        # Luego, eliminar el documento del paciente en Firestore
        delete_from_firestore('patients', firestore_patient_id)

        # Finalmente, eliminar el paciente de la base de datos local SQLite
        conn = get_db_connection()
        conn.execute('DELETE FROM patients WHERE firestore_id = ?', (firestore_patient_id,))
        conn.commit()
        conn.close()

        return redirect(url_for('index'))
    except Exception as e:
        print(f"Error al eliminar paciente: {e}")
        return "Ocurrió un error durante la eliminación.", 500


@app.route('/delete_capture/<string:firestore_capture_id>', methods=['POST'])
@login_required
def delete_capture(firestore_capture_id):
    if session['user']['role'] != 'doctor':
        return "Acceso denegado.", 403

    team_id = session['user']['team_id']
    
    try:
        capture_ref = db_firestore.collection('captures').document(firestore_capture_id)
        capture_doc = capture_ref.get()

        if not capture_doc.exists or capture_doc.to_dict().get('team_id') != team_id:
            return "Captura no encontrada o acceso no autorizado.", 404
        
        capture_data = capture_doc.to_dict()
        patient_id_to_redirect = capture_data.get('patient_firestore_id')

        # Eliminar el archivo de Firebase Storage
        if 'storage_path' in capture_data:
            delete_from_storage(capture_data['storage_path'])

        # Eliminar el documento de Firestore
        delete_from_firestore('captures', firestore_capture_id)

        # Eliminar de la base de datos local SQLite
        conn = get_db_connection()
        conn.execute('DELETE FROM captures WHERE firestore_id = ?', (firestore_capture_id,))
        conn.commit()
        conn.close()

        return redirect(url_for('patient_detail', firestore_patient_id=patient_id_to_redirect))

    except Exception as e:
        print(f"Error al eliminar la captura: {e}")
        return "Ocurrió un error durante la eliminación.", 500

@app.route('/video_feed')
@login_required
def video_feed():
    def gen(camera_instance):
        while True:
            frame = camera_instance.get_frame()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    return Response(gen(camera), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    print("Iniciando servidor Flask...")
    # threaded=True es importante para manejar múltiples solicitudes (video y otras acciones) a la vez
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False, threaded=True)

