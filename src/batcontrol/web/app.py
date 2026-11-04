""" FastAPI application factory: API routes, docs and the dashboard. """
import logging
import pathlib
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __pkginfo__
from .auth import auth_dependencies
from .config import API_PREFIX, ApiConfig
from .routes import NoDataAvailable, no_data_response, public_router, router

logger = logging.getLogger(__name__)

DESCRIPTION = """
Access to a running batcontrol instance: battery, the current mode and why,
the night plan with its estimated savings, and the prices.

The only write is `/manual-charge`, which charges at full speed for a while.

Timestamps are epoch milliseconds, prices EUR/kWh, energy Wh, power W.
"""

STATIC_DIR = pathlib.Path(__file__).parent / 'static'

# Shown instead of the dashboard when the static assets are absent - normal
# for a source checkout without a Node build.
MISSING_DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>batcontrol</title>
<style>body{background:#030a05;color:#33ff66;font-family:ui-monospace,monospace;
padding:2rem;line-height:1.6}code{color:#ffcc33}</style></head>
<body>
<h1>batcontrol</h1>
<p>The API is running, but the dashboard assets are not installed.</p>
<p><code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code></p>
<p>The REST API at <code>api/v1/</code> is unaffected.</p>
</body></html>
"""


def create_app(batcontrol, config: Optional[ApiConfig] = None) -> FastAPI:
    """ Build the ASGI application for a live Batcontrol instance. """
    config = config or ApiConfig()
    app = FastAPI(
        title='batcontrol',
        summary='API of a running batcontrol instance',
        description=DESCRIPTION,
        version=__pkginfo__.__version__,
        openapi_url='/openapi.json' if config.docs_enabled else None,
        docs_url=None,
        redoc_url=None,
    )
    if config.docs_enabled:
        _add_docs(app, config)
    app.state.batcontrol = batcontrol

    @app.exception_handler(NoDataAvailable)
    async def _no_data(_request: Request, _exc: NoDataAvailable) -> JSONResponse:
        return no_data_response()

    app.include_router(public_router, prefix=API_PREFIX)
    app.include_router(router, prefix=API_PREFIX,
                       dependencies=auth_dependencies(config))

    # Mounted last, at the root, so the API routes keep precedence.
    if config.dashboard_enabled:
        _mount_dashboard(app)
    return app


def _add_docs(app: FastAPI, config: ApiConfig) -> None:
    """ Serve Swagger UI at /docs from the bundled assets when present. """
    swagger_dir = STATIC_DIR / 'swagger'
    urls = {}
    if (swagger_dir / 'swagger-ui-bundle.js').is_file():
        urls = {
            'swagger_js_url': 'swagger/swagger-ui-bundle.js',
            'swagger_css_url': 'swagger/swagger-ui.css',
            'swagger_favicon_url': 'favicon.svg',
        }
        if not config.dashboard_enabled:
            app.mount('/swagger', StaticFiles(directory=swagger_dir),
                      name='swagger')

    @app.get('/docs', include_in_schema=False)
    async def _swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url='openapi.json',
            title=f'{app.title} - API documentation',
            **urls,
        )


def _mount_dashboard(app: FastAPI) -> None:
    """ Serve the built dashboard at /, or a hint page when it is missing. """
    if (STATIC_DIR / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=STATIC_DIR, html=True),
                  name='dashboard')
        logger.info('Dashboard served from %s', STATIC_DIR)
        return

    @app.get('/', include_in_schema=False, response_class=HTMLResponse)
    async def _missing_dashboard() -> str:
        return MISSING_DASHBOARD_HTML

    logger.warning('Dashboard assets not found in %s, serving a hint page.',
                   STATIC_DIR)
