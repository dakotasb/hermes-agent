"""
Tests for the Kanban Boards API endpoints on the API server adapter.

Boards are Hermes's native projects primitive — each board has its own
kanban.db, workspaces directory, and dispatcher loop.  These tests cover:

- CRUD for boards (list, create, get, patch, delete)
- Task CRUD per board (list, create, patch status/assignee/priority)
- Input validation (missing slug/title, invalid status, running-task conflict)
- Auth enforcement (401 when API_SERVER_KEY is set)
- Query-param filtering (assignee, status, include_archived, limit)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter, cors_middleware

_MOD = "gateway.platforms.api_server"
_KB  = "hermes_cli.kanban_db"


# ---------------------------------------------------------------------------
# Shared test data and helpers
# ---------------------------------------------------------------------------

SAMPLE_BOARD_META = {
    "slug":          "project-alpha",
    "name":          "Project Alpha",
    "description":   "Main project board",
    "icon":          "🚀",
    "color":         "#6CD9BA",
    "created_at":    1_700_000_000,
    "archived":      False,
    "default_workdir": None,
    "db_path":       "/home/user/.hermes/kanban/boards/project-alpha/kanban.db",
}

VALID_STATUSES = {
    "triage", "todo", "scheduled", "ready",
    "running", "blocked", "review", "done", "archived",
}


@dataclass
class _FakeTask:
    """Minimal stand-in for kanban_db.Task used in API response tests."""
    id:                   str = "t_deadbeef"
    title:                str = "Write tests"
    body:                 Optional[str] = None
    assignee:             Optional[str] = "forge"
    status:               str = "ready"
    priority:             int = 0
    tenant:               Optional[str] = None
    workspace_kind:       str = "scratch"
    workspace_path:       Optional[str] = None
    branch_name:          Optional[str] = None
    created_by:           Optional[str] = "api_server"
    created_at:           int = 1_700_000_000
    started_at:           Optional[int] = None
    completed_at:         Optional[int] = None
    result:               Optional[str] = None
    skills:               Optional[list] = None
    max_retries:          Optional[int] = None
    session_id:           Optional[str] = None
    consecutive_failures: int = 0
    last_failure_error:   Optional[str] = None


class _FakeConn:
    """Minimal sqlite3.Connection stand-in: captures execute calls, has close()."""

    def __init__(self):
        self.executed: list[tuple] = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        row = MagicMock()
        row.fetchone.return_value = (5,)
        return row

    def commit(self):
        pass

    def close(self):
        pass


@contextlib.contextmanager
def _noop_write_txn(conn):
    """Drop-in for kanban_db.write_txn that does nothing special."""
    yield conn


def _make_adapter(api_key: str = "") -> APIServerAdapter:
    extra = {"key": api_key} if api_key else {}
    return APIServerAdapter(PlatformConfig(enabled=True, extra=extra))


def _create_app(adapter: APIServerAdapter) -> web.Application:
    """Register only the board routes under test."""
    app = web.Application(middlewares=[cors_middleware])
    app["api_server_adapter"] = adapter
    app.router.add_get("/api/boards",                              adapter._handle_list_boards)
    app.router.add_post("/api/boards",                             adapter._handle_create_board)
    app.router.add_get("/api/boards/{slug}",                       adapter._handle_get_board)
    app.router.add_patch("/api/boards/{slug}",                     adapter._handle_patch_board)
    app.router.add_delete("/api/boards/{slug}",                    adapter._handle_delete_board)
    app.router.add_get("/api/boards/{slug}/tasks",                 adapter._handle_list_board_tasks)
    app.router.add_post("/api/boards/{slug}/tasks",                adapter._handle_create_board_task)
    app.router.add_patch("/api/boards/{slug}/tasks/{task_id}",     adapter._handle_patch_board_task)
    return app


@pytest.fixture
def adapter():
    return _make_adapter()


@pytest.fixture
def auth_adapter():
    return _make_adapter(api_key="sk-supersecret")


# ---------------------------------------------------------------------------
# GET /api/boards
# ---------------------------------------------------------------------------

class TestListBoards:
    @pytest.mark.asyncio
    async def test_returns_board_list(self, adapter):
        """GET /api/boards returns serialized board list without db_path."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.list_boards", return_value=[SAMPLE_BOARD_META]):
                resp = await cli.get("/api/boards")
                assert resp.status == 200
                data = await resp.json()
        assert "boards" in data
        assert len(data["boards"]) == 1
        board = data["boards"][0]
        assert board["slug"] == "project-alpha"
        assert board["name"] == "Project Alpha"
        assert "db_path" not in board

    @pytest.mark.asyncio
    async def test_include_archived_param(self, adapter):
        """GET /api/boards?include_archived=true passes flag to list_boards."""
        app = _create_app(adapter)
        mock_list = MagicMock(return_value=[])
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.list_boards", mock_list):
                resp = await cli.get("/api/boards?include_archived=true")
                assert resp.status == 200
        mock_list.assert_called_once_with(include_archived=True)

    @pytest.mark.asyncio
    async def test_default_excludes_archived(self, adapter):
        """GET /api/boards without param passes include_archived=False."""
        app = _create_app(adapter)
        mock_list = MagicMock(return_value=[])
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.list_boards", mock_list):
                resp = await cli.get("/api/boards")
                assert resp.status == 200
        mock_list.assert_called_once_with(include_archived=False)

    @pytest.mark.asyncio
    async def test_500_on_exception(self, adapter):
        """GET /api/boards returns 500 when kanban_db raises."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.list_boards", side_effect=OSError("disk full")):
                resp = await cli.get("/api/boards")
                assert resp.status == 500


# ---------------------------------------------------------------------------
# POST /api/boards
# ---------------------------------------------------------------------------

class TestCreateBoard:
    @pytest.mark.asyncio
    async def test_create_board(self, adapter):
        """POST /api/boards with valid slug returns 201 with board."""
        app = _create_app(adapter)
        mock_create = MagicMock(return_value=SAMPLE_BOARD_META)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.create_board", mock_create):
                resp = await cli.post("/api/boards", json={
                    "slug":        "project-alpha",
                    "name":        "Project Alpha",
                    "description": "Main project board",
                    "color":       "#6CD9BA",
                    "icon":        "🚀",
                })
                assert resp.status == 201
                data = await resp.json()
        assert data["board"]["slug"] == "project-alpha"
        mock_create.assert_called_once_with(
            "project-alpha",
            name="Project Alpha",
            description="Main project board",
            icon="🚀",
            color="#6CD9BA",
            default_workdir=None,
        )

    @pytest.mark.asyncio
    async def test_missing_slug_returns_400(self, adapter):
        """POST /api/boards without slug returns 400."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post("/api/boards", json={"name": "No Slug"})
            assert resp.status == 400
            data = await resp.json()
        assert "slug" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_slug_returns_400(self, adapter):
        """POST /api/boards with invalid slug propagates ValueError as 400."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.create_board", side_effect=ValueError("bad slug")):
                resp = await cli.post("/api/boards", json={"slug": "INVALID SLUG!"})
                assert resp.status == 400

    @pytest.mark.asyncio
    async def test_idempotent_on_existing_slug(self, adapter):
        """POST /api/boards with existing slug returns 201 (idempotent)."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.create_board", return_value=SAMPLE_BOARD_META):
                resp = await cli.post("/api/boards", json={"slug": "project-alpha"})
                assert resp.status == 201


