"""
Integration tests for the Sentiment Analysis REST API.
"""
import pytest
from fastapi.testclient import TestClient
import sys, os

# Ensure the app module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["MODEL_PATH"] = os.path.join(
    os.path.dirname(__file__), "..", "app", "sentimentanalysismodel.pkl"
)

from main import app  # noqa: E402

client = TestClient(app)


class TestHealthEndpoints:
    def test_root(self):
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "environment" in body
        assert "color" in body

    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


class TestPredictEndpoint:
    def test_positive_review(self):
        review = "I love this product so much, it is fantastic!"
        r = client.post("/predict", json={"review": review})
        assert r.status_code == 200
        body = r.json()
        assert body["sentiment"] == "positive"
        assert 0.0 <= body["confidence"] <= 1.0
        assert body["review"] == review

    def test_negative_review(self):
        r = client.post("/predict", json={"review": "Terrible quality, total waste of money."})
        assert r.status_code == 200
        assert r.json()["sentiment"] == "negative"

    def test_response_schema(self):
        r = client.post("/predict", json={"review": "Good enough product."})
        assert r.status_code == 200
        body = r.json()
        # Schema completo
        for field in ("sentiment", "confidence", "review", "request_id", "color"):
            assert field in body, f"Missing field: {field}"

    def test_valid_sentiment_labels(self):
        reviews = [
            "Outstanding, I love it!",
            "Broken junk, avoid.",
            "It does the job, nothing more.",
        ]
        valid = {"positive", "negative", "neutral"}
        for review in reviews:
            r = client.post("/predict", json={"review": review})
            assert r.status_code == 200
            assert r.json()["sentiment"] in valid

    def test_empty_review_returns_422(self):
        r = client.post("/predict", json={"review": ""})
        assert r.status_code == 422

    def test_whitespace_review_returns_422(self):
        r = client.post("/predict", json={"review": "   "})
        assert r.status_code == 422

    def test_missing_review_field(self):
        r = client.post("/predict", json={})
        assert r.status_code == 422

    def test_wrong_field_name(self):
        r = client.post("/predict", json={"text": "Great product!"})
        assert r.status_code == 422

    def test_long_review(self):
        long_review = "Amazing product! " * 100
        r = client.post("/predict", json={"review": long_review})
        assert r.status_code == 200


class TestDistributedTracing:
    """Tests for the X-Request-ID middleware used as distributed-tracing primitive."""

    def test_request_id_generated_when_absent(self):
        r = client.post("/predict", json={"review": "Nice product!"})
        assert r.status_code == 200
        # Response header is set
        assert "x-request-id" in {k.lower() for k in r.headers.keys()}
        # And it appears in the response body
        rid = r.json()["request_id"]
        assert rid
        assert len(rid) >= 16  # UUID-ish

    def test_request_id_propagated_when_provided(self):
        my_id = "trace-abc-123-test"
        r = client.post(
            "/predict",
            json={"review": "Cool product!"},
            headers={"X-Request-ID": my_id},
        )
        assert r.status_code == 200
        # Echoed back in header
        assert r.headers.get("x-request-id") == my_id
        # And in body
        assert r.json()["request_id"] == my_id

    def test_each_request_has_unique_id(self):
        ids = set()
        for _ in range(5):
            r = client.post("/predict", json={"review": "Nice item"})
            ids.add(r.json()["request_id"])
        # Tutti diversi
        assert len(ids) == 5


class TestMetricsEndpoint:
    def test_metrics_returns_200(self):
        client.post("/predict", json={"review": "Test review for metrics"})
        r = client.get("/metrics")
        assert r.status_code == 200

    def test_metrics_content_type(self):
        r = client.get("/metrics")
        assert "text/plain" in r.headers["content-type"]

    def test_metrics_contains_expected_metrics(self):
        client.post("/predict", json={"review": "Another test review"})
        r = client.get("/metrics")
        body = r.text
        assert "sentiment_api_requests_total" in body
        assert "sentiment_api_request_latency_seconds" in body
        assert "sentiment_api_cpu_usage_percent" in body
        assert "sentiment_api_memory_usage_bytes" in body

    def test_metrics_include_environment_and_color_labels(self):
        """Le metriche devono includere le label per distinguere staging/prod e blue/green."""
        client.post("/predict", json={"review": "Excellent quality!"})
        r = client.get("/metrics")
        body = r.text
        assert 'environment="' in body
        assert 'color="' in body
