import os
import time
import cv2
import numpy as np
from datetime import datetime
from desktop.detection.classifier import AccidentDetectionModel
from desktop.paths import SCREENSHOT_DIR, asset

YOLO_WEIGHTS = asset("yolo", "yolov3.weights")
YOLO_CFG = asset("yolo", "yolov3.cfg")
YOLO_NAMES = asset("yolo", "coco.names")
MODEL_JSON = asset("model", "model.json")
MODEL_WEIGHTS = asset("model", "model_weights.h5")
MODEL_FILE = asset("model", "accident_model.keras")  # written by training/train_model.py, preferred when present

# COCO class ids we care about -> box color (BGR)
VEHICLE_COLORS = {
    2: (0, 255, 0),    # car
    3: (255, 255, 0),  # motorbike
    5: (0, 0, 255),    # bus
    7: (255, 0, 0),    # truck
}

font = cv2.FONT_HERSHEY_DUPLEX


class AccidentDetector:
    """Loads YOLO + the accident CNN once and processes frames one at a time."""

    def __init__(self):
        self.net = cv2.dnn.readNet(YOLO_WEIGHTS, YOLO_CFG)
        with open(YOLO_NAMES, "r") as f:
            self.classes = [line.strip() for line in f.readlines()]

        layer_names = self.net.getLayerNames()
        out_indices = np.array(self.net.getUnconnectedOutLayers()).flatten()
        self.output_layers = [layer_names[i - 1] for i in out_indices]

        self.model = AccidentDetectionModel(MODEL_JSON, MODEL_WEIGHTS, MODEL_FILE)
        self._last_screenshot = 0.0

    def process_frame(self, frame, threshold=86.0, save_screenshots=True, cooldown=0.0, screenshot_dir=SCREENSHOT_DIR):
        """Annotate `frame` in place and return (frame, info).

        info = {"vehicles": int, "accident": bool, "probability": float, "screenshot": path or None}
        """
        height, width = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(frame, 0.00392, (416, 416), (0, 0, 0), True, crop=False)
        self.net.setInput(blob)
        outs = self.net.forward(self.output_layers)

        class_ids, confidences, boxes = [], [], []
        for out in outs:
            for detection in out:
                scores = detection[5:]
                class_id = int(np.argmax(scores))
                confidence = float(scores[class_id])
                if confidence > 0.5 and class_id in VEHICLE_COLORS:
                    center_x = int(detection[0] * width)
                    center_y = int(detection[1] * height)
                    w = int(detection[2] * width)
                    h = int(detection[3] * height)
                    boxes.append([int(center_x - w / 2), int(center_y - h / 2), w, h])
                    confidences.append(confidence)
                    class_ids.append(class_id)

        # Keep an untouched copy: the classifier was trained on clean images, not on frames with our boxes drawn on them
        clean = frame.copy()
        indexes = np.array(cv2.dnn.NMSBoxes(boxes, confidences, 0.5, 0.4)).flatten() if boxes else []
        for i in indexes:
            x, y, w, h = boxes[i]
            color = VEHICLE_COLORS[class_ids[i]]
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, self.classes[class_ids[i]], (x, y - 10), font, 0.5, color, 1)

        info = {"vehicles": len(indexes), "accident": False, "probability": 0.0, "screenshot": None}
        if not boxes:
            return frame, info

        # The accident classifier looks at the whole frame
        rgb = cv2.cvtColor(clean, cv2.COLOR_BGR2RGB)
        roi = cv2.resize(rgb, (250, 250))
        pred, prob = self.model.predict_accident(roi[np.newaxis, :, :])
        accident_prob = round(float(prob[0][0]) * 100, 2)
        info["probability"] = accident_prob

        if pred == "Accident" and accident_prob >= threshold:
            info["accident"] = True
            cv2.rectangle(frame, (0, 0), (width, height), (0, 0, 255), 5)
            cv2.putText(frame, f"Warning {pred} {accident_prob}%", (20, 40), font, 1, (0, 0, 255), 2)

            now = time.time()
            if save_screenshots and now - self._last_screenshot >= cooldown:
                self._last_screenshot = now
                os.makedirs(screenshot_dir, exist_ok=True)
                # milliseconds: with no interval, several images can be saved within the same second
                stamp = datetime.now().strftime("%Y%m%d%H%M%S_%f")[:-3]
                path = os.path.join(screenshot_dir, f"screenshot_{stamp}.png")
                cv2.imwrite(path, frame)
                info["screenshot"] = path

        return frame, info


def startapplication(video_path):
    """Legacy entry point: run detection in a plain OpenCV window (press q to quit)."""
    detector = AccidentDetector()
    video = cv2.VideoCapture(video_path)
    while True:
        ret, frame = video.read()
        if not ret:
            break
        frame, _ = detector.process_frame(frame)
        cv2.imshow("Video", frame)
        if cv2.waitKey(33) & 0xFF == ord("q"):
            break
    video.release()
    cv2.destroyAllWindows()
