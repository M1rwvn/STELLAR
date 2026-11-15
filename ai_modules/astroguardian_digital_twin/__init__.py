"""AstroGuardian Digital Twin (AI Member 1) - personal baselines for SYNTHETIC astronaut data."""
from .baseline import build_baselines, compute_astronaut_baseline, load_config
from .data_cleaning import clean_wearable_data
from .data_generator import generate_dataset
from .deviation import compute_deviation, compute_deviation_detailed
from .explain import explain_deviation
from .feature_engineering import engineer_features
from .online import compute_online_reference, online_features
from .profiles import UnknownAstronautError, get_baseline, run_pipeline

__version__ = "1.1.0"
__all__ = ["get_baseline", "compute_deviation", "compute_deviation_detailed", "UnknownAstronautError",
           "online_features", "explain_deviation", "compute_online_reference",
           "generate_dataset", "clean_wearable_data", "engineer_features", "build_baselines",
           "compute_astronaut_baseline", "load_config", "run_pipeline", "__version__"]
