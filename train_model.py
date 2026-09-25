"""Train a stronger accident classifier (EfficientNetB0 / MobileNetV2 transfer learning) and compare it to the current model.

    python train_model.py                # train, compare on Data/test, install only if better
    python train_model.py --no-install   # train and compare, never replace the current model

Same input as the app: a whole RGB frame resized to 250x250, values 0-255; output [Accident, Non Accident].
The model is saved as model/accident_model.keras, which detection.py loads first when it exists.
"""
import argparse
import json
import os
import shutil
from datetime import datetime

import random

import numpy as np
import tensorflow as tf
from PIL import Image
from keras.models import model_from_json

from overlays import add_overlays, title_card

DATA_DIR = "Data"
IMG_SIZE = (250, 250)      # what the app feeds the classifier
BACKBONE_SIZE = (224, 224)  # what MobileNetV2's ImageNet weights were trained on
NEW_MODEL = "model/accident_model.keras"
OLD_JSON, OLD_WEIGHTS = "model/model.json", "model/model_weights.h5"
REPORT = "model/training_report.json"
SEED = 42


CLASS_NAMES = ["Accident", "Non Accident"]  # label 0 / 1, same order as the app
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")


def to_array(img):
    return np.asarray(img.convert("RGB").resize(IMG_SIZE, Image.BILINEAR), dtype=np.uint8)


def load_split(name, shuffle, overlay_rate=0.0, title_cards=0, duplicate_with_overlays=False):
    """Read the images with Pillow: TensorFlow's own loader fails on accented file names on Windows
    ("Capture d'écran ..."). Each image is stretched to 250x250 RGB, like the frames the app classifies.

    overlay_rate: share of images (both classes alike) that get random text / logos drawn on them, so that
    "there is a caption on screen" stops predicting "accident". title_cards: extra text-only frames (non accident).
    duplicate_with_overlays: add an overlaid copy of every image (robustness test)."""
    rng = random.Random(SEED + len(name))
    random.seed(SEED + len(name))
    images, labels = [], []
    for label, class_name in enumerate(CLASS_NAMES):
        folder = os.path.join(DATA_DIR, name, class_name)
        for fname in sorted(os.listdir(folder)):
            if fname.lower().endswith(IMAGE_EXTS):
                with Image.open(os.path.join(folder, fname)) as img:
                    img = img.convert("RGB")
                    if duplicate_with_overlays:
                        images.append(to_array(add_overlays(img)))
                        labels.append(label)
                    elif rng.random() < overlay_rate:
                        img = add_overlays(img)
                    images.append(to_array(img))
                labels.append(label)
    for _ in range(title_cards):
        images.append(to_array(title_card()))
        labels.append(1)
    print(f"{name}{' (robustness)' if duplicate_with_overlays else ''}: {len(images)} images "
          f"({labels.count(0)} accident, {labels.count(1)} non accident)")
    ds = tf.data.Dataset.from_tensor_slices((np.stack(images), np.array(labels, dtype=np.int32)))  # uint8: 4x less RAM
    if shuffle:
        ds = ds.shuffle(len(images), seed=SEED, reshuffle_each_iteration=True)
    return ds.batch(32).map(lambda x, y: (tf.cast(x, tf.float32), y))


def build_model(name):
    """Frozen ImageNet backbone + small head. Preprocessing lives inside the model, so the app stays unchanged."""
    inputs = tf.keras.Input(shape=IMG_SIZE + (3,))
    x = tf.keras.layers.Resizing(*BACKBONE_SIZE)(inputs)
    if name == "efficientnet":
        # EfficientNet normalises 0-255 pixels itself
        backbone = tf.keras.applications.EfficientNetB0(input_shape=BACKBONE_SIZE + (3,), include_top=False, weights="imagenet")
    else:
        backbone = tf.keras.applications.MobileNetV2(input_shape=BACKBONE_SIZE + (3,), include_top=False, weights="imagenet")
        x = tf.keras.layers.Rescaling(1 / 127.5, offset=-1)(x)  # MobileNetV2 expects [-1, 1]
    backbone.trainable = False
    x = backbone(x, training=False)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(0.3)(x)
    outputs = tf.keras.layers.Dense(2, activation="softmax")(x)
    return tf.keras.Model(inputs, outputs), backbone


def augment(ds):
    """Random variations applied to training images only: flips, small rotations / zooms, lighting."""
    # Kept light: stronger variations made the first run underfit (82% on its own training images)
    aug = tf.keras.Sequential([
        tf.keras.layers.RandomFlip("horizontal"),
        tf.keras.layers.RandomZoom(0.08),
        tf.keras.layers.RandomBrightness(0.1, value_range=(0, 255)),
    ])
    return ds.map(lambda x, y: (aug(x, training=True), y), num_parallel_calls=tf.data.AUTOTUNE)


def class_weights(ds):
    labels = np.concatenate([y.numpy() for _, y in ds])
    counts = np.bincount(labels, minlength=2)
    return {i: len(labels) / (2 * c) for i, c in enumerate(counts)}  # balances Accident vs Non Accident


