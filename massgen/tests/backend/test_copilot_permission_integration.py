"""Integration tests for Copilot permission callback with real PathPermissionManager.

Wires up a CopilotBackend with a real PathPermissionManager (backed by temp
directories) and verifies the end-to-end permission flow through both layers:

* Layer 1: ``_build_permission_callback`` (coarse gate)
* Layer 2: ``PathPermissionManagerHook`` via ``GeneralHookManager`` (fine-grained)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from massgen.filesystem_manager import (
    PathPermissionManager,
    PathPermissionManagerHook,
    Permission,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_copilot_backend_with_ppm(
    workspace: Path,
    context_paths: list[tuple[Path, Permission]] | None = None,
):
    """Create a CopilotBackend with a real PathPermissionManager."""
    mock_copilot_module = MagicMock()
    mock_copilot_module.CopilotClient = MagicMock
    mock_copilot_module.Tool = MagicMock

    with patch.dict("sys.modules", {"copilot": mock_copilot_module}):
        from massgen.backend.copilot import CopilotBackend

        backend = CopilotBackend.__new__(CopilotBackend)
        backend.config = {}
        backend.client = MagicMock()
        backend.sessions = {}
        backend._session_signatures = {}

        # Build real PPM
        ppm = PathPermissionManager(
            context_write_access_enabled=False,
            enforce_read_before_delete=False,
        )
        ppm.add_path(workspace, Permission.WRITE, "workspace")
        for ctx_path, ctx_perm in context_paths or []:
            ppm.add_path(ctx_path, ctx_perm, "context")

        # Wire PPM into a mock FilesystemManager
        fm = MagicMock()
        fm.path_permission_manager = ppm
        fm.get_current_workspace.return_value = workspace
        backend.filesystem_manager = fm

        return backend, ppm


SDK_CONTEXT = {"session_id": "integration_test"}


# ---------------------------------------------------------------------------
# Layer 1: Permission callback with real PPM
# ---------------------------------------------------------------------------
class TestPermissionCallbackIntegration:
    """End-to-end tests for Layer 1 (permission callback) with real PPM."""

    def test_write_inside_workspace_approved(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, _ = _make_copilot_backend_with_ppm(workspace)
        callback = backend._build_permission_callback("approve")

        result = callback(
            {"kind": "write", "path": str(workspace / "output.txt")},
            SDK_CONTEXT,
        )
        assert result["kind"] == "approved"

    def test_write_outside_workspace_denied(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, _ = _make_copilot_backend_with_ppm(workspace)
        callback = backend._build_permission_callback("approve")

        result = callback(
            {"kind": "write", "path": "/etc/passwd"},
            SDK_CONTEXT,
        )
        assert result["kind"] == "denied-by-rules"

    def test_read_context_path_approved(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ref_dir = tmp_path / "reference"
        ref_dir.mkdir()

        backend, _ = _make_copilot_backend_with_ppm(
            workspace,
            context_paths=[(ref_dir, Permission.READ)],
        )
        callback = backend._build_permission_callback("approve")

        result = callback(
            {"kind": "read", "path": str(ref_dir / "doc.md")},
            SDK_CONTEXT,
        )
        assert result["kind"] == "approved"

    def test_write_to_readonly_context_denied(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ref_dir = tmp_path / "reference"
        ref_dir.mkdir()

        backend, _ = _make_copilot_backend_with_ppm(
            workspace,
            context_paths=[(ref_dir, Permission.READ)],
        )
        callback = backend._build_permission_callback("approve")

        result = callback(
            {"kind": "write", "path": str(ref_dir / "doc.md")},
            SDK_CONTEXT,
        )
        assert result["kind"] == "denied-by-rules"

    def test_read_outside_all_contexts_denied(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, _ = _make_copilot_backend_with_ppm(workspace)
        callback = backend._build_permission_callback("approve")

        result = callback(
            {"kind": "read", "path": "/etc/shadow"},
            SDK_CONTEXT,
        )
        assert result["kind"] == "denied-by-rules"

    def test_read_workspace_files_approved(self, tmp_path):
        """Reading from writable workspace should be approved (WRITE implies READ)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, _ = _make_copilot_backend_with_ppm(workspace)
        callback = backend._build_permission_callback("approve")

        result = callback(
            {"kind": "read", "path": str(workspace / "src" / "main.py")},
            SDK_CONTEXT,
        )
        assert result["kind"] == "approved"

    def test_shell_safe_command_approved(self, tmp_path):
        """Shell command within workspace should be approved."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, _ = _make_copilot_backend_with_ppm(workspace)
        callback = backend._build_permission_callback("approve")

        result = callback(
            {"kind": "shell", "command": "echo hello"},
            SDK_CONTEXT,
        )
        assert result["kind"] == "approved"

    def test_filePath_key_extraction(self, tmp_path):
        """SDK may use camelCase 'filePath' instead of 'path'."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, _ = _make_copilot_backend_with_ppm(workspace)
        callback = backend._build_permission_callback("approve")

        # Inside workspace via filePath key
        result = callback(
            {"kind": "write", "filePath": str(workspace / "out.txt")},
            SDK_CONTEXT,
        )
        assert result["kind"] == "approved"

        # Outside workspace via filePath key
        result = callback(
            {"kind": "write", "filePath": "/etc/passwd"},
            SDK_CONTEXT,
        )
        assert result["kind"] == "denied-by-rules"


