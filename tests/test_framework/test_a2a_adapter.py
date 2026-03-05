"""Unit tests for A2AAdapter — agent card, task handling, status tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
