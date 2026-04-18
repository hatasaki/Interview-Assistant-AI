import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

# NOTE: Per Azure Monitor OpenTelemetry docs, configure_azure_monitor() must
# be called BEFORE importing FastAPI so the ASGI/HTTP instrumentation can
# patch the framework. See:
# https://learn.microsoft.com/troubleshoot/azure/azure-monitor/app-insights/telemetry/opentelemetry-troubleshooting-python
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor()
    except Exception:  # pragma: no cover - telemetry must never break the app
        logging.getLogger(__name__).exception(
            "Failed to configure Azure Monitor OpenTelemetry"
        )

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers import interviews, speech, websocket
from services import agent_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Increase thread pool for async agent calls
_executor = ThreadPoolExecutor(max_workers=20)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set larger thread pool for asyncio.to_thread
    loop = asyncio.get_event_loop()
    loop.set_default_executor(_executor)
    # Startup: ensure the Foundry agent exists
    try:
        agent_service.ensure_agent()
    except Exception:
        logger.exception("Failed to initialize agent – will retry on first request")
    yield
    _executor.shutdown(wait=False)


app = FastAPI(title="Interview Assistant AI", lifespan=lifespan)

# Routers
app.include_router(interviews.router)
app.include_router(speech.router)
app.include_router(websocket.router)

# Serve frontend static files (built by Vite into backend/static/)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