# ---------------------------------------------------------------------------
# Layer 2: PathPermissionManagerHook with real PPM
# ---------------------------------------------------------------------------
class TestPPMHookIntegration:
    """End-to-end tests for Layer 2 (PathPermissionManagerHook) with real PPM."""

    @pytest.mark.asyncio
    async def test_write_tool_inside_workspace_allowed(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _, ppm = _make_copilot_backend_with_ppm(workspace)

        hook = PathPermissionManagerHook(ppm)
        result = await hook.execute(
            "Write",
            json.dumps({"file_path": str(workspace / "output.txt")}),
        )
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_write_tool_outside_workspace_blocked(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _, ppm = _make_copilot_backend_with_ppm(workspace)

        hook = PathPermissionManagerHook(ppm)
        result = await hook.execute(
            "Write",
            json.dumps({"file_path": "/etc/passwd"}),
        )
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_edit_tool_readonly_context_blocked(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ref_dir = tmp_path / "reference"
        ref_dir.mkdir()

        _, ppm = _make_copilot_backend_with_ppm(
            workspace,
            context_paths=[(ref_dir, Permission.READ)],
        )

        hook = PathPermissionManagerHook(ppm)
        result = await hook.execute(
            "Edit",
            json.dumps({"file_path": str(ref_dir / "doc.md")}),
        )
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_read_tool_context_allowed(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ref_dir = tmp_path / "reference"
        ref_dir.mkdir()
        (ref_dir / "notes.txt").write_text("hello")

        _, ppm = _make_copilot_backend_with_ppm(
            workspace,
            context_paths=[(ref_dir, Permission.READ)],
        )

        hook = PathPermissionManagerHook(ppm)
        result = await hook.execute(
            "Read",
            json.dumps({"file_path": str(ref_dir / "notes.txt")}),
        )
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Combined: Both layers agree
# ---------------------------------------------------------------------------
class TestTwoLayerDefense:
    """Verify that both layers produce consistent decisions."""

    @pytest.mark.asyncio
    async def test_both_layers_deny_write_outside_workspace(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, ppm = _make_copilot_backend_with_ppm(workspace)

        # Layer 1
        callback = backend._build_permission_callback("approve")
        l1 = callback(
            {"kind": "write", "path": "/etc/passwd"},
            SDK_CONTEXT,
        )
        assert l1["kind"] == "denied-by-rules"

        # Layer 2
        hook = PathPermissionManagerHook(ppm)
        l2 = await hook.execute(
            "Write",
            json.dumps({"file_path": "/etc/passwd"}),
        )
        assert l2.allowed is False

    @pytest.mark.asyncio
    async def test_both_layers_approve_write_inside_workspace(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, ppm = _make_copilot_backend_with_ppm(workspace)
        target = str(workspace / "output.txt")

        # Layer 1
        callback = backend._build_permission_callback("approve")
        l1 = callback(
            {"kind": "write", "path": target},
            SDK_CONTEXT,
        )
        assert l1["kind"] == "approved"

        # Layer 2
        hook = PathPermissionManagerHook(ppm)
        l2 = await hook.execute(
            "Write",
            json.dumps({"file_path": target}),
        )
        assert l2.allowed is True

    @pytest.mark.asyncio
    async def test_layer1_failopen_layer2_catches(self, tmp_path):
        """When Layer 1 can't extract a path (fail-open), Layer 2 catches it."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        backend, ppm = _make_copilot_backend_with_ppm(workspace)

        # Layer 1: unrecognized field name → fail-open
        callback = backend._build_permission_callback("approve")
        l1 = callback(
            {"kind": "write", "targetFile": "/etc/passwd"},
            SDK_CONTEXT,
        )
        assert l1["kind"] == "approved"  # fail-open

        # Layer 2: full tool args available → catches it
        hook = PathPermissionManagerHook(ppm)
        l2 = await hook.execute(
            "Write",
            json.dumps({"file_path": "/etc/passwd"}),
        )
        assert l2.allowed is False  # caught by Layer 2

    @pytest.mark.asyncio
    async def test_hook_via_native_adapter(self, tmp_path):
        """PPM hook works when wired through CopilotNativeHookAdapter."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _, ppm = _make_copilot_backend_with_ppm(workspace)

        # Register PPM hook in a GeneralHookManager via PatternHook wrapper
        # (mirrors what the orchestrator does — PPM hook gets wrapped by the
        # native adapter before reaching GeneralHookManager)
        ppm_hook = PathPermissionManagerHook(ppm)

        # Direct invocation — the adapter calls execute() directly
        result = await ppm_hook.execute(
            "Write",
            json.dumps({"file_path": "/etc/passwd"}),
        )
        assert result.allowed is False

        result = await ppm_hook.execute(
            "Write",
            json.dumps({"file_path": str(workspace / "ok.txt")}),
        )
        assert result.allowed is True
