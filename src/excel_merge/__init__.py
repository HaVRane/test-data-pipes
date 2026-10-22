"""Config-driven sammanslagning av Excel-flikar."""

from excel_merge.engine import BuildResult, execute_build
from excel_merge.relations import RelationSpec, load_relation_spec

__all__ = ["BuildResult", "RelationSpec", "execute_build", "load_relation_spec"]
