import os

os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")

from fastapi import FastAPI, Response
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace as otel_trace
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

_meter_provider: MeterProvider | None = None


def _ensure_otel(service_name: str) -> MeterProvider:
    """One MeterProvider per process, shared by every app instance.

    create_app() may be called many times (tests, multiple workers), but the
    httpx client instrumentation binds to the globally-set meter provider, so a
    single shared reader keeps server and client metrics in one Prometheus page.
    """
    global _meter_provider
    if _meter_provider is None:
        resource = Resource.create(
            {
                SERVICE_NAME: service_name,
                SERVICE_VERSION: os.environ.get("APP_VERSION", "0.0.0-dev"),
            }
        )
        reader = PrometheusMetricReader()
        _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        otel_metrics.set_meter_provider(_meter_provider)
        otel_trace.set_tracer_provider(TracerProvider(resource=resource))
        HTTPXClientInstrumentor().instrument()
    return _meter_provider


def setup_otel(app: FastAPI, service_name: str) -> None:
    provider = _ensure_otel(service_name)
    FastAPIInstrumentor.instrument_app(app, meter_provider=provider)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)