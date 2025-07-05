# camera.py (Versión final con picamera2)
import cv2
from picamera2 import Picamera2
import time

class Camera(object):
    def __init__(self):
        print("Inicializando cámara con picamera2...")
        # Inicializa la cámara usando la librería nativa
        self.picam2 = Picamera2()
        
        # Configura la resolución para la previsualización/captura
        config = self.picam2.create_preview_configuration(main={"size": (640, 480)})
        self.picam2.configure(config)
        
        # Inicia la cámara
        self.picam2.start()
        
        # Dale tiempo a la cámara para que se ajuste a la luz
        time.sleep(2)
        print("Cámara inicializada con éxito.")

    def __del__(self):
        # Detiene la cámara al eliminar el objeto
        self.picam2.stop()

    def get_frame(self):
        # Captura un frame como un array de NumPy (formato que OpenCV entiende)
        frame = self.picam2.capture_array()
        
        # Codifica el frame a formato JPEG
        ret, jpeg = cv2.imencode('.jpg', frame)
        
        # Retorna los bytes de la imagen
        return jpeg.tobytes()