"""Проверка совместимости веб-обёртки Flet с установленным FastAPI."""

import unittest

from fastapi.testclient import TestClient
from flet_web.fastapi import FastAPI


class WebStartupTests(unittest.TestCase):
    def test_flet_web_app_serves_requests_and_runs_lifecycle_hooks(self):
        events = []
        app = FastAPI(
            on_startup=[lambda: events.append("startup")],
            on_shutdown=[lambda: events.append("shutdown")],
        )

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        with TestClient(app) as client:
            self.assertEqual(events, ["startup"])
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})

        self.assertEqual(events, ["startup", "shutdown"])


if __name__ == "__main__":
    unittest.main()