# ---------------------------------------------------------------------------
# GET /api/boards/{slug}
# ---------------------------------------------------------------------------

class TestGetBoard:
    @pytest.mark.asyncio
    async def test_returns_metadata_and_counts(self, adapter):
        """GET /api/boards/{slug} returns board metadata plus task_counts."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.read_board_metadata", return_value=SAMPLE_BOARD_META), \
                 patch(f"{_KB}.connect", return_value=fake_conn):
                resp = await cli.get("/api/boards/project-alpha")
                assert resp.status == 200
                data = await resp.json()
        assert data["board"]["slug"] == "project-alpha"
        assert "task_counts" in data["board"]

    @pytest.mark.asyncio
    async def test_task_counts_best_effort(self, adapter):
        """GET /api/boards/{slug} still returns metadata when task count fails."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.read_board_metadata", return_value=SAMPLE_BOARD_META), \
                 patch(f"{_KB}.connect", side_effect=Exception("db locked")):
                resp = await cli.get("/api/boards/project-alpha")
                assert resp.status == 200
                data = await resp.json()
        assert data["board"]["slug"] == "project-alpha"
        assert data["board"]["task_counts"] == {}


# ---------------------------------------------------------------------------
# PATCH /api/boards/{slug}
# ---------------------------------------------------------------------------

