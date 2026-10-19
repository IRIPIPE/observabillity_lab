import os
from urllib.request import Request, urlopen

from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

provider = TracerProvider(
    resource=Resource.create({"service.name": "lab-client"})
)
provider.add_span_processor(
    SimpleSpanProcessor(
        OTLPSpanExporter(
            endpoint=os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"]
        )
    )
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("propagation-demo")

try:
    with tracer.start_as_current_span(
        "GET task-api",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        headers = {}
        inject(headers)

        print("traceparent:", headers["traceparent"])
        print("Trace ID:", f"{span.get_span_context().trace_id:032x}")

        request = Request(
            "http://api:8000/tasks",
            headers=headers,
        )
        with urlopen(request, timeout=5) as response:
            response.read()
            print("HTTP:", response.status)
finally:
    provider.shutdown()
