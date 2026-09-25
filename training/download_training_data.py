"""Add CCTV images to data/ for training (then run training/train_model.py).

    python training/download_training_data.py

Accident:      justjuu/traffic-accident-cctv-object-detection (Hugging Face, CC0) - CCTV frames of collisions.
Non accident:  UA-DETRAC (Hugging Face mirror abhineet123/ua_detrac) - normal traffic from road cameras.
               Only the chosen frames are read out of the 5-10 GB ZIPs (HTTP range requests).

Files are prefixed (hf_cctv_*, detrac_*) so they can be told apart from the original images or removed.
Different UA-DETRAC sequences go to train / val / test, so the test never sees a scene used for training.
"""
import io
import os
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from PIL import Image

from remote_zip import HttpRangeFile

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HF = "https://huggingface.co/datasets"
ACCIDENT_REPO = f"{HF}/justjuu/traffic-accident-cctv-object-detection/resolve/main/data"
ACCIDENT_FILES = {"train": ["train-00000-of-00002.parquet", "train-00001-of-00002.parquet"],
                  "val": ["validation-00000-of-00001.parquet"], "test": ["test-00000-of-00001.parquet"]}
DETRAC = f"{HF}/abhineet123/ua_detrac/resolve/main"
# (zip, first sequence index, last, split, frames per sequence) -> about as many normal frames as accident frames
DETRAC_PLAN = [("ua_detrac_training_set.zip", 0, 50, "train", 42),
               ("ua_detrac_training_set.zip", 50, 60, "val", 32),
               ("ua_detrac_test_set.zip", 0, 40, "test", 8)]
MAX_WIDTH = 640  # smaller files; the model sees 250x250 anyway


def save(img, split, label, name):
    folder = os.path.join(DATA, split, label)
    os.makedirs(folder, exist_ok=True)
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    img.convert("RGB").save(os.path.join(folder, name), "JPEG", quality=92)


def accident_images():
    tmp = os.path.join(tempfile.gettempdir(), "hf_cctv")
    os.makedirs(tmp, exist_ok=True)
    counts = {}
    for split, files in ACCIDENT_FILES.items():
        n = 0
        for fname in files:
            path = os.path.join(tmp, fname)
            if not os.path.exists(path):
                print(f"  downloading {fname} ...")
                with requests.get(f"{ACCIDENT_REPO}/{fname}", stream=True, timeout=600) as r, open(path, "wb") as f:
                    r.raise_for_status()
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            for i, row in pd.read_parquet(path).iterrows():
                # an image showing any collision box is an accident scene
                label = "Accident" if 0 in list(row["objects"]["category"]) else "Non Accident"
                # the parquet part number keeps names unique across the two train files
                save(Image.open(io.BytesIO(row["image"]["bytes"])), split, label,
                     f"hf_cctv_{split}_{fname.split('-')[1]}_{i:05d}.jpg")
                counts[(split, label)] = counts.get((split, label), 0) + 1
                n += 1
        print(f"  accident dataset {split}: {n} images")
    return counts


def detrac_images():
    jobs = []
    listings = {}
    for zip_name, first, last, split, per_seq in DETRAC_PLAN:
        if zip_name not in listings:
            names = zipfile.ZipFile(HttpRangeFile(f"{DETRAC}/{zip_name}")).namelist()
            seqs = {}
            for n in sorted(names):
                if n.lower().endswith(".jpg"):
                    seqs.setdefault(n.rsplit("/", 1)[0], []).append(n)
            listings[zip_name] = seqs
        seqs = listings[zip_name]
        for seq in sorted(seqs)[first:last]:
            frames = seqs[seq]
            step = max(1, len(frames) // per_seq)  # evenly spread over the sequence: fewer near-duplicates
            for name in frames[::step][:per_seq]:
                jobs.append((zip_name, name, split, f"detrac_{split}_{seq.split('/')[-1]}_{name.rsplit('/', 1)[-1]}"))

    def work(chunk):
        zips = {}
        for zip_name, name, split, out in chunk:
            if os.path.exists(os.path.join(DATA, split, "Non Accident", out)):
                continue
            if zip_name not in zips:
                zips[zip_name] = zipfile.ZipFile(HttpRangeFile(f"{DETRAC}/{zip_name}"))
            save(Image.open(io.BytesIO(zips[zip_name].read(name))), split, "Non Accident", out)
        return len(chunk)

    workers = 8
    chunks = [jobs[i::workers] for i in range(workers)]
    with ThreadPoolExecutor(workers) as pool:
        done = sum(pool.map(work, chunks))
    counts = {}
    for _, _, split, _ in jobs:
        counts[(split, "Non Accident")] = counts.get((split, "Non Accident"), 0) + 1
    print(f"  UA-DETRAC: {done} frames")
    return counts


if __name__ == "__main__":
    print("Accident images (CCTV, CC0):")
    a = accident_images()
    print("Normal traffic (UA-DETRAC road cameras):")
    d = detrac_images()
    print("\nAdded:")
    for split in ("train", "val", "test"):
        for label in ("Accident", "Non Accident"):
            added = a.get((split, label), 0) + d.get((split, label), 0)
            total = len(os.listdir(os.path.join(DATA, split, label)))
            print(f"  {split:5} {label:13} +{added:5}  -> {total} images")