class TestPatchBoard:
    @pytest.mark.asyncio
    async def test_update_name(self, adapter):
        """PATCH /api/boards/{slug} updates board name."""
        app = _create_app(adapter)
        updated = {**SAMPLE_BOARD_META, "name": "Renamed Project"}
        mock_write = MagicMock(return_value=updated)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.write_board_metadata", mock_write):
                resp = await cli.patch(
                    "/api/boards/project-alpha",
                    json={"name": "Renamed Project"},
                )
                assert resp.status == 200
                data = await resp.json()
        assert data["board"]["name"] == "Renamed Project"
        mock_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_board_returns_400(self, adapter):
        """PATCH /api/boards/{slug} propagates ValueError as 400."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.write_board_metadata",
                       side_effect=ValueError("no such board")):
                resp = await cli.patch("/api/boards/nonexistent", json={"name": "X"})
                assert resp.status == 400


# ---------------------------------------------------------------------------
# DELETE /api/boards/{slug}
# ---------------------------------------------------------------------------

class TestDeleteBoard:
    @pytest.mark.asyncio
    async def test_archive_by_default(self, adapter):
        """DELETE /api/boards/{slug} archives (not hard-deletes) by default."""
        app = _create_app(adapter)
        mock_remove = MagicMock(return_value={"action": "archived"})
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.remove_board", mock_remove):
                resp = await cli.delete("/api/boards/project-alpha")
                assert resp.status == 200
        mock_remove.assert_called_once_with("project-alpha", archive=True)

    @pytest.mark.asyncio
    async def test_hard_delete_with_param(self, adapter):
        """DELETE /api/boards/{slug}?hard=true passes archive=False."""
        app = _create_app(adapter)
        mock_remove = MagicMock(return_value={"action": "deleted"})
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.remove_board", mock_remove):
                resp = await cli.delete("/api/boards/project-alpha?hard=true")
                assert resp.status == 200
        mock_remove.assert_called_once_with("project-alpha", archive=False)

    @pytest.mark.asyncio
    async def test_cannot_delete_default_board(self, adapter):
        """DELETE /api/boards/default returns 400 (ValueError from kanban_db)."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.remove_board",
                       side_effect=ValueError("the 'default' board cannot be removed")):
                resp = await cli.delete("/api/boards/default")
                assert resp.status == 400


# ---------------------------------------------------------------------------
# GET /api/boards/{slug}/tasks
# ---------------------------------------------------------------------------

class TestListBoardTasks:
    @pytest.mark.asyncio
    async def test_returns_task_list(self, adapter):
        """GET /api/boards/{slug}/tasks returns tasks tagged with board slug."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        task = _FakeTask()
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.list_tasks", return_value=[task]):
                resp = await cli.get("/api/boards/project-alpha/tasks")
                assert resp.status == 200
                data = await resp.json()
        assert data["board"] == "project-alpha"
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["id"] == "t_deadbeef"
        assert data["tasks"][0]["board"] == "project-alpha"

    @pytest.mark.asyncio
    async def test_filters_passed_to_list_tasks(self, adapter):
        """GET with query params forwards assignee/status/limit to list_tasks."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        mock_list = MagicMock(return_value=[])
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.list_tasks", mock_list):
                resp = await cli.get(
                    "/api/boards/project-alpha/tasks"
                    "?assignee=forge&status=running&limit=10"
                )
                assert resp.status == 200
        mock_list.assert_called_once_with(
            fake_conn,
            assignee="forge",
            status="running",
            include_archived=False,
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_invalid_status_returns_400(self, adapter):
        """GET with an invalid status value returns 400 via ValueError."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.list_tasks", side_effect=ValueError("bad status")):
                resp = await cli.get("/api/boards/project-alpha/tasks?status=bogus")
                assert resp.status == 400


# ---------------------------------------------------------------------------
# POST /api/boards/{slug}/tasks
# ---------------------------------------------------------------------------

class TestCreateBoardTask:
    @pytest.mark.asyncio
    async def test_create_task(self, adapter):
        """POST /api/boards/{slug}/tasks creates a task and returns 201."""
        app = _create_app(adapter)
        task = _FakeTask()
        fake_conn = _FakeConn()
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.create_task", return_value="t_deadbeef"), \
                 patch(f"{_KB}.get_task", return_value=task):
                resp = await cli.post("/api/boards/project-alpha/tasks", json={
                    "title":    "Write tests",
                    "assignee": "forge",
                    "priority": 1,
                })
                assert resp.status == 201
                data = await resp.json()
        assert data["task"]["id"] == "t_deadbeef"
        assert data["task"]["board"] == "project-alpha"

    @pytest.mark.asyncio
    async def test_missing_title_returns_400(self, adapter):
        """POST /api/boards/{slug}/tasks without title returns 400."""
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post("/api/boards/project-alpha/tasks", json={
                "assignee": "forge",
            })
            assert resp.status == 400
            data = await resp.json()
        assert "title" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_assignee_returns_400(self, adapter):
        """POST with invalid assignee propagates ValueError as 400."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.create_task", side_effect=ValueError("unknown profile")):
                resp = await cli.post("/api/boards/project-alpha/tasks", json={
                    "title": "Task", "assignee": "nonexistent-agent",
                })
                assert resp.status == 400


