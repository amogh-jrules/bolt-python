import json
import re
from time import time

from slack_sdk.signature import SignatureVerifier
from slack_sdk.web import WebClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from slack_bolt.adapter.starlette import SlackRequestHandler
from slack_bolt.app import App
from tests.mock_web_api_server import (
    setup_mock_web_api_server,
    cleanup_mock_web_api_server,
)
from tests.utils import remove_os_env_temporarily, restore_os_env


class TestStarlette:
    signing_secret = "secret"
    valid_token = "xoxb-valid"
    mock_api_server_base_url = "http://localhost:8888"
    signature_verifier = SignatureVerifier(signing_secret)
    web_client = WebClient(token=valid_token, base_url=mock_api_server_base_url,)

    def setup_method(self):
        self.old_os_env = remove_os_env_temporarily()
        setup_mock_web_api_server(self)

    def teardown_method(self):
        cleanup_mock_web_api_server(self)
        restore_os_env(self.old_os_env)

    def generate_signature(self, body: str, timestamp: str):
        return self.signature_verifier.generate_signature(
            body=body, timestamp=timestamp,
        )

    def build_headers(self, timestamp: str, body: str):
        return {
            "content-type": "application/x-www-form-urlencoded",
            "x-slack-signature": self.generate_signature(body, timestamp),
            "x-slack-request-timestamp": timestamp,
        }

    def test_events(self):
        app = App(client=self.web_client, signing_secret=self.signing_secret,)

        def event_handler():
            pass

        app.event("app_mention")(event_handler)

        app_handler = SlackRequestHandler(app)

        payload = {
            "token": "verification_token",
            "team_id": "T111",
            "enterprise_id": "E111",
            "api_app_id": "A111",
            "event": {
                "client_msg_id": "9cbd4c5b-7ddf-4ede-b479-ad21fca66d63",
                "type": "app_mention",
                "text": "<@W111> Hi there!",
                "user": "W222",
                "ts": "1595926230.009600",
                "team": "T111",
                "channel": "C111",
                "event_ts": "1595926230.009600",
            },
            "type": "event_callback",
            "event_id": "Ev111",
            "event_time": 1595926230,
            "authed_users": ["W111"],
        }
        timestamp, body = str(int(time())), json.dumps(payload)

        async def endpoint(req: Request):
            return await app_handler.handle(req)

        api = Starlette(
            debug=True,
            routes=[Route("/slack/events", endpoint=endpoint, methods=["POST"])],
        )
        client = TestClient(api)
        response = client.post(
            "/slack/events", data=body, headers=self.build_headers(timestamp, body),
        )
        assert response.status_code == 200
        assert self.mock_received_requests["/auth.test"] == 1

    def test_shortcuts(self):
        app = App(client=self.web_client, signing_secret=self.signing_secret,)

        def shortcut_handler(ack):
            ack()

        app.shortcut("test-shortcut")(shortcut_handler)

        app_handler = SlackRequestHandler(app)

        payload = {
            "type": "shortcut",
            "token": "verification_token",
            "action_ts": "111.111",
            "team": {
                "id": "T111",
                "domain": "workspace-domain",
                "enterprise_id": "E111",
                "enterprise_name": "Org Name",
            },
            "user": {"id": "W111", "username": "primary-owner", "team_id": "T111"},
            "callback_id": "test-shortcut",
            "trigger_id": "111.111.xxxxxx",
        }

        timestamp, body = str(int(time())), json.dumps(payload)

        async def endpoint(req: Request):
            return await app_handler.handle(req)

        api = Starlette(
            debug=True,
            routes=[Route("/slack/events", endpoint=endpoint, methods=["POST"])],
        )
        client = TestClient(api)
        response = client.post(
            "/slack/events", data=body, headers=self.build_headers(timestamp, body),
        )
        assert response.status_code == 200
        assert self.mock_received_requests["/auth.test"] == 1

    def test_commands(self):
        app = App(client=self.web_client, signing_secret=self.signing_secret,)

        def command_handler(ack):
            ack()

        app.command("/hello-world")(command_handler)

        app_handler = SlackRequestHandler(app)

        payload = (
            "token=verification_token"
            "&team_id=T111"
            "&team_domain=test-domain"
            "&channel_id=C111"
            "&channel_name=random"
            "&user_id=W111"
            "&user_name=primary-owner"
            "&command=%2Fhello-world"
            "&text=Hi"
            "&enterprise_id=E111"
            "&enterprise_name=Org+Name"
            "&response_url=https%3A%2F%2Fhooks.slack.com%2Fcommands%2FT111%2F111%2Fxxxxx"
            "&trigger_id=111.111.xxx"
        )
        timestamp, body = str(int(time())), json.dumps(payload)

        async def endpoint(req: Request):
            return await app_handler.handle(req)

        api = Starlette(
            debug=True,
            routes=[Route("/slack/events", endpoint=endpoint, methods=["POST"])],
        )
        client = TestClient(api)
        response = client.post(
            "/slack/events", data=body, headers=self.build_headers(timestamp, body),
        )
        assert response.status_code == 200
        assert self.mock_received_requests["/auth.test"] == 1

    def test_oauth(self):
        app = App(
            client=self.web_client,
            signing_secret=self.signing_secret,
            client_id="111.111",
            client_secret="xxx",
            scopes=["chat:write", "commands"],
        )
        app_handler = SlackRequestHandler(app)

        async def endpoint(req: Request):
            return await app_handler.handle(req)

        api = Starlette(
            debug=True,
            routes=[Route("/slack/install", endpoint=endpoint, methods=["GET"])],
        )
        client = TestClient(api)
        response = client.get("/slack/install", allow_redirects=False)
        assert response.status_code == 302
        assert re.match(
            "https://slack.com/oauth/v2/authorize\\?state=[^&]+&client_id=111.111&scope=chat:write,commands&user_scope=",
            response.headers["Location"],
        )