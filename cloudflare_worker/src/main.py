from __future__ import annotations

import asgi
from workers import WorkerEntrypoint

from rapyvet_api import app


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        worker_request = getattr(request, "js_object", request)
        return await asgi.fetch(app, worker_request, self.env)

