"""
Tests for generate_media batch/parallel functionality.

Tests cover:
1. Batch mode validation and return formats
2. Parallel execution with asyncio.gather
3. agent_cwd injection across backends
4. Error handling in batch mode
"""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    GenerationResult,
    MediaType,
)
from massgen.tool._multimodal_tools.generation.generate_media import generate_media


class TestGenerateMediaBatchUnit:
    """Unit tests for batch generation - validation and return formats."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files with CONTEXT.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Resolve to handle macOS /var -> /private/var symlink
            tmp_path = Path(tmpdir).resolve()
            # Create required CONTEXT.md for generate_media
            (tmp_path / "CONTEXT.md").write_text("Test context for generate_media unit tests.")
            yield tmp_path

    @pytest.fixture
    def mock_generate_image(self):
        """Mock the generate_image function to avoid API calls."""

        async def _mock_generate(config: GenerationConfig) -> GenerationResult:
            # Create a dummy file
            config.output_path.parent.mkdir(parents=True, exist_ok=True)
            config.output_path.write_bytes(b"fake image data")
            return GenerationResult(
                success=True,
                output_path=config.output_path,
                media_type=MediaType.IMAGE,
                backend_name="openai",
                model_used="gpt-image-mock",
                file_size_bytes=15,
            )

        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.generate_image",
            side_effect=_mock_generate,
        ):
            yield

    @pytest.fixture
    def mock_backend_selection(self):
        """Mock backend selection to always return openai."""
        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("openai", "gpt-image-mock"),
        ):
            yield

    # --- Validation Tests ---

    @pytest.mark.asyncio
    async def test_error_when_both_prompt_and_prompts_provided(self, temp_dir):
        """Should error when both prompt and prompts are provided."""
        result = await generate_media(
            prompt="single prompt",
            prompts=["prompt1", "prompt2"],
            mode="image",
            agent_cwd=str(temp_dir),
        )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is False
        assert "either 'prompt' or 'prompts'" in result_data["error"].lower()

    @pytest.mark.asyncio
    async def test_error_when_neither_prompt_nor_prompts_provided(self, temp_dir):
        """Should error when neither prompt nor prompts is provided."""
        result = await generate_media(
            mode="image",
            agent_cwd=str(temp_dir),
        )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is False
        assert "must provide" in result_data["error"].lower()

    @pytest.mark.asyncio
    async def test_error_invalid_mode(self, temp_dir):
        """Should error with invalid mode."""
        result = await generate_media(
            prompt="test",
            mode="invalid_mode",
            agent_cwd=str(temp_dir),
        )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is False
        assert "invalid mode" in result_data["error"].lower()

    # --- Return Format Tests ---

    @pytest.mark.asyncio
    async def test_single_prompt_returns_flat_json(
        self,
        temp_dir,
        mock_generate_image,
        mock_backend_selection,
    ):
        """Single prompt should return flat JSON (backwards compatible)."""
        result = await generate_media(
            prompt="a cat in space",
            mode="image",
            agent_cwd=str(temp_dir),
            allowed_paths=[str(temp_dir)],
        )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is True
        assert "batch" not in result_data  # No batch key for single
        assert "file_path" in result_data
        assert "results" not in result_data  # No results array

    @pytest.mark.asyncio
    async def test_batch_prompts_returns_array_json(
        self,
        temp_dir,
        mock_generate_image,
        mock_backend_selection,
    ):
        """Batch prompts should return JSON with results array."""
        prompts = ["cat in space", "dog on moon", "bird in forest"]
        result = await generate_media(
            prompts=prompts,
            mode="image",
            agent_cwd=str(temp_dir),
            allowed_paths=[str(temp_dir)],
        )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is True
        assert result_data["batch"] is True
        assert result_data["total"] == 3
        assert result_data["succeeded"] == 3
        assert result_data["failed"] == 0
        assert len(result_data["results"]) == 3

        # Each result should have expected fields
        for i, item in enumerate(result_data["results"]):
            assert item["prompt"] == prompts[i]
            assert item["success"] is True
            assert "file_path" in item

    # --- Filename Tests ---

    @pytest.mark.asyncio
    async def test_batch_filenames_include_index(
        self,
        temp_dir,
        mock_generate_image,
        mock_backend_selection,
    ):
        """Batch mode should include index in filenames."""
        result = await generate_media(
            prompts=["prompt one", "prompt two"],
            mode="image",
            agent_cwd=str(temp_dir),
            allowed_paths=[str(temp_dir)],
        )

        result_data = json.loads(result.output_blocks[0].data)
        filenames = [r["filename"] for r in result_data["results"]]

        # Check indices are present
        assert "_00_" in filenames[0]
        assert "_01_" in filenames[1]

    @pytest.mark.asyncio
    async def test_single_filename_no_index(
        self,
        temp_dir,
        mock_generate_image,
        mock_backend_selection,
    ):
        """Single prompt should not have index in filename."""
        result = await generate_media(
            prompt="test prompt",
            mode="image",
            agent_cwd=str(temp_dir),
            allowed_paths=[str(temp_dir)],
        )

        result_data = json.loads(result.output_blocks[0].data)
        filename = result_data["filename"]

        # Should not have index pattern like _00_ or _01_
        assert "_00_" not in filename
        assert "_01_" not in filename

    # --- Path Resolution Tests ---

    @pytest.mark.asyncio
    async def test_relative_storage_path_resolves_to_agent_cwd(
        self,
        temp_dir,
        mock_generate_image,
        mock_backend_selection,
    ):
        """Relative storage_path should resolve relative to agent_cwd."""
        result = await generate_media(
            prompt="test",
            mode="image",
            storage_path="images",
            agent_cwd=str(temp_dir),
            allowed_paths=[str(temp_dir)],
        )

        result_data = json.loads(result.output_blocks[0].data)
        file_path = result_data["file_path"]

        # Should be inside temp_dir/images/
        assert str(temp_dir) in file_path
        assert "/images/" in file_path

    @pytest.mark.asyncio
    async def test_absolute_storage_path_used_directly(
        self,
        temp_dir,
        mock_generate_image,
        mock_backend_selection,
    ):
        """Absolute storage_path should be used directly."""
        abs_path = temp_dir / "absolute_output"
        abs_path.mkdir()

        result = await generate_media(
            prompt="test",
            mode="image",
            storage_path=str(abs_path),
            agent_cwd=str(temp_dir),
            allowed_paths=[str(temp_dir)],
        )

        result_data = json.loads(result.output_blocks[0].data)
        file_path = result_data["file_path"]

        assert str(abs_path) in file_path


class TestGenerateMediaBatchParallelism:
    """Tests for parallel execution behavior."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir).resolve()
            (tmp_path / "CONTEXT.md").write_text("Test context for parallelism tests.")
            yield tmp_path

    @pytest.fixture
    def mock_backend_selection(self):
        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("openai", "gpt-image-mock"),
        ):
            yield

    @pytest.mark.asyncio
    async def test_batch_executes_in_parallel(self, temp_dir, mock_backend_selection):
        """Batch mode should execute prompts in parallel, not sequentially."""
        call_times = []

        async def _mock_generate(config: GenerationConfig) -> GenerationResult:
            call_times.append(time.time())
            await asyncio.sleep(0.1)  # Simulate API delay
            config.output_path.parent.mkdir(parents=True, exist_ok=True)
            config.output_path.write_bytes(b"fake")
            return GenerationResult(
                success=True,
                output_path=config.output_path,
                backend_name="openai",
                model_used="mock",
                file_size_bytes=4,
            )

        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.generate_image",
            side_effect=_mock_generate,
        ):
            start = time.time()
            result = await generate_media(
                prompts=["p1", "p2", "p3", "p4"],
                mode="image",
                max_concurrent=4,
                agent_cwd=str(temp_dir),
                allowed_paths=[str(temp_dir)],
            )
            elapsed = time.time() - start

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is True
        assert result_data["total"] == 4

        # If sequential, would take ~0.4s (4 * 0.1s)
        # If parallel, should take ~0.1s
        # Allow some margin for test overhead
        assert elapsed < 0.3, f"Expected parallel execution, took {elapsed:.2f}s"

        # All calls should start within a short window
        if len(call_times) >= 2:
            time_spread = max(call_times) - min(call_times)
            assert time_spread < 0.05, f"Calls not parallel, spread: {time_spread:.3f}s"

    @pytest.mark.asyncio
    async def test_max_concurrent_limits_parallelism(
        self,
        temp_dir,
        mock_backend_selection,
    ):
        """max_concurrent should limit how many run at once."""
        concurrent_count = 0
        max_observed = 0
        lock = asyncio.Lock()

        async def _mock_generate(config: GenerationConfig) -> GenerationResult:
            nonlocal concurrent_count, max_observed
            async with lock:
                concurrent_count += 1
                max_observed = max(max_observed, concurrent_count)

            await asyncio.sleep(0.1)

            async with lock:
                concurrent_count -= 1

            config.output_path.parent.mkdir(parents=True, exist_ok=True)
            config.output_path.write_bytes(b"fake")
            return GenerationResult(
                success=True,
                output_path=config.output_path,
                backend_name="openai",
                model_used="mock",
                file_size_bytes=4,
            )

        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.generate_image",
            side_effect=_mock_generate,
        ):
            result = await generate_media(
                prompts=[f"prompt{i}" for i in range(6)],
                mode="image",
                max_concurrent=2,  # Limit to 2 concurrent
                agent_cwd=str(temp_dir),
                allowed_paths=[str(temp_dir)],
            )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is True
        assert result_data["total"] == 6

        # Should never exceed max_concurrent
        assert max_observed <= 2, f"Exceeded max_concurrent: observed {max_observed}"


