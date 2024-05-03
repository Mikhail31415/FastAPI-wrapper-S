from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import base64
import cv2
import numpy as np
from datetime import datetime
import os

app = FastAPI()

downloads_dir = "downloads"
os.makedirs(downloads_dir, exist_ok=True)


@app.get("/")
async def get():
    return HTMLResponse(html)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    frame_count = 0
    try:
        # Здесь мы останавливаемся после 50 кадров,
        # в будущем на этом участке будет работать
        # модель и остановка будет осуществляться
        # по результатам работы модели
        while frame_count < 50:
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
        await websocket.send_text("50 frames received, stopping recording.")
        await websocket.close()
    except Exception as e:
        print('Error:', e)
    finally:
        if not websocket.closed:
            await websocket.close()


html = """
<!DOCTYPE html>
<html>
<head>
<title>Video Stream</title>
</head>
<body>
<button onclick="startStream()">Start Camera</button>
<video id="video" width="640" height="480" autoplay></video>
<script>
var video = document.getElementById('video');
var ws = new WebSocket('ws://localhost:8000/ws');

function startStream() {
    navigator.mediaDevices.getUserMedia({ video: true })
        .then(stream => {
            video.srcObject = stream;
            video.play();
            setInterval(() => {
                captureFrame();
            }, 100); // Отправка кадра каждые 100 мс
        })
        .catch(console.error);
}

function captureFrame() {
    var canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    var ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    var data = canvas.toDataURL('image/jpeg').split(',')[1];
    ws.send(data);
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
