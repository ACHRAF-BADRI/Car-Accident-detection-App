# Training data sources

| Files | Class | Source | License |
|---|---|---|---|
| `Capture d'écran …` and other original files | both | Original project dataset | as in the project |
| `hf_cctv_*` | Accident (a few Non Accident) | [justjuu/traffic-accident-cctv-object-detection](https://huggingface.co/datasets/justjuu/traffic-accident-cctv-object-detection), from the Roboflow "Accident and Non-accident label Image Dataset" | CC0 1.0 as published; the frames come from online crash videos (some carry channel logos) |
| `detrac_*` | Non Accident | [UA-DETRAC](https://arxiv.org/abs/1511.04136) road-camera sequences, via [abhineet123/ua_detrac](https://huggingface.co/datasets/abhineet123/ua_detrac) | Mirror says CC BY 4.0; the original UA-DETRAC license is CC BY-NC-SA 3.0 (non-commercial) |

The downloaded files (`hf_cctv_*`, `detrac_*`) are not committed to git. Recreate them with:

```bash
python download_training_data.py
```

Use for study / non-commercial purposes only.
