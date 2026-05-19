import pickle
import time
import os
import uuid
import warnings
import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import psutil

warnings.filterwarnings("ignore")

# ── Logging setup ─────────────────────────────────────────────────────────────
# Log format includes the request_id when present, to support distributed
# tracing across the API gateway → service → downstream calls chain.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [req=%(request_id)s] %(name)s: %(message)s",
)


class RequestIdFilter(logging.Filter):
    """Inject request_id into every log record. Defaults to '-' if not set."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


logger = logging.getLogger(__name__)
for handler in logging.root.handlers:
    handler.addFilter(RequestIdFilter())

# Identifies which deployment color is serving the request (blue/green).
# Set via env var by docker-compose; defaults to "n/a" in local dev.
DEPLOYMENT_COLOR = os.getenv("DEPLOYMENT_COLOR", "n/a")
ENVIRONMENT = os.getenv("ENVIRONMENT", "staging")

# ── Load model ──────────────────────────────────────────────────────────────
MODEL_PATH = os.getenv("MODEL_PATH", "sentimentanalysismodel.pkl")

with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)

logger.info(
    "Model loaded from %s | env=%s color=%s", MODEL_PATH, ENVIRONMENT, DEPLOYMENT_COLOR
)

# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Sentiment Analysis API",
    description="REST API for product review sentiment analysis",
    version="1.0.0",
)

# ── Prometheus metrics ───────────────────────────────────────────────────────
# Labels include `environment` and `color` so the same Prometheus instance can
# distinguish metrics between staging and the blue/green production replicas.
REQUEST_COUNT = Counter(
    "sentiment_api_requests_total",
    "Total number of prediction requests",
    ["method", "endpoint", "sentiment", "environment", "color"],
)
REQUEST_LATENCY = Histogram(
    "sentiment_api_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint", "environment", "color"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)
PREDICTION_ERRORS = Counter(
    "sentiment_api_prediction_errors_total",
    "Total number of prediction errors",
    ["environment", "color"],
)
CPU_USAGE = Gauge(
    "sentiment_api_cpu_usage_percent",
    "CPU usage percent",
    ["environment", "color"],
)
MEMORY_USAGE = Gauge(
    "sentiment_api_memory_usage_bytes",
    "Memory usage in bytes",
    ["environment", "color"],
)


# ── Middleware: distributed tracing via request_id ────────────────────────────
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """
    Distributed tracing primitive.

    Generates a request_id (UUID4) for each incoming request, or reuses one
    propagated upstream via the X-Request-ID header (e.g. from nginx, an API
    gateway, or a calling microservice). The id is attached to request.state
    so route handlers can read it, and echoed back in the response header so
    callers can correlate logs across services.
    """
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id

    # Add request_id to all log records emitted during this request
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.request_id = request_id
        return record

    logging.setLogRecordFactory(record_factory)
    try:
        response = await call_next(request)
    finally:
        logging.setLogRecordFactory(old_factory)

    response.headers["X-Request-ID"] = request_id
    return response


# ── Schemas ──────────────────────────────────────────────────────────────────
class ReviewRequest(BaseModel):
    review: str

    model_config = {"json_schema_extra": {"example": {"review": "This product is amazing!"}}}


class PredictionResponse(BaseModel):
    sentiment: str
    confidence: float
    review: str
    request_id: str
    color: str


# ── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {
        "status": "ok",
        "service": "Sentiment Analysis API",
        "version": "1.0.0",
        "environment": ENVIRONMENT,
        "color": DEPLOYMENT_COLOR,
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy", "environment": ENVIRONMENT, "color": DEPLOYMENT_COLOR}


@app.post("/predict", response_model=PredictionResponse, tags=["Prediction"])
def predict(request: ReviewRequest, http_request: Request):
    start = time.time()
    request_id = http_request.state.request_id

    if not request.review or not request.review.strip():
        PREDICTION_ERRORS.labels(environment=ENVIRONMENT, color=DEPLOYMENT_COLOR).inc()
        logger.warning("Rejected empty review")
        raise HTTPException(status_code=422, detail="Review text cannot be empty.")

    try:
        sentiment = model.predict([request.review])[0]
        proba = model.predict_proba([request.review])[0]
        confidence = float(proba.max())
    except Exception as exc:
        PREDICTION_ERRORS.labels(environment=ENVIRONMENT, color=DEPLOYMENT_COLOR).inc()
        logger.error("Prediction failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(exc)}")

    latency = time.time() - start
    REQUEST_COUNT.labels(
        method="POST",
        endpoint="/predict",
        sentiment=sentiment,
        environment=ENVIRONMENT,
        color=DEPLOYMENT_COLOR,
    ).inc()
    REQUEST_LATENCY.labels(
        endpoint="/predict", environment=ENVIRONMENT, color=DEPLOYMENT_COLOR
    ).observe(latency)

    CPU_USAGE.labels(environment=ENVIRONMENT, color=DEPLOYMENT_COLOR).set(psutil.cpu_percent())
    MEMORY_USAGE.labels(environment=ENVIRONMENT, color=DEPLOYMENT_COLOR).set(
        psutil.Process().memory_info().rss
    )

    logger.info(
        "Prediction OK | sentiment=%s confidence=%.3f latency=%.4fs", sentiment, confidence, latency
    )
    return PredictionResponse(
        sentiment=sentiment,
        confidence=round(confidence, 4),
        review=request.review,
        request_id=request_id,
        color=DEPLOYMENT_COLOR,
    )


@app.get("/metrics", tags=["Monitoring"])
def metrics():
    """Expose Prometheus metrics."""
    CPU_USAGE.labels(environment=ENVIRONMENT, color=DEPLOYMENT_COLOR).set(psutil.cpu_percent())
    MEMORY_USAGE.labels(environment=ENVIRONMENT, color=DEPLOYMENT_COLOR).set(
        psutil.Process().memory_info().rss
    )
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
