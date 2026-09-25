# Accident Detection Desktop App

This desktop application detects accidents from video feeds using computer vision and deep learning techniques. It leverages various libraries including NumPy, pandas, OpenCV-Python, TensorFlow, Keras, and Tkinter to accomplish its tasks.

## Features

- **Accident detection from video input**
- **Real-time accident detection**
- **User-friendly GUI using Tkinter**

## Requirements

- Python 3.7
- numpy
- pandas
- opencv-python
- tensorflow
- keras
- tkinter (usually included with Python)

## Model Training

The `model_weights.h5` model used for accident detection is generated from the `training_cnn.ipynb` notebook.

### Retraining (transfer learning)

`train_model.py` trains an EfficientNetB0-based classifier on `Data/` (train / val), compares it with the model in use on `Data/test`, and installs it as `model/accident_model.keras` only if it scores better. The app loads that file first when it exists; delete it to go back to `model.json` + `model_weights.h5`. Results are written to `model/training_report.json`.

```bash
python train_model.py              # train, compare, install if better
python train_model.py --no-install # train and compare only
```

Add new images to `Data/train/Accident` or `Data/train/Non Accident` (raw frames, without drawn boxes) and run it again.

## YOLO v3

- Download the `yolov3.weights` file from this link : https://huggingface.co/spaces/Epitech/Scarecrow/blob/main/yolov3.weights 
- Add the Yolo file to the folder "Yolo_Folder".

## Accounts and cloud storage

Accounts, accident images and recorded videos are stored in MongoDB Atlas through a small API server (`server/`, FastAPI). The desktop app never connects to the database itself.

1. Create a `.env` file at the project root (it is git-ignored):

    ```
    MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>/?retryWrites=true&w=majority
    MONGODB_DB=accident_detection
    JWT_SECRET_KEY=<long random string>
    JWT_EXPIRE_HOURS=12
    ADMIN_USERNAME=<first admin>
    ADMIN_PASSWORD=<their password>
    API_URL=http://127.0.0.1:8000
    ```

2. The admin account is created when the server first starts. Anyone can then sign up from the login screen (role "user"); an admin can promote other users.

3. When `API_URL` points to this PC, the desktop app starts the server by itself. To run it separately (for example on another machine):

    ```bash
    python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
    ```

- **Users** see their own detections. Accident images and every finished recording (one file per hour) are uploaded in the background; files that could not be sent are retried at the next login.
- **Admins** also get an *Administration* menu: a dashboard (users, images, videos, storage, uploads per day) and every user's images and videos.
- The free Atlas tier (M0) holds 512 MB, which a few hours of video can fill. The dashboard turns the storage figure red above 80%.

## Usage

1. **Navigate to the project directory:**

    ```bash
    cd path/to/your/project
    ```

2. **Run the main application file:**

    ```bash
    python main.py
    ```

3. **Sign in, or create an account** from the login screen.

4. **Using the application:**
    - Select a video file or enable the webcam for real-time accident detection.
    - Detections are shown in the app; accident images and recordings are saved locally (per account) and uploaded to the cloud.

5. **Stopping the detection process:**
    - Click **Stop** and confirm.

6. **Viewing accident images and recordings:**
    - Use the *Accident images* and *Recordings* menus.