# ---------------------------------------------------------------------------
# PATCH /api/boards/{slug}/tasks/{task_id}
# ---------------------------------------------------------------------------

class TestPatchBoardTask:
    @pytest.mark.asyncio
    async def test_update_status(self, adapter):
        """PATCH task with new status writes update and returns task."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        task_before = _FakeTask()
        task_after  = _FakeTask(status="done")
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.get_task", side_effect=[task_before, task_after]), \
                 patch(f"{_KB}.write_txn", _noop_write_txn), \
                 patch(f"{_KB}.VALID_STATUSES", VALID_STATUSES):
                resp = await cli.patch(
                    "/api/boards/project-alpha/tasks/t_deadbeef",
                    json={"status": "done"},
                )
                assert resp.status == 200
                data = await resp.json()
        assert data["task"]["status"] == "done"

    @pytest.mark.asyncio
    async def test_invalid_status_returns_400(self, adapter):
        """PATCH task with invalid status returns 400."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        task = _FakeTask()
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.get_task", return_value=task), \
                 patch(f"{_KB}.VALID_STATUSES", VALID_STATUSES):
                resp = await cli.patch(
                    "/api/boards/project-alpha/tasks/t_deadbeef",
                    json={"status": "flying"},
                )
                assert resp.status == 400

    @pytest.mark.asyncio
    async def test_task_not_found_returns_404(self, adapter):
        """PATCH task that doesn't exist returns 404."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.get_task", return_value=None):
                resp = await cli.patch(
                    "/api/boards/project-alpha/tasks/t_nosuchid",
                    json={"status": "done"},
                )
                assert resp.status == 404

    @pytest.mark.asyncio
    async def test_assign_running_task_returns_409(self, adapter):
        """PATCH reassignment of a running task returns 409 (Conflict)."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        task = _FakeTask(status="running")
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.get_task", return_value=task), \
                 patch(f"{_KB}.VALID_STATUSES", VALID_STATUSES), \
                 patch(f"{_KB}.write_txn", _noop_write_txn), \
                 patch(f"{_KB}.assign_task",
                       side_effect=RuntimeError("cannot reassign: currently running")):
                resp = await cli.patch(
                    "/api/boards/project-alpha/tasks/t_deadbeef",
                    json={"assignee": "mason"},
                )
                assert resp.status == 409

    @pytest.mark.asyncio
    async def test_update_priority(self, adapter):
        """PATCH task with priority updates the priority field."""
        app = _create_app(adapter)
        fake_conn = _FakeConn()
        task_before = _FakeTask()
        task_after  = _FakeTask(priority=5)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.connect", return_value=fake_conn), \
                 patch(f"{_KB}.get_task", side_effect=[task_before, task_after]), \
                 patch(f"{_KB}.write_txn", _noop_write_txn), \
                 patch(f"{_KB}.VALID_STATUSES", VALID_STATUSES):
                resp = await cli.patch(
                    "/api/boards/project-alpha/tasks/t_deadbeef",
                    json={"priority": 5},
                )
                assert resp.status == 200
                data = await resp.json()
        assert data["task"]["priority"] == 5


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------

class TestBoardsAuth:
    @pytest.mark.asyncio
    async def test_list_boards_requires_auth(self, auth_adapter):
        """GET /api/boards returns 401 when API key is set and not provided."""
        app = _create_app(auth_adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get("/api/boards")
            assert resp.status == 401

    @pytest.mark.asyncio
    async def test_list_boards_with_valid_key(self, auth_adapter):
        """GET /api/boards succeeds with correct Bearer token."""
        app = _create_app(auth_adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch(f"{_KB}.list_boards", return_value=[]):
                resp = await cli.get(
                    "/api/boards",
                    headers={"Authorization": "Bearer sk-supersecret"},
                )
                assert resp.status == 200

    @pytest.mark.asyncio
    async def test_create_board_requires_auth(self, auth_adapter):
        """POST /api/boards returns 401 without auth."""
        app = _create_app(auth_adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post("/api/boards", json={"slug": "test"})
            assert resp.status == 401

    @pytest.mark.asyncio
    async def test_list_tasks_requires_auth(self, auth_adapter):
        """GET /api/boards/{slug}/tasks returns 401 without auth."""
        app = _create_app(auth_adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get("/api/boards/project-alpha/tasks")
            assert resp.status == 401
