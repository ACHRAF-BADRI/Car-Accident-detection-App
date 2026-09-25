import os

from keras.models import load_model, model_from_json
import numpy as np

class AccidentDetectionModel(object):

    class_nums = ['Accident', "No Accident"]

    def __init__(self, model_json_file, model_weights_file, model_file=None):
        # The retrained model (train_model.py) is used when present; otherwise the original JSON + weights
        if model_file and os.path.exists(model_file):
            self.loaded_model = load_model(model_file)
            self.source = model_file
        else:
            with open(model_json_file, "r") as json_file:
                self.loaded_model = model_from_json(json_file.read())
            self.loaded_model.load_weights(model_weights_file)
            self.source = model_weights_file
        self.loaded_model.make_predict_function()

    def predict_accident(self, img):
        self.preds = self.loaded_model.predict(img, verbose=0)
        return AccidentDetectionModel.class_nums[np.argmax(self.preds)], self.preds
