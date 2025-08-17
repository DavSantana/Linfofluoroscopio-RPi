# app.py (Versión Final con Generación de PDF y Ruta de Anotaciones)
import os
import sqlite3
import io
import requests
from datetime import datetime
import json
from flask import Flask, Response, render_template, jsonify, request, redirect, url_for, session, send_file
from functools import wraps
from camera_pi import Camera
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import base64

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
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'linfofluoroscopio-tesis.firebasestorage.app'
    })
    db_firestore = firestore.client()
    bucket = storage.bucket()
    print("Firebase inicializado con éxito.")
except Exception as e:
    print(f"Error al inicializar Firebase: {e}")
    db_firestore = None
    bucket = None

# --- CLASE PERSONALIZADA PARA EL PDF (CORREGIDA) ---
class PDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 16)
        self.cell(0, 10, 'LINFOFLUOROSCOPIA', align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', align='C')

    def chapter_title(self, title):
        self.set_font('Helvetica', 'B', 12)
        self.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(4)

    def chapter_body(self, name, data):
        y_before = self.get_y()
        # Dibuja la celda del título (izquierda)
        self.set_font('Helvetica', 'B', 11)
        self.multi_cell(40, 10, name, border=1, new_x="RIGHT", new_y="TOP")

        # Regresa a la posición Y inicial y mueve el cursor X
        self.set_y(y_before)
        self.set_x(self.l_margin + 40)

        # Dibuja la celda de datos (derecha)
        self.set_font('Helvetica', '', 11)
        available_width = self.w - self.l_margin - self.r_margin - 40
        self.multi_cell(available_width, 10, data, border=1, new_x="LMARGIN", new_y="NEXT")

# --- BASE DE DATOS Y FUNCIONES AUXILIARES ---
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

def sync_to_firestore(collection_name, data, document_id=None):
    if not db_firestore: return None
    try:
        if document_id:
            doc_ref = db_firestore.collection(collection_name).document(document_id)
        else:
            doc_ref = db_firestore.collection(collection_name).document()
        doc_ref.set(data, merge=True)
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
    except Exception as e:
        print(f"Error al eliminar de Firestore: {e}")

def delete_from_storage(blob_name):
    if not bucket: return
    try:
        blob = bucket.blob(blob_name)
        if blob.exists():
            blob.delete()
    except Exception as e:
        print(f"Error al eliminar de Storage: {e}")

# --- DECORADOR DE AUTENTICACIÓN ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- RUTAS DE AUTENTICACIÓN ---
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
            new_user = auth.create_user(email=email, password=password)
            if team_name:
                team_ref = db_firestore.collection('teams').document()
                team_ref.set({'name': team_name, 'owner_uid': new_user.uid})
                final_team_id = team_ref.id
            else:
                team_ref = db_firestore.collection('teams').document(team_id).get()
                if not team_ref.exists:
                    auth.delete_user(new_user.uid)
                    return render_template('register.html', error="El ID del equipo no es válido.")
                final_team_id = team_id
            auth.set_custom_user_claims(new_user.uid, {'role': role, 'team_id': final_team_id})
            db_firestore.collection('users').document(new_user.uid).set({
                'email': email, 'role': role, 'team_id': final_team_id
            })
            return redirect(url_for('login'))
        except Exception as e:
            return render_template('register.html', error=str(e))
    return render_template('register.html')

@app.route('/login', methods=['GET'])
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/session_login', methods=['POST'])
def session_login():
    try:
        id_token = request.json['token']
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token['uid']
        user_profile_ref = db_firestore.collection('users').document(uid)
        user_profile = user_profile_ref.get()
        if not user_profile.exists:
            return jsonify({"status": "error", "message": "El perfil de usuario no existe."}), 401
        profile_data = user_profile.to_dict()
        session['user'] = {
            'uid': uid,
            'email': profile_data.get('email'),
            'role': profile_data.get('role'),
            'team_id': profile_data.get('team_id')
        }
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 401

@app.route('/logout')
@login_required
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

# --- RUTAS PRINCIPALES ---
@app.route('/')
@login_required
def dashboard():
    user_role = session['user'].get('role')
    if user_role == 'doctor':
        return render_template('dashboard_doctor.html', user=session['user'])
    elif user_role == 'secretaria':
        return render_template('dashboard_secretaria.html', user=session['user'])
    else:
        return redirect(url_for('login'))

@app.route('/register_patient', methods=['GET', 'POST'])
@login_required
def register_patient():
    allowed_roles = ['secretaria', 'doctor']
    if session['user']['role'] not in allowed_roles:
        return "Acceso denegado.", 403

    if request.method == 'POST':
        try:
            team_id = session['user']['team_id']
            patient_data = {
                'cedula': request.form['cedula'], 
                'nombre': request.form['nombre'], 
                'apellido': request.form['apellido'], 
                'email': request.form.get('email'),
                'edad': int(request.form['edad']) if request.form['edad'] else None,
                'telefono': request.form['telefono'], 
                'createdAt': firestore.SERVER_TIMESTAMP,
                'team_id': team_id
            }
            history_data = {
                'fecha_sintomas': request.form.get('fecha_sintomas'),
                'fecha_diagnostico': request.form.get('fecha_diagnostico'),
                'diagnostico_medico': request.form.get('diagnostico_medico'),
                'tratamiento_farmacologico': request.form.get('tratamiento_farmacologico'),
                'tratamiento_conservador': request.form.get('tratamiento_conservador'),
                'tratamiento_quirurgico': request.form.get('tratamiento_quirurgico'),
            }
            patient_data['history'] = history_data
            sync_to_firestore('patients', patient_data)
            return redirect(url_for('dashboard'))
        except Exception as e:
            print(f"Error al registrar el paciente: {e}")
            return "Error al guardar el paciente.", 500
    return render_template('register_patient.html', user=session['user'])

@app.route('/patient_list')
@login_required
def patient_list():
    patients_list = []
    team_id = session['user']['team_id']
    if db_firestore:
        try:
            query = db_firestore.collection('patients').where(filter=FieldFilter('team_id', '==', team_id)).order_by('apellido')
            docs = query.stream()
            for doc in docs:
                patient_data = doc.to_dict()
                patient_data['firestore_id'] = doc.id
                patients_list.append(patient_data)
        except Exception as e:
            print(f"Error al leer pacientes de Firestore: {e}")
    return render_template('patient_list.html', patients=patients_list, user=session.get('user'))

@app.route('/start_study/<string:firestore_patient_id>', methods=['GET', 'POST'])
@login_required
def start_study(firestore_patient_id):
    if session['user']['role'] != 'doctor':
        return "Acceso denegado.", 403
    
    patient_ref = db_firestore.collection('patients').document(firestore_patient_id)
    patient = patient_ref.get()
    if not patient.exists or patient.to_dict().get('team_id') != session['user']['team_id']:
        return "Paciente no encontrado o acceso no autorizado.", 404
    
    patient_data = patient.to_dict()
    patient_data['firestore_id'] = patient.id

    if request.method == 'POST':
        study_area = request.form.get('study_area')
        return render_template('study.html', patient=patient_data, study_area=study_area, user=session.get('user'))

    return render_template('select_study_area.html', patient=patient_data, user=session.get('user'))

# --- RUTAS DE GESTIÓN DE PACIENTES ---
@app.route('/patient/<string:firestore_patient_id>')
@login_required
def patient_detail(firestore_patient_id):
    patient_data = None
    captures_list = []
    team_id = session['user']['team_id']
    if db_firestore:
        try:
            doc_ref = db_firestore.collection('patients').document(firestore_patient_id)
            patient = doc_ref.get()
            if patient.exists and patient.to_dict().get('team_id') == team_id:
                patient_data = patient.to_dict()
                patient_data['firestore_id'] = patient.id
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

@app.route('/update_history/<string:firestore_patient_id>', methods=['POST'])
@login_required
def update_history(firestore_patient_id):
    allowed_roles = ['secretaria', 'doctor']
    if session['user']['role'] not in allowed_roles:
        return "Acceso denegado.", 403
    try:
        patient_updates = {
            'nombre': request.form.get('nombre'),
            'apellido': request.form.get('apellido'),
            'cedula': request.form.get('cedula'),
            'email': request.form.get('email'),
            'edad': int(request.form['edad']) if request.form['edad'] else None,
            'telefono': request.form.get('telefono'),
        }
        
        history_updates = {
            'fecha_sintomas': request.form.get('fecha_sintomas'),
            'fecha_diagnostico': request.form.get('fecha_diagnostico'),
            'diagnostico_medico': request.form.get('diagnostico_medico'),
            'tratamiento_farmacologico': request.form.get('tratamiento_farmacologico'),
            'tratamiento_conservador': request.form.get('tratamiento_conservador'),
            'tratamiento_quirurgico': request.form.get('tratamiento_quirurgico'),
        }
        
        patient_updates['history'] = history_updates
        
        patient_ref = db_firestore.collection('patients').document(firestore_patient_id)
        patient_ref.update(patient_updates)
        
        return redirect(url_for('patient_detail', firestore_patient_id=firestore_patient_id))
    except Exception as e:
        print(f"Error al actualizar datos del paciente: {e}")
        return "Ocurrió un error al guardar los datos.", 500

@app.route('/save_analysis/<string:firestore_patient_id>', methods=['POST'])
@login_required
def save_analysis(firestore_patient_id):
    if session['user']['role'] != 'doctor':
        return "Acceso denegado.", 403
    
    try:
        analysis_data = {
            'patient_id': firestore_patient_id,
            'team_id': session['user']['team_id'],
            'doctor_id': session['user']['uid'],
            'analysis_date': firestore.SERVER_TIMESTAMP,
            'selected_captures': request.form.getlist('selected_captures'),
            'extremidad': request.form.getlist('extremidad'),
            'hallazgos': request.form.getlist('hallazgos'),
            'conclusiones': request.form.get('conclusiones')
        }

        report_id = sync_to_firestore('reports', analysis_data)
        
        print(f"Análisis guardado con éxito para el paciente {firestore_patient_id} en el reporte {report_id}")
        
        return redirect(url_for('generate_report', report_id=report_id))

    except Exception as e:
        print(f"Error al guardar el análisis: {e}")
        return "Ocurrió un error al guardar el análisis.", 500

# Reemplaza esta función completa en tu app.py
@app.route('/generate_report/<string:report_id>')
@login_required
def generate_report(report_id):
    try:
        report_ref = db_firestore.collection('reports').document(report_id)
        report_data = report_ref.get().to_dict()

        if not report_data or report_data.get('team_id') != session['user']['team_id']:
            return "Reporte no encontrado o acceso no autorizado.", 404

        patient_id = report_data.get('patient_id')
        patient_ref = db_firestore.collection('patients').document(patient_id)
        patient_data = patient_ref.get().to_dict()
        
        pdf = PDF()
        pdf.add_page()
        
        pdf.chapter_title('Datos del Paciente')
        pdf.chapter_body('Nombre:', f"{patient_data.get('nombre', '')} {patient_data.get('apellido', '')}")
        pdf.chapter_body('Cédula:', patient_data.get('cedula', 'N/A'))
        # CORRECCIÓN: Se usa la fecha de la anotación si existe
        fecha_informe = report_data.get('analysis_date')
        if fecha_informe:
            pdf.chapter_body('Fecha del Informe:', fecha_informe.strftime('%d-%m-%Y'))
        
        pdf.ln(10)
        
        # --- CORRECCIÓN PRINCIPAL AQUÍ ---
        # Preparamos los datos y nos aseguramos de que no estén vacíos
        extremidad_str = ', '.join(report_data.get('extremidad', []))
        hallazgos_str = ', '.join(report_data.get('hallazgos', []))
        # Usamos 'Observaciones' como en tu imagen, en lugar de 'Conclusiones'
        observaciones_str = report_data.get('conclusiones', '')

        pdf.chapter_title('Resultados del Estudio')
        # Si el string está vacío, pasamos un espacio para mantener la altura de la celda
        pdf.chapter_body('Extremidad:', extremidad_str if extremidad_str else ' ')
        pdf.chapter_body('Hallazgos:', hallazgos_str if hallazgos_str else ' ')
        pdf.chapter_body('Observaciones:', observaciones_str if observaciones_str else ' ')
        
        selected_captures_ids = report_data.get('selected_captures', [])
        if selected_captures_ids:
            pdf.add_page()
            pdf.chapter_title('Imágenes Anexas')
            
            for capture_id in selected_captures_ids:
                capture_ref = db_firestore.collection('captures').document(capture_id)
                capture_data = capture_ref.get().to_dict()
                if capture_data:
                    # Usamos la imagen anotada si existe, si no, la original
                    image_url_to_use = capture_data.get('annotated_url', capture_data.get('cloud_url'))
                    if image_url_to_use:
                        response = requests.get(image_url_to_use)
                        if response.status_code == 200:
                            img_stream = io.BytesIO(response.content)
                            pdf.image(img_stream, w=pdf.w - 20)
                            pdf.set_font('Helvetica', 'I', 9)
                            timestamp = capture_data.get('timestamp')
                            if timestamp:
                                pdf.cell(0, 10, f"Captura de {capture_data.get('study_area', '')} - {timestamp.strftime('%d-%m-%Y %H:%M')}", align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                            pdf.ln(5)

        pdf_output = pdf.output()
        return send_file(
            io.BytesIO(pdf_output),
            as_attachment=True,
            download_name=f'informe_{patient_data.get("apellido", "")}_{report_id}.pdf',
            mimetype='application/pdf'
        )

    except Exception as e:
        print(f"Error al generar el PDF: {e}")
        return "Ocurrió un error al generar el informe.", 500

@app.route('/capture')
@login_required
def capture():
    if session['user']['role'] != 'doctor':
        return jsonify(message="Error: Solo los doctores pueden realizar capturas."), 403
        
    firestore_patient_id = request.args.get('firestore_patient_id')
    study_area = request.args.get('study_area', 'General')

    if not firestore_patient_id:
        return jsonify(message="Error: ID de paciente no proporcionado."), 400
        
    try:
        team_id = session['user']['team_id']
        timestamp_obj = datetime.now()
        timestamp_str = timestamp_obj.strftime("%Y-%m-%d_%H-%M-%S")
        destination_blob_name = f"pacientes/{firestore_patient_id}/{study_area.replace(' ', '_')}/{timestamp_str}.jpg"
        
        temp_dir = 'temp_captures'
        os.makedirs(temp_dir, exist_ok=True)
        local_file_path = os.path.join(temp_dir, f"{timestamp_str}.jpg")
        
        frame_bytes = camera.capture_high_res()
        
        with open(local_file_path, 'wb') as f:
            f.write(frame_bytes)
        cloud_image_url = upload_to_storage(local_file_path, destination_blob_name)
        os.remove(local_file_path)
        
        if cloud_image_url:
            capture_data = {
                'patient_firestore_id': firestore_patient_id,
                'cloud_url': cloud_image_url,
                'storage_path': destination_blob_name,
                'timestamp': timestamp_obj,
                'team_id': team_id,
                'study_area': study_area
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
        captures_query = db_firestore.collection('captures').where(filter=FieldFilter('patient_firestore_id', '==', firestore_patient_id)).stream()
        for capture in captures_query:
            capture_data = capture.to_dict()
            if 'storage_path' in capture_data:
                delete_from_storage(capture_data['storage_path'])
            # Also delete annotated image if it exists
            if 'annotated_url' in capture_data:
                # Extract blob name from URL for deletion
                blob_name_annotated = '/'.join(capture_data['annotated_url'].split('?')[0].split('/')[-5:])
                delete_from_storage(blob_name_annotated)
            capture.reference.delete()
        delete_from_firestore('patients', firestore_patient_id)
        conn = get_db_connection()
        conn.execute('DELETE FROM patients WHERE firestore_id = ?', (firestore_patient_id,))
        conn.commit()
        conn.close()
        return redirect(url_for('dashboard'))
    except Exception as e:
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
        if 'storage_path' in capture_data:
            delete_from_storage(capture_data['storage_path'])
        # Also delete annotated image if it exists
        if 'annotated_url' in capture_data:
            blob_name_annotated = '/'.join(capture_data['annotated_url'].split('?')[0].split('/')[-5:])
            delete_from_storage(blob_name_annotated)
            
        delete_from_firestore('captures', firestore_capture_id)
        conn = get_db_connection()
        conn.execute('DELETE FROM captures WHERE firestore_id = ?', (firestore_capture_id,))
        conn.commit()
        conn.close()
        return redirect(url_for('patient_detail', firestore_patient_id=patient_id_to_redirect))
    except Exception as e:
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

# --- RUTA NUEVA PARA GUARDAR ANOTACIONES ---
# Reemplaza esta función completa en tu app.py
@app.route('/save_annotation/<string:capture_id>', methods=['POST'])
@login_required
def save_annotation(capture_id):
    if session['user']['role'] != 'doctor':
        return jsonify(status="error", message="Acceso denegado."), 403

    try:
        data = request.json
        image_data_url = data.get('imageData')
        annotation_data = data.get('annotationData')

        if not image_data_url:
            return jsonify(status="error", message="No se proporcionaron datos de imagen."), 400

        team_id = session['user']['team_id']
        capture_ref = db_firestore.collection('captures').document(capture_id)
        capture_doc = capture_ref.get()

        if not capture_doc.exists or capture_doc.to_dict().get('team_id') != team_id:
            return jsonify(status="error", message="Captura no encontrada o sin autorización."), 404

        patient_id = capture_doc.to_dict().get('patient_firestore_id')

        header, encoded = image_data_url.split(",", 1)
        decoded_image = base64.b64decode(encoded)

        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        destination_blob_name = f"pacientes/{patient_id}/anotaciones/annotated_{capture_id}_{timestamp_str}.png"

        blob = bucket.blob(destination_blob_name)
        blob.upload_from_string(decoded_image, content_type='image/png')
        blob.make_public()
        new_annotated_url = blob.public_url

        update_data = {
            'annotated_url': new_annotated_url,
            'last_annotated_at': firestore.SERVER_TIMESTAMP
        }
        if annotation_data:
            # CORRECCIÓN: Convertimos el objeto a un string de texto JSON antes de guardarlo
            update_data['annotation_data'] = json.dumps(annotation_data)

        capture_ref.update(update_data)

        return jsonify(status="success", message="Anotación guardada con éxito.")

    except Exception as e:
        print(f"Error al guardar la anotación: {e}")
        return jsonify(status="error", message=f"Ocurrió un error en el servidor: {e}"), 500

if __name__ == '__main__':
    print("Iniciando servidor Flask...")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False, threaded=True)
    