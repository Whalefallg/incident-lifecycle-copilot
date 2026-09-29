from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Serve built frontend assets and fall back to index.html for client routes."""

    def __init__(self, directory: str | Path) -> None:
        super().__init__(directory=directory, html=True)
        self.index_path = Path(directory) / "index.html"

    async def get_response(self, path: str, scope: dict) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in {"GET", "HEAD"}:
                raise
            return FileResponse(self.index_path)
