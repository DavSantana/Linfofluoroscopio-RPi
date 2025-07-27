# camera_pi.py (Versión optimizada para Raspberry Pi con libcamera)

import io
import time
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput

class Camera:
    def __init__(self):
        self.picam2 = Picamera2()
        # Configuración para el streaming de video (baja resolución para fluidez)
        self.video_config = self.picam2.create_video_configuration(main={"size": (640, 480)})
        # Configuración para capturas de alta resolución
        self.still_config = self.picam2.create_still_configuration()
        
        # Iniciar con la configuración de video
        self.picam2.configure(self.video_config)
        self.picam2.start()
        
        # Dar tiempo a la cámara para que se estabilice
        time.sleep(2)
        print("Cámara optimizada iniciada.")

    def get_frame(self):
        """Captura un frame del stream de video para la transmisión en vivo."""
        # Usamos un buffer en memoria para no escribir en disco
        stream = io.BytesIO()
        # Capturamos el frame del stream de video activo
        self.picam2.capture_file(stream, format='jpeg')
        stream.seek(0)
        return stream.read()

    def capture_high_res(self):
        """Cambia a modo de alta resolución, captura una imagen y vuelve al modo de video."""
        print("Cambiando a modo de alta resolución para captura...")
        # Cambiar a la configuración de alta resolución
        self.picam2.switch_mode(self.still_config)
        
        # Capturar la imagen en un buffer de memoria
        stream = io.BytesIO()
        self.picam2.capture_file(stream, format='jpeg')
        stream.seek(0)
        print("Captura de alta resolución tomada.")
        
        # Volver a la configuración de video para continuar el streaming
        self.picam2.switch_mode(self.video_config)
        
        return stream.read()

