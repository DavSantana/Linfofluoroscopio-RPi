import firebase_admin
from firebase_admin import credentials, auth

# Inicializa la app de Firebase (asegúrate de que firebase_credentials.json está presente)
cred = credentials.Certificate("firebase_credentials.json")
firebase_admin.initialize_app(cred)

def set_role(email, role):
    """Asigna un rol a un usuario de Firebase por su email."""
    try:
        user = auth.get_user_by_email(email)
        # El segundo argumento de set_custom_user_claims es un diccionario
        auth.set_custom_user_claims(user.uid, {'role': role})
        print(f"Éxito: El rol '{role}' fue asignado a {email}.")
    except Exception as e:
        print(f"Error: {e}")

# --- ¡EJECUTA ESTA SECCIÓN UNA SOLA VEZ! ---
if __name__ == '__main__':
    # Asigna el rol 'secretaria' al usuario correspondiente
    set_role('secretaria@linfoscopio.com', 'secretaria')

    # Asigna el rol 'doctor' al usuario correspondiente
    set_role('doctor@linfoscopio.com', 'doctor')