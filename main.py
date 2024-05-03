from fastapi import FastAPI, WebSocket, Request, Depends, HTTPException, Form, APIRouter, UploadFile

import base64
import cv2
import numpy as np
from datetime import datetime
import os
import httpx
from fastapi.params import File, Header
from pydantic import BaseModel
from fastapi.templating import Jinja2Templates
import secrets
from sqlalchemy.orm import Session
from models.database import get_db
from passlib.context import CryptContext
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse


from models.models import User, TemporaryKey

app = FastAPI()
templates = Jinja2Templates(directory="templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

downloads_dir = "downloads"
os.makedirs(downloads_dir, exist_ok=True)

app.add_middleware(SessionMiddleware, secret_key="your-secret-key")

router = APIRouter()



class APIKey(BaseModel):
    api_key: str

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/register")
async def show_register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/login")
async def show_login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/register")
async def register_user(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = pwd_context.hash(password)
    new_user = User(email=email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    return templates.TemplateResponse("registration_success.html", {"request": request, "email": email})


@app.post("/login")
def login_user(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    # Сохранение ID пользователя в сессии
    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "email": user.email,
        "api_key": user.api_key,
        "remaining_verifications": user.total_requests
    })


@app.post("/generate-api-key")
async def generate_api_key(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Генерация нового API ключа
    new_api_key = secrets.token_urlsafe(32)
    user.api_key = new_api_key
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/generate-temp-key")
async def generate_temp_key(api_key: APIKey, db: Session = Depends(get_db)):
    api_key_value = api_key.api_key
    user = db.query(User).filter(User.api_key == api_key_value).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")


    new_temp_key = secrets.token_urlsafe(32)

    print(new_temp_key)
    temp_key_entry = TemporaryKey(temp_key=new_temp_key)
    user.total_requests -= 1
    db.add(temp_key_entry)
    db.commit()

    return {"new_temp_key": new_temp_key}

app.include_router(router)
@app.post("/update-requests")
async def update_requests(request: Request, amount: int = Form(...), db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")


    user.total_requests += amount
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


class Message(BaseModel):
    api_key: str
    message: str
    url: str


@app.post("/send_result")
async def send_result(data: Message):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(data.url, json={"api_key": data.api_key, "message": data.message})
            return {"status": response.status_code, "response_data": response.json()}
        except httpx.RequestError as e:
            return {"error": "An error occurred while requesting."}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, db: Session = Depends(get_db)):
    await websocket.accept()
    received_key = await websocket.receive_text()


    user = db.query(User).filter(User.api_key == received_key).first()
    if not user and not db.query(TemporaryKey).filter(TemporaryKey.temp_key == received_key).first():
        print("noy")
        await websocket.close(code=1008)
        return
    elif user and user.total_requests <= 0:
        await websocket.send_text("No remaining verifications left.")
        await websocket.close(code=1008)
        return
    elif db.query(TemporaryKey).filter(TemporaryKey.temp_key == received_key).first():
        db.query(TemporaryKey).filter(TemporaryKey.temp_key == received_key).delete()
        db.commit()
    else:
        user.total_requests -= 1
        db.commit()

    frame_count = 0
    try:
        # Здесь мы останавливаемся после 50 кадров,
        # в будущем на этом участке будет работать
        # модель и остановка будет осуществляться
        # по результатам работы модели
        while True:
            data = await websocket.receive_text()
            img_data = base64.b64decode(data)
            nparr = np.frombuffer(img_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is not None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                filename = f'{downloads_dir}/frame_{timestamp}.jpg'
                cv2.imwrite(filename, frame)
                frame_count += 1
            else:
                print("Frame decode failed.")
            if frame_count > 50:
                url = "http://localhost:5000/receive_result"
                message = "verified"

                message_data = Message(api_key=received_key, message=message, url=url)

                await send_result(message_data)
                return

        await websocket.close()
    except Exception as e:
        print('Error:', e)
    finally:
        await websocket.close()


@app.post("/single_frame")
async def single_frame(file: UploadFile = File(...), authorization: str = Header(None), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.api_key == authorization).first()
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user.total_requests -= 1
    db.commit()
    return {"filename": file.filename, "message": "Image received successfully"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
