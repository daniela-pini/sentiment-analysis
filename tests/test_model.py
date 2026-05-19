"""
Unit tests for the Sentiment Analysis model.
"""
import pickle
import pytest
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "sentimentanalysismodel.pkl")


@pytest.fixture(scope="module")
def model():
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


class TestModelLoading:
    def test_model_loads(self, model):
        assert model is not None

    def test_model_has_predict(self, model):
        assert hasattr(model, "predict")

    def test_model_has_predict_proba(self, model):
        assert hasattr(model, "predict_proba")


class TestModelPredictions:
    def test_positive_review(self, model):
        result = model.predict(["I love this product so much, it is fantastic!"])
        assert result[0] == "positive"

    def test_negative_review(self, model):
        result = model.predict(["Terrible product, total waste of money, very disappointed."])
        assert result[0] == "negative"

    def test_model_classes(self, model):
        expected = {"positive", "negative", "neutral"}
        assert set(model.classes_) == expected

    def test_batch_prediction(self, model):
        reviews = [
            "Excellent quality, highly recommend!",
            "Worst purchase ever, broken on arrival.",
            "Average product, nothing special.",
        ]
        results = model.predict(reviews)
        assert len(results) == 3

    def test_output_labels(self, model):
        reviews = ["Great!", "Awful!", "Okay."]
        results = model.predict(reviews)
        valid_labels = {"positive", "negative", "neutral"}
        for r in results:
            assert r in valid_labels

    def test_predict_proba_shape(self, model):
        reviews = ["Great product!", "Terrible item."]
        proba = model.predict_proba(reviews)
        assert proba.shape[0] == 2
        assert proba.shape[1] >= 2

    def test_predict_proba_sums_to_one(self, model):
        reviews = ["Amazing!", "Terrible!", "Average."]
        proba = model.predict_proba(reviews)
        for row in proba:
            assert abs(row.sum() - 1.0) < 1e-6

    def test_confidence_range(self, model):
        reviews = ["I love this!", "I hate this!"]
        proba = model.predict_proba(reviews)
        for row in proba:
            assert all(0.0 <= p <= 1.0 for p in row)

    def test_single_word_input(self, model):
        result = model.predict(["good"])
        assert result[0] in {"positive", "negative", "neutral"}

    def test_special_characters(self, model):
        result = model.predict(["Amazing!!! 100% worth it :)"])
        assert result[0] in {"positive", "negative", "neutral"}
