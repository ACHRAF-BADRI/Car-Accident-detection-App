# AccidentAI — Car Accident Detection

Windows desktop application that detects road accidents in real time on a video file or a webcam. It finds the vehicles with **YOLOv3**, estimates the probability of an accident with a **CNN**, raises an alert, saves snapshots and recordings, and backs everything up to **MongoDB Atlas** through a small FastAPI server.

![AccidentAI detecting an accident](docs/assets/screens/detection.jpg)

**Website:** https://achraf-badri.github.io/Car-Accident-detection-App/ (download page, served from `docs/`)

## Features

- **Detection** on a video file (MP4, AVI, MKV, WEBM, MOV) or a webcam, played in real time, with pause / resume / stop
- **Alerts** above an adjustable threshold (86% by default), with an event log and a snapshot of every alert
- **Webcam recording** split into one-hour files, with an optional duration limit, and a built-in player (0.5× to 16×)
- **Accounts**: sign up, sign in (with "remember my username"), profile (name, email) and password change
- **Cloud backup**: accident images and finished recordings are uploaded in the background and retried if the connection drops
- **Delete** images and recordings one by one or all at once, on this PC and in the cloud
- **Admin area**: dashboard (users, images, videos, storage, uploads per day), create / suspend / delete users, change roles, edit profiles, view and delete every user's images and videos
- **Modern interface** (CustomTkinter): light / dark / system theme, English / French

## Architecture

```
Desktop app (CustomTkinter)  ──HTTP + JWT──>  API server (FastAPI, server/)  ──>  MongoDB Atlas
  YOLOv3 (OpenCV DNN)                           accounts, roles                     users
  accident CNN (TensorFlow / Keras)             media upload / download             GridFS: images, videos
```

The desktop app never talks to the database directly: only the API server holds the MongoDB credentials. When `API_URL` points to the local machine, the app starts the server by itself.

| Path | Role |
|---|---|
| `main.py`, `app.py` | Application entry point and windows / pages |
| `detection_service.py`, `detection.py` | YOLOv3 + accident classifier, frame by frame |
| `recorder.py`, `uploader.py`, `api_client.py` | Recording, background uploads, API calls |
| `admin_page.py`, `profile_page.py`, `widgets.py`, `i18n.py` | Admin area, profile, shared widgets, EN / FR texts |
| `server/` | FastAPI server: auth (JWT, bcrypt), media (GridFS), admin routes |
| `train_model.py`, `download_training_data.py`, `overlays.py` | Retraining tools |
| `docs/` | GitHub Pages website |

## Installation

Requires **Windows 10 / 11** and **Python 3.11** (tested with TensorFlow / Keras 2.15).

1. **Clone the project and install the dependencies**

    ```bash
    git clone https://github.com/ACHRAF-BADRI/Car-Accident-detection-App.git
    cd Car-Accident-detection-App
    pip install -r requirements.txt
    ```

2. **Add the two model files**, which are too large for the repository (GitHub limit: 100 MB):
    - `Yolo_Folder/yolov3.weights` — download it from https://huggingface.co/spaces/Epitech/Scarecrow/blob/main/yolov3.weights
    - `model/model_weights.h5` — the accident classifier, produced by `training_cnn.ipynb` (or retrained with `train_model.py`, see below)

3. **Create a `.env` file** at the project root (it is git-ignored, never commit it):

    ```
    MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>/?retryWrites=true&w=majority
    MONGODB_DB=accident_detection
    JWT_SECRET_KEY=<long random string>
    JWT_EXPIRE_HOURS=12
    ADMIN_USERNAME=<first admin>
    ADMIN_PASSWORD=<their password>
    API_URL=http://127.0.0.1:8000
    ```

    The admin account is created the first time the server starts. Everyone else signs up from the login screen (role "user"); an admin can promote them.

4. **Run the application**

    ```bash
    python main.py
    ```

    To run the API server on its own (for example on another machine), use `python -m uvicorn server.main:app --host 127.0.0.1 --port 8000` and point `API_URL` to it.

## Usage

1. **Sign in** or create an account.
2. **Detection**: click *Open video* or *Webcam*. Vehicles are boxed, the probability and the status update live, and alerts are written to the event log. *Pause* / *Resume* works on video files; *Stop* asks for confirmation and clears the screen. With no webcam plugged in, the app opens the camera setting.
3. **Accident images** and **Recordings**: browse, play (with speed control), open the folder, or delete one / all.
4. **Settings**: alert threshold, snapshots and snapshot interval, camera, theme, language, and webcam recording (folder, duration or no limit).
5. **My profile**: full name, email, password.
6. **Administration** (admins only): dashboard and user management.

Local files are stored per account: `Accidents_Screen/<username>/` and `Recordings/<username>/`.

## Improving the model

The classifier looks at the whole frame resized to 250×250. `model/model.json` + `model/model_weights.h5` is the original CNN (`training_cnn.ipynb`).

- **`download_training_data.py`** adds CCTV images to `Data/`: accident frames (CC0 dataset on Hugging Face) and normal traffic from road cameras (UA-DETRAC). Sources and licenses are listed in [Data/SOURCES.md](Data/SOURCES.md); the downloaded files are not committed.
- **`train_model.py`** trains an EfficientNetB0 classifier (transfer learning, augmentation, random text / logo overlays so captions are not mistaken for accidents), compares it with the existing models on `Data/test`, and installs it as `model/accident_model.keras` **only if it scores better**. Results go to `model/training_report.json`.

```bash
python download_training_data.py
python train_model.py              # train, compare, install if better
python train_model.py --no-install # train and compare only
```

The app loads `model/accident_model.keras` first when it exists; delete it to go back to the original model.

Test videos are in `Traffic_vids/` (credits in [Traffic_vids/SOURCES.md](Traffic_vids/SOURCES.md)).

## Website and releases

`docs/` is a static site (HTML / CSS / JS, EN / FR) for **GitHub Pages**: *Settings → Pages → Deploy from a branch → `main` / `docs`*. Its download button reads the latest **GitHub Release** and links to the attached `.exe`; until a release exists it points to the releases page.

## Security notes

- `.env` holds the database password and the JWT secret: keep it out of git and out of any installer.
- Before distributing an installer, host the API server online and ship the app with only `API_URL` pointing to it; the desktop app must not contain the MongoDB credentials.
- The free Atlas tier (M0) holds 512 MB, which a few hours of video can fill; the admin dashboard turns the storage figure red above 80%.

## Built with

Python · OpenCV · TensorFlow / Keras · CustomTkinter · FastAPI · MongoDB Atlas (PyMongo, GridFS) · PyJWT · bcrypt