class TestGenerateMediaBatchErrorHandling:
    """Tests for error handling in batch mode."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir).resolve()
            (tmp_path / "CONTEXT.md").write_text("Test context for error handling tests.")
            yield tmp_path

    @pytest.fixture
    def mock_backend_selection(self):
        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("openai", "gpt-image-mock"),
        ):
            yield

    @pytest.mark.asyncio
    async def test_partial_failure_returns_mixed_results(
        self,
        temp_dir,
        mock_backend_selection,
    ):
        """Some failures should not fail entire batch."""
        call_count = 0

        async def _mock_generate(config: GenerationConfig) -> GenerationResult:
            nonlocal call_count
            call_count += 1

            # Fail every other call
            if call_count % 2 == 0:
                return GenerationResult(
                    success=False,
                    backend_name="openai",
                    error="Simulated failure",
                )

            config.output_path.parent.mkdir(parents=True, exist_ok=True)
            config.output_path.write_bytes(b"fake")
            return GenerationResult(
                success=True,
                output_path=config.output_path,
                backend_name="openai",
                model_used="mock",
                file_size_bytes=4,
            )

        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.generate_image",
            side_effect=_mock_generate,
        ):
            result = await generate_media(
                prompts=["p1", "p2", "p3", "p4"],
                mode="image",
                agent_cwd=str(temp_dir),
                allowed_paths=[str(temp_dir)],
            )

        result_data = json.loads(result.output_blocks[0].data)

        # Batch should still succeed (partial success)
        assert result_data["success"] is True
        assert result_data["total"] == 4
        assert result_data["succeeded"] == 2
        assert result_data["failed"] == 2

        # Check individual results
        successes = [r for r in result_data["results"] if r["success"]]
        failures = [r for r in result_data["results"] if not r["success"]]
        assert len(successes) == 2
        assert len(failures) == 2

    @pytest.mark.asyncio
    async def test_all_failures_still_returns_batch_format(
        self,
        temp_dir,
        mock_backend_selection,
    ):
        """All failures should return batch format with success=False."""

        async def _mock_generate(config: GenerationConfig) -> GenerationResult:
            return GenerationResult(
                success=False,
                backend_name="openai",
                error="All fail",
            )

        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.generate_image",
            side_effect=_mock_generate,
        ):
            result = await generate_media(
                prompts=["p1", "p2", "p3"],
                mode="image",
                agent_cwd=str(temp_dir),
                allowed_paths=[str(temp_dir)],
            )

        result_data = json.loads(result.output_blocks[0].data)

        assert result_data["success"] is False  # Overall failure
        assert result_data["batch"] is True
        assert result_data["total"] == 3
        assert result_data["succeeded"] == 0
        assert result_data["failed"] == 3


class TestAgentCwdInjection:
    """Tests for agent_cwd context injection across backends."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir).resolve()
            (tmp_path / "CONTEXT.md").write_text("Test context for agent_cwd injection tests.")
            yield tmp_path

    @pytest.mark.asyncio
    async def test_agent_cwd_defaults_to_cwd_when_not_provided(self, temp_dir):
        """When agent_cwd is not provided, should error about missing CONTEXT.md."""
        # Without agent_cwd, we can't find CONTEXT.md, so we expect the error
        with patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=(None, None),  # No backend = error, but no crash
        ):
            result = await generate_media(
                prompt="test",
                mode="image",
                # No agent_cwd - will fail because no CONTEXT.md found
            )

        result_data = json.loads(result.output_blocks[0].data)
        # Should fail due to missing CONTEXT.md when no agent_cwd provided
        assert "CONTEXT.md not found" in result_data.get("error", "")


@pytest.mark.integration
class TestGenerateMediaRealAPI:
    """Real API tests - requires API keys."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir).resolve()
            (tmp_path / "CONTEXT.md").write_text("Test context for real API integration tests.")
            yield tmp_path

    @pytest.mark.asyncio
    async def test_real_single_image_generation(self, temp_dir):
        """Test single image generation with real API."""
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        result = await generate_media(
            prompt="A simple red circle on white background",
            mode="image",
            agent_cwd=str(temp_dir),
            allowed_paths=[str(temp_dir)],
        )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is True
        assert "file_path" in result_data

        # Verify file was created
        file_path = Path(result_data["file_path"])
        assert file_path.exists()
        assert file_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_real_batch_image_generation(self, temp_dir):
        """Test batch image generation with real API."""
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        prompts = [
            "A red circle",
            "A blue square",
        ]

        start = time.time()
        result = await generate_media(
            prompts=prompts,
            mode="image",
            max_concurrent=2,
            agent_cwd=str(temp_dir),
            allowed_paths=[str(temp_dir)],
        )
        elapsed = time.time() - start

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is True
        assert result_data["batch"] is True
        assert result_data["total"] == 2
        assert result_data["succeeded"] == 2

        # Verify files were created
        for item in result_data["results"]:
            file_path = Path(item["file_path"])
            assert file_path.exists()

        # Log timing for manual verification of parallelism
        print(f"\nBatch generation of 2 images took {elapsed:.2f}s")
