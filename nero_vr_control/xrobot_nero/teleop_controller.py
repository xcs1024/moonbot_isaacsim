from __future__ import annotations

from .config import TeleopConfig


class NeroDualTeleopController:
    """Lazy wrapper around the XRoboToolkit hardware controller.

    XRoboToolkit and Placo are heavy optional runtime dependencies. Keeping the
    import lazy lets config parsing, safety tests, and pyAgxArm adapter tests run
    on a development machine before the full robot stack is installed.
    """

    def __new__(
        cls,
        config: TeleopConfig,
        *,
        dry_run: bool,
        visualize_placo: bool = False,
        enable_log_data: bool = True,
        dataset_capture: bool = False,
        dataset_format: str | None = None,
        dataset_root: str | None = None,
        dataset_repo_id: str | None = None,
        dataset_task: str | None = None,
        dataset_fps: int | None = None,
        dataset_image_writer_threads: int | None = None,
        dataset_image_writer_processes: int | None = None,
    ):
        from ._xr_hardware import XRNeroDualTeleopController

        return XRNeroDualTeleopController(
            config=config,
            dry_run=dry_run,
            visualize_placo=visualize_placo,
            enable_log_data=enable_log_data,
            dataset_capture=dataset_capture,
            dataset_format=dataset_format,
            dataset_root=dataset_root,
            dataset_repo_id=dataset_repo_id,
            dataset_task=dataset_task,
            dataset_fps=dataset_fps,
            dataset_image_writer_threads=dataset_image_writer_threads,
            dataset_image_writer_processes=dataset_image_writer_processes,
        )
