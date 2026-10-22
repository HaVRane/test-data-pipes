"""Config-driven sammanslagning av Excel-flikar."""

from excel_merge.config import PipelineConfig, SourceConfig, load_config
from excel_merge.pipeline import run_pipeline

__all__ = ["PipelineConfig", "SourceConfig", "load_config", "run_pipeline"]