def evaluate(model, test_ds):
    """Metrics for the Accident class (label 0): an accident we miss and a false alarm both count."""
    y_true, y_pred = [], []
    for x, y in test_ds:
        y_pred.extend(np.argmax(model.predict(x, verbose=0), axis=1))
        y_true.extend(y.numpy())
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    tp = int(np.sum((y_pred == 0) & (y_true == 0)))  # accident found
    fn = int(np.sum((y_pred == 1) & (y_true == 0)))  # accident missed
    fp = int(np.sum((y_pred == 0) & (y_true == 1)))  # false alarm
    tn = int(np.sum((y_pred == 1) & (y_true == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"accuracy": (tp + tn) / len(y_true), "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "accidents_found": tp, "accidents_missed": fn, "false_alarms": fp, "correct_non_accidents": tn}


def existing_models():
    """Every model the new one has to beat: the original CNN, and the retrained one if there is one."""
    with open(OLD_JSON) as f:
        original = model_from_json(f.read())
    original.load_weights(OLD_WEIGHTS)
    models = {"original": original}
    if os.path.exists(NEW_MODEL):
        models["installed"] = tf.keras.models.load_model(NEW_MODEL)
    return models


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backbone", choices=["efficientnet", "mobilenet"], default="efficientnet")
    parser.add_argument("--epochs", type=int, default=20, help="max epochs with the backbone frozen")
    parser.add_argument("--fine-tune-epochs", type=int, default=30, help="max epochs fine-tuning the top of the backbone")
    parser.add_argument("--unfreeze", type=int, default=60, help="number of backbone layers fine-tuned in phase 2")
    parser.add_argument("--no-install", action="store_true", help="never replace the current model")
    args = parser.parse_args()
    tf.keras.utils.set_random_seed(SEED)

    train = load_split("train", True, overlay_rate=0.5, title_cards=300)
    val = load_split("val", False, overlay_rate=0.5, title_cards=50)
    test = load_split("test", False)
    # Same test images plus a copy of each with captions / logos, plus title cards: catches the "text = accident" shortcut
    robust = load_split("test", False, title_cards=100, duplicate_with_overlays=True)
    weights = class_weights(train)
    train = augment(train).prefetch(tf.data.AUTOTUNE)
    val, test, robust = (d.cache().prefetch(tf.data.AUTOTUNE) for d in (val, test, robust))

    model, backbone = build_model(args.backbone)
    stop = lambda patience: [
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=patience, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=2, min_lr=1e-7)]

    # Phase 1: only the new head learns
    print("\n=== Phase 1: training the classifier head ===")
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(train, validation_data=val, epochs=args.epochs, class_weight=weights, callbacks=stop(5))

    # Phase 2: also adapt the last blocks of the backbone, with a small learning rate
    print(f"\n=== Phase 2: fine-tuning the last {args.unfreeze} layers of {args.backbone} ===")
    backbone.trainable = True
    for layer in backbone.layers[:-args.unfreeze]:
        layer.trainable = False
    for layer in backbone.layers:
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False  # keep ImageNet statistics, the dataset is too small to re-estimate them
    model.compile(optimizer=tf.keras.optimizers.Adam(5e-5), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(train, validation_data=val, epochs=args.fine_tune_epochs, class_weight=weights, callbacks=stop(6))

    # Compare on the same test images: the new model must beat every existing one, clean AND with captions
    models = existing_models()
    models["new"] = model
    results = {name: evaluate(m, test) for name, m in models.items()}
    robust_results = {name: evaluate(m, robust) for name, m in models.items()}
    new_metrics = results["new"]
    for title, table in (("clean test images", results), ("robustness: + captions / logos / title cards", robust_results)):
        print(f"\n{title}\n{'':22}" + "".join(f"{name:>11}" for name in table))
        for key in ("accuracy", "precision", "recall", "f1", "accidents_found", "accidents_missed", "false_alarms"):
            fmt = (lambda v: f"{v:.1%}") if isinstance(table["new"][key], float) else str
            print(f"{key:22}" + "".join(f"{fmt(m[key]):>11}" for m in table.values()))

    score = lambda name: (robust_results[name]["f1"] + results[name]["f1"], results[name]["accuracy"])
    better = all(score("new") > score(name) for name in results if name != "new")
    current_name = "model/accident_model.keras" if "installed" in results else f"{OLD_JSON} + {OLD_WEIGHTS}"
    installed = False
    candidate = "model/accident_model_candidate.keras"
    model.save(candidate)
    if better and not args.no_install:
        if os.path.exists(NEW_MODEL):  # keep the previous version
            backup = f"model/backup_{datetime.now():%Y%m%d_%H%M%S}"
            os.makedirs(backup, exist_ok=True)
            shutil.move(NEW_MODEL, os.path.join(backup, os.path.basename(NEW_MODEL)))
        shutil.move(candidate, NEW_MODEL)
        installed = True
    print("\nNew model installed:", NEW_MODEL if installed else f"no (kept {current_name}; candidate in {candidate})")

    with open(REPORT, "w") as f:
        json.dump({"date": datetime.now().isoformat(timespec="seconds"), "results": results,
                   "robustness": robust_results, "installed": installed,
                   "test_images": sum(len(os.listdir(os.path.join(DATA_DIR, "test", c))) for c in CLASS_NAMES),
                   "train_images": sum(len(os.listdir(os.path.join(DATA_DIR, "train", c))) for c in CLASS_NAMES)},
                  f, indent=2)


if __name__ == "__main__":
    main()
