"""Unit tests for A2AAdapter — agent card, task handling, streaming, webhooks."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_toolkit.framework.a2a_adapter import (
    A2AAdapter,
    A2AAgentCard,
    A2ATaskStatus,
)


@pytest.fixture
def mock_server():
    server = MagicMock()
    server.name = "test-server"
    server.list_tools = AsyncMock(
        return_value=[
            MagicMock(name="query_db", description="Query the database"),
            MagicMock(name="send_email", description="Send an email"),
        ]
    )
    server.call_tool = AsyncMock(return_value="Tool result text")
    return server


@pytest.fixture
def adapter(mock_server):
    return A2AAdapter(mock_server, base_url="https://test.example.com", description="Test server")


class TestA2AAgentCard:
    def test_to_dict(self):
        card = A2AAgentCard(
            name="test",
            description="A test agent",
            url="https://test.com",
            skills=[{"id": "skill1", "name": "Skill 1"}],
        )
        d = card.to_dict()
        assert d["name"] == "test"
        assert d["capabilities"]["streaming"] is True
        assert len(d["skills"]) == 1

    def test_to_json(self):
        card = A2AAgentCard(name="test", description="A test", url="https://test.com")
        json_str = card.to_json()
        assert '"name": "test"' in json_str

    def test_default_authentication(self):
        card = A2AAgentCard(name="t", description="d", url="u")
        assert card.authentication["schemes"] == ["bearer"]

    def test_push_notifications_false_by_default(self):
        card = A2AAgentCard(name="t", description="d", url="u")
        assert card.to_dict()["capabilities"]["pushNotifications"] is False

    def test_push_notifications_true_when_supports_push(self):
        card = A2AAgentCard(name="t", description="d", url="u", supports_push=True)
        assert card.to_dict()["capabilities"]["pushNotifications"] is True


class TestA2ATaskStatus:
    def test_to_dict_basic(self):
        status = A2ATaskStatus(task_id="t1", status="completed", message="Done")
        d = status.to_dict()
        assert d["id"] == "t1"
        assert d["status"]["state"] == "completed"
        assert d["status"]["message"]["parts"][0]["text"] == "Done"

    def test_to_dict_without_message(self):
        status = A2ATaskStatus(task_id="t1", status="working")
        d = status.to_dict()
        assert "message" not in d["status"]

    def test_to_dict_with_result(self):
        status = A2ATaskStatus(task_id="t1", status="completed", result={"output": "data"})
        d = status.to_dict()
        assert d["result"]["output"] == "data"

    def test_to_sse_format(self):
        status = A2ATaskStatus(task_id="t1", status="working")
        sse = status.to_sse()
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        payload = json.loads(sse[len("data: "):])
        assert payload["status"]["state"] == "working"

    def test_timestamp_present(self):
        status = A2ATaskStatus(task_id="t1", status="submitted")
        d = status.to_dict()
        assert "timestamp" in d["status"]
        assert isinstance(d["status"]["timestamp"], float)


class TestA2AAdapter:
    @pytest.mark.asyncio
    async def test_build_agent_card(self, adapter, mock_server):
        card = await adapter.build_agent_card()
        assert card.name == "test-server"
        assert len(card.skills) == 2

    @pytest.mark.asyncio
    async def test_get_agent_card_dict(self, adapter):
        d = await adapter.get_agent_card()
        assert d["name"] == "test-server"
        assert "capabilities" in d

    @pytest.mark.asyncio
    async def test_handle_task_success(self, adapter, mock_server):
        mock_server.call_tool.return_value = "Result text"
        status = await adapter.handle_task("task-1", "query_db", {"sql": "SELECT 1"})
        assert status.status == "completed"
        assert status.task_id == "task-1"
        mock_server.call_tool.assert_called_once_with("query_db", {"sql": "SELECT 1"})

    @pytest.mark.asyncio
    async def test_handle_task_failure(self, adapter, mock_server):
        mock_server.call_tool.side_effect = RuntimeError("Connection failed")
        status = await adapter.handle_task("task-2", "bad_tool", {})
        assert status.status == "failed"
        assert "Connection failed" in status.message

    def test_get_task_status(self, adapter):
        assert adapter.get_task_status("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_task_status_after_handle(self, adapter, mock_server):
        await adapter.handle_task("task-1", "query_db", {})
        status = adapter.get_task_status("task-1")
        assert status is not None
        assert status.status == "completed"

    def test_list_tasks_empty(self, adapter):
        assert adapter.list_tasks() == []

    @pytest.mark.asyncio
    async def test_list_tasks_after_handling(self, adapter, mock_server):
        await adapter.handle_task("t1", "query_db", {})
        await adapter.handle_task("t2", "send_email", {})
        tasks = adapter.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_agent_card_push_false_without_webhook(self, adapter):
        card = await adapter.get_agent_card()
        assert card["capabilities"]["pushNotifications"] is False

    @pytest.mark.asyncio
    async def test_agent_card_push_true_with_webhook_endpoint(self, adapter):
        card = await adapter.get_agent_card(webhook_endpoint="https://cb.example.com/hook")
        assert card["capabilities"]["pushNotifications"] is True


class TestA2AAdapterStreaming:
    @pytest.fixture
    def mock_server(self):
        server = MagicMock()
        server.name = "stream-server"
        server.list_tools = AsyncMock(return_value=[])
        server.call_tool = AsyncMock(return_value="streamed result")
        return server

    @pytest.fixture
    def adapter(self, mock_server):
        return A2AAdapter(mock_server, base_url="https://stream.example.com")

    @pytest.mark.asyncio
    async def test_stream_task_yields_submitted_working_completed(self, adapter):
        events = []
        async for chunk in adapter.stream_task("t1", "echo", {"message": "hi"}):
            events.append(chunk)

        states = []
        for chunk in events:
            if chunk.startswith("data:") and "[DONE]" not in chunk:
                payload = json.loads(chunk[len("data:"):])
                states.append(payload["status"]["state"])

        assert states == ["submitted", "working", "completed"]

    @pytest.mark.asyncio
    async def test_stream_task_ends_with_done(self, adapter):
        events = []
        async for chunk in adapter.stream_task("t1", "echo", {"message": "hi"}):
            events.append(chunk)
        assert events[-1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_stream_task_failed_on_exception(self, adapter, mock_server):
        mock_server.call_tool.side_effect = RuntimeError("oops")
        events = []
        async for chunk in adapter.stream_task("t1", "echo", {}):
            events.append(chunk)

        states = [
            json.loads(c[len("data:"):])["status"]["state"]
            for c in events
            if c.startswith("data:") and "[DONE]" not in c
        ]
        assert states[-1] == "failed"

    @pytest.mark.asyncio
    async def test_stream_task_records_in_tasks_dict(self, adapter):
        async for _ in adapter.stream_task("t-stream", "echo", {}):
            pass
        final = adapter.get_task_status("t-stream")
        assert final is not None
        assert final.status == "completed"


class TestA2AAdapterWebhook:
    @pytest.fixture
    def mock_server(self):
        server = MagicMock()
        server.name = "webhook-server"
        server.list_tools = AsyncMock(return_value=[])
        server.call_tool = AsyncMock(return_value="ok")
        return server

    @pytest.fixture
    def adapter(self, mock_server):
        return A2AAdapter(mock_server)

    @pytest.mark.asyncio
    async def test_webhook_posted_on_each_state(self, adapter):
        posted = []

        async def fake_post(url, *, json, headers):
            posted.append(json["status"]["state"])
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=fake_post)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await adapter.handle_task("t1", "tool", {}, webhook_url="https://cb.example.com/hook")

        assert "submitted" in posted
        assert "working" in posted
        assert "completed" in posted

    @pytest.mark.asyncio
    async def test_webhook_failure_does_not_raise(self, adapter):
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("network error"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            status = await adapter.handle_task("t1", "tool", {}, webhook_url="https://cb.example.com")
        assert status.status == "completed"

    @pytest.mark.asyncio
    async def test_no_webhook_skips_notify(self, adapter):
        with patch("httpx.AsyncClient") as mock_cls:
            await adapter.handle_task("t1", "tool", {})
        mock_cls.assert_not_called()
