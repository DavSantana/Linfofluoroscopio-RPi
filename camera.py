# camera.py (Versión final y robusta con Lock)
import cv2
from picamera2 import Picamera2
import time
import threading

class Camera(object):
    def __init__(self):
        print("Inicializando cámara con picamera2...")
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(main={"size": (640, 480)})
        self.picam2.configure(config)
        self.frame_lock = threading.Lock()
        self.picam2.start()
        time.sleep(2)
        print("Cámara inicializada con éxito.")

    def __del__(self):
        # Añadimos una comprobación para evitar errores si la cámara no se inicializó
        if hasattr(self, 'picam2') and self.picam2.is_open:
            self.picam2.stop()

    def get_frame(self):
        with self.frame_lock:
            # Capturamos el frame solo cuando tengamos el "paso"
            frame = self.picam2.capture_array()
        
        frame = cv2.flip(frame, -1) # Corregimos la orientación
        ret, jpeg = cv2.imencode('.jpg', frame)
        return jpeg.tobytes()
