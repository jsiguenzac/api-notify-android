from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import credentials, initialize_app, messaging, firestore
import schedule
import time
from threading import Thread
from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

# Middleware para CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar Firebase
""" try:
    cred = credentials.Certificate('credentials.json')  # Ruta al archivo de credenciales
    initialize_app(cred)
    db = firestore.client()
    print("Firebase inicializado correctamente.")
except Exception as e:
    print(f"Error al inicializar Firebase: {e}")
    db = None """
    
import os
from dotenv import load_dotenv
load_dotenv()

try:
    # Usa las variables de entorno para crear las credenciales
    cred_dict = {
        "type": "service_account",
        "project_id": os.getenv('FIREBASE_PROJECT_ID'),
        "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID'),
        "private_key": os.getenv('FIREBASE_PRIVATE_KEY').replace("\\n", "\n"),
        "client_email": os.getenv('FIREBASE_CLIENT_EMAIL'),
        "client_id": os.getenv('FIREBASE_CLIENT_ID'),
        "auth_uri": os.getenv('FIREBASE_AUTH_URI'),
        "token_uri": os.getenv('FIREBASE_TOKEN_URI'),
        "auth_provider_x509_cert_url": os.getenv('FIREBASE_AUTH_PROVIDER_X509_CERT_URL'),
        "client_x509_cert_url": os.getenv('FIREBASE_CLIENT_X509_CERT_URL'),
        "universe_domain": os.getenv('FIREBASE_UNIVERSE_DOMAIN')
    }
    cred = credentials.Certificate(cred_dict)
    initialize_app(cred)
    db = firestore.client()
    print("Firebase inicializado correctamente.")
except Exception as e:
    print(f"Error al inicializar Firebase: {e}")
    db = None


# Modelo para las solicitudes de notificación
class Vehiculo(BaseModel):
    tipo: Optional[str] = ""
    placa: Optional[str] = ""
    marca: Optional[str] = ""
    modelo: Optional[str] = ""
    horaEntrada: Optional[str] = ""
    nombreCliente: Optional[str] = ""

class NotificationRequest(BaseModel):
    to: str  # El token del administrador
    vehiculo: Vehiculo  # Información del vehículo
    spaceId: int  # ID del espacio de estacionamiento
    
class UserNotificationRequest(BaseModel):
    to: str  # El token del usuario
    message: Optional[str] = ""  # Mensaje de la notificación

# Función para obtener los tokens de usuarios administrativos
def get_admin_tokens() -> List[str]:
    try:
        if db is None:
            raise RuntimeError("Firestore no está inicializado.")
        query = db.collection('usuarios').where('role', '==', 'Administrativo').stream()
        tokens = [user_doc.to_dict().get("fcmToken") for user_doc in query if user_doc.to_dict().get("fcmToken")]
        if not tokens:
            print("No se encontraron tokens administrativos.")
        return tokens
    except Exception as e:
        print(f"Error al obtener tokens: {e}")
        return []

# Función para enviar la notificación
def send_admin_notification(tokens: List[str], message_body: str):
    try:
        if not tokens:
            print("No se enviaron notificaciones. No hay tokens disponibles.")
            return
        for token in tokens:
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title="Aviso importante",
                        body=message_body
                    ),
                    token=token
                )
                response = messaging.send(message)
                print(f"Notificación enviada a token {token}: {response}")
            except Exception as e:
                print(f"Error al enviar notificación al token {token}: {e}")
    except Exception as e:
        print(f"Error al enviar la notificación: {e}")

# Función para verificar la ocupación del estacionamiento
def check_parking_occupancy():
    try:
        spaces_ref = db.collection('espaciosEstacionamiento')
        spaces_docs = spaces_ref.stream()

        total_spaces = 0
        occupied_spaces = 0

        for space_doc in spaces_docs:
            space_data = space_doc.to_dict()
            if space_data.get('ocupado', False):
                occupied_spaces += 1
            total_spaces += 1

        occupancy_percentage = (occupied_spaces / total_spaces) * 100
        print(f"Ocupación del estacionamiento: {occupancy_percentage}%")

        if occupancy_percentage >= 100:
            admin_tokens = get_admin_tokens()
            if admin_tokens:
                message_body = "¡Alerta! El estacionamiento está lleno. No hay más espacios disponibles."
                send_admin_notification(admin_tokens, message_body)
        elif occupancy_percentage > 80:
            admin_tokens = get_admin_tokens()
            if admin_tokens:
                message_body = "¡Atención! El estacionamiento está casi lleno."
                send_admin_notification(admin_tokens, message_body)
    except Exception as e:
        print(f"Error al verificar la ocupación del estacionamiento: {e}")

# Función para ejecutar tareas programadas
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

# Tarea programada
schedule.every().day.at("18:15").do(check_parking_occupancy)
thread = Thread(target=run_schedule, daemon=True)
thread.start()

@app.get("/")
async def hello():
    return {"message": "¡La aplicación está funcionando!"}

@app.post("/send_notification")
async def send_notification(request: NotificationRequest):
    try:
        admin_token = request.to
        vehiculo = request.vehiculo or {}
        space_id = request.spaceId
        notification_body = (
            f"El espacio {space_id} ha sido marcado como ocupado. "
            f"Vehículo: {vehiculo.marca} {vehiculo.modelo} "
            f"({vehiculo.placa}, {vehiculo.tipo}) a las {vehiculo.horaEntrada}, "
            f"Nombre del Cliente: {vehiculo.nombreCliente}"
        )

        message = messaging.Message(
            notification=messaging.Notification(
                title="¡Estacionamiento Ocupado!",
                body=notification_body
            ),
            token=admin_token,
            data={key: str(value) for key, value in vehiculo if value} | {"space_id": str(space_id)}
        )

        response = messaging.send(message)
        return {"message": "Mensaje enviado con éxito", "response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al enviar la notificación: {e}")

@app.post("/send_user_notification")
async def send_user_notification(request: UserNotificationRequest):
    try:
        user_token = request.to
        message_text = request.message or "Tienes una nueva notificación."

        message = messaging.Message(
            notification=messaging.Notification(
                title="Notificación UPN-Parking",
                body=message_text
            ),
            token=user_token
        )

        response = messaging.send(message)
        return {"message": "Mensaje enviado con éxito", "response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al enviar la notificación: {e}")
