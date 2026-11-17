from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .errors import install
from .store import Store
from . import web
from .modules.m1_intake import handler as m1_handler
from .modules.m2_encoding import handler as m2_handler
from .modules.m3_fields import handler as m3_handler
from .modules.m4_content import handler as m4_handler
from .modules.m5_reconcile import handler as m5_handler
from .modules.m6_runs import handler as m6_handler

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="历史档案混合编码归一与索引保形", version=settings.rule_version)
    app.state.settings = settings
    app.state.store = Store(settings.db_path)
    app.state.templates = web.templates
    app.mount("/static", StaticFiles(directory=str(web.BASE / "static")), name="static")
    for module in (m1_handler, m2_handler, m3_handler, m4_handler, m5_handler, m6_handler,):
        app.include_router(module.router)
    install(app)
    @app.get("/api/health")
    def health():
        return {"status": "ok", "project": "archivecodec", "runs": app.state.store.count()}
    @app.get("/")
    def home():
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/intake")
    return app

app = create_app()
