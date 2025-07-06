# camera.py (Versión final y robusta con Lock)
import cv2
from picamera2 import Picamera2
import time
import threading # <--- CAMBIO 1: Importamos la librería de sincronización

class Camera(object):
    def __init__(self):
        print("Inicializando cámara con picamera2...")
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(main={"size": (640, 480)})
        self.picam2.configure(config)
        
        # --- CAMBIO 2: Creamos el "semáforo" (Lock) ---
        self.frame_lock = threading.Lock()
        # ---------------------------------------------
        
        self.picam2.start()
        time.sleep(2)
        print("Cámara inicializada con éxito.")

    def __del__(self):
        self.picam2.stop()

    def get_frame(self):
        # --- CAMBIO 3: Usamos el "semáforo" para proteger el acceso ---
        with self.frame_lock:
            # Capturamos el frame solo cuando tengamos el "paso"
            frame = self.picam2.capture_array()
        # -------------------------------------------------------------
        
        # El resto del procesamiento puede ocurrir fuera del lock
        frame = cv2.flip(frame, -1) # Corregimos la orientación
        ret, jpeg = cv2.imencode('.jpg', frame)
        return jpeg.tobytes()