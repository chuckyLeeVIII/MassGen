from concurrent.futures import ThreadPoolExecutor

import pytest

from evals.calibration import runner


@pytest.mark.asyncio
async def test_run_matrix_aggregates_trials(monkeypatch):
    """run_matrix should preserve per-cell trial mapping and metrics."""

    def fake_executor_factory(max_workers: int):
        return ThreadPoolExecutor(max_workers=max_workers)

    def fake_worker(model_config, scenario, threshold, cap, with_adjustments, verbose=False):
        del scenario, with_adjustments, verbose
        new_answer_count = 1 if threshold <= 10 else 3
        return runner.TrialResult(
            success=True,
            new_answer_count=new_answer_count,
            cap=cap,
            effort_ratio=new_answer_count / cap,
            has_final_answer=True,
            duration_seconds=0.01,
            log_directory=f"/tmp/{model_config['model']}/{threshold}",
        )

    monkeypatch.setattr(runner, "_create_trial_executor", fake_executor_factory)
    monkeypatch.setattr(runner, "_run_trial_worker", fake_worker)

    cells = [
        {
            "model_key": "m1",
            "model_label": "Model 1",
            "model_config": {"model": "model-a"},
            "scenario": {"name": "scenario-a", "prompt": "prompt-a"},
            "threshold": 10,
            "cap": 5,
        },
        {
            "model_key": "m1",
            "model_label": "Model 1",
            "model_config": {"model": "model-a"},
            "scenario": {"name": "scenario-a", "prompt": "prompt-a"},
            "threshold": 30,
            "cap": 5,
        },
    ]

    results = await runner.run_matrix(
        cells=cells,
        trials_per_cell=2,
        concurrency=2,
        with_adjustments=False,
    )

    assert len(results) == 2
    assert all(len(cell.trials) == 2 for cell in results)
    assert all(trial.success for cell in results for trial in cell.trials)

    low_threshold = next(cell for cell in results if cell.threshold == 10)
    high_threshold = next(cell for cell in results if cell.threshold == 30)

    assert low_threshold.metrics is not None
    assert low_threshold.metrics.effort_ratio_mean == pytest.approx(0.2)
    assert low_threshold.metrics.one_answer_rate == pytest.approx(1.0)
    assert low_threshold.metrics.completion_rate == pytest.approx(1.0)
    assert low_threshold.metrics.trial_count == 2

    assert high_threshold.metrics is not None
    assert high_threshold.metrics.effort_ratio_mean == pytest.approx(0.6)
    assert high_threshold.metrics.one_answer_rate == pytest.approx(0.0)
    assert high_threshold.metrics.completion_rate == pytest.approx(1.0)
    assert high_threshold.metrics.trial_count == 2


@pytest.mark.asyncio
async def test_run_matrix_converts_worker_exceptions_to_failed_trials(monkeypatch):
    """Worker exceptions should become failed TrialResult entries, not crash the matrix."""

    def fake_executor_factory(max_workers: int):
        return ThreadPoolExecutor(max_workers=max_workers)

    def fake_worker(model_config, scenario, threshold, cap, with_adjustments, verbose=False):
        del model_config, scenario, with_adjustments, verbose
        if threshold == 20:
            raise RuntimeError("worker exploded")
        return runner.TrialResult(
            success=True,
            new_answer_count=2,
            cap=cap,
            effort_ratio=2 / cap,
            has_final_answer=True,
            duration_seconds=0.01,
            log_directory="/tmp/success",
        )

    monkeypatch.setattr(runner, "_create_trial_executor", fake_executor_factory)
    monkeypatch.setattr(runner, "_run_trial_worker", fake_worker)

    cells = [
        {
            "model_key": "m1",
            "model_label": "Model 1",
            "model_config": {"model": "model-a"},
            "scenario": {"name": "scenario-a", "prompt": "prompt-a"},
            "threshold": 20,
            "cap": 4,
        },
        {
            "model_key": "m1",
            "model_label": "Model 1",
            "model_config": {"model": "model-a"},
            "scenario": {"name": "scenario-a", "prompt": "prompt-a"},
            "threshold": 10,
            "cap": 4,
        },
    ]

    results = await runner.run_matrix(
        cells=cells,
        trials_per_cell=1,
        concurrency=2,
        with_adjustments=False,
    )

    failed_cell = next(cell for cell in results if cell.threshold == 20)
    passed_cell = next(cell for cell in results if cell.threshold == 10)

    assert len(failed_cell.trials) == 1
    assert failed_cell.trials[0].success is False
    assert failed_cell.trials[0].error == "RuntimeError: worker exploded"
    assert failed_cell.metrics is not None
    assert failed_cell.metrics.completion_rate == pytest.approx(0.0)

    assert len(passed_cell.trials) == 1
    assert passed_cell.trials[0].success is True
    assert passed_cell.metrics is not None
    assert passed_cell.metrics.completion_rate == pytest.approx(1.0)
