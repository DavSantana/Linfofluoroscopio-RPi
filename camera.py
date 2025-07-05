import cv2

class Camera:
    def __init__(self):
        self.cap = cv2.VideoCapture(0)

    def get_frame(self):
        success, frame = self.cap.read()
        if not success:
            return None
        _, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes()

    def __del__(self):
        self.cap.release()
