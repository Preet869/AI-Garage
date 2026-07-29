"""Configuration loading, validation, and dataclass."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal

import yaml
from dotenv import load_dotenv


@dataclass
class FileSourceConfig:
    """File-based video source configuration."""
    path: str
    realtime: bool = False
    loop: bool = True


@dataclass
class RTSPSourceConfig:
    """RTSP stream source configuration."""
    main_url: str
    sub_url: str
    use_substream: bool = False


@dataclass
class SourceConfig:
    """Source configuration (file or RTSP)."""
    type: Literal["file", "rtsp"]
    file: FileSourceConfig
    rtsp: RTSPSourceConfig


@dataclass
class CaptureConfig:
    """Capture/processing configuration."""
    target_fps: int
    reconnect_initial_delay: int
    reconnect_max_delay: int
    watchdog_timeout: int


@dataclass
class DisplayConfig:
    """Display configuration."""
    enabled: bool
    window_name: str
    show_overlay: bool


@dataclass
class OutputConfig:
    """Output paths and settings."""
    snapshots_dir: str
    clips_dir: str
    clip_seconds: int


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str
    file: str
    format: str


@dataclass
class Config:
    """Complete application configuration."""
    source: SourceConfig
    capture: CaptureConfig
    display: DisplayConfig
    output: OutputConfig
    logging: LoggingConfig


def interpolate_env_vars(value: Any) -> Any:
    """Recursively interpolate ${VAR} placeholders with environment variables."""
    if isinstance(value, str):
        # Replace ${VAR} with environment variable value
        import re
        def replace_var(match):
            var_name = match.group(1)
            env_val = os.environ.get(var_name)
            if env_val is None:
                raise ValueError(
                    f"Environment variable '{var_name}' not found. "
                    f"Did you create .env and set {var_name}?"
                )
            return env_val
        
        return re.sub(r'\$\{([^}]+)\}', replace_var, value)
    elif isinstance(value, dict):
        return {k: interpolate_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [interpolate_env_vars(item) for item in value]
    return value


def validate_config(data: Dict[str, Any]) -> None:
    """
    Validate configuration structure and values.
    
    Args:
        data: Raw configuration dictionary
        
    Raises:
        ValueError: If configuration is invalid
    """
    # Check top-level keys
    required_top_level = {"source", "capture", "display", "output", "logging"}
    missing_keys = required_top_level - set(data.keys())
    if missing_keys:
        raise ValueError(
            f"Missing required top-level config keys: {missing_keys}\n"
            f"Expected: {required_top_level}"
        )
    
    # Validate source.type
    if "source" not in data:
        raise ValueError("Missing 'source' section in config")
    
    source_type = data["source"].get("type")
    allowed_types = {"file", "rtsp"}
    if source_type not in allowed_types:
        raise ValueError(
            f"Invalid source.type: '{source_type}'\n"
            f"Must be one of: {allowed_types}"
        )
    
    # Validate source has appropriate subsection
    if source_type == "file" and "file" not in data["source"]:
        raise ValueError("source.type is 'file' but no 'file' section found")
    if source_type == "rtsp" and "rtsp" not in data["source"]:
        raise ValueError("source.type is 'rtsp' but no 'rtsp' section found")
    
    # Validate capture config
    if "capture" not in data:
        raise ValueError("Missing 'capture' section in config")
    
    capture_required = {"target_fps", "reconnect_initial_delay", 
                       "reconnect_max_delay", "watchdog_timeout"}
    capture_missing = capture_required - set(data["capture"].keys())
    if capture_missing:
        raise ValueError(
            f"Missing required capture config keys: {capture_missing}\n"
            f"Expected: {capture_required}"
        )
    
    # Validate output config
    if "output" not in data:
        raise ValueError("Missing 'output' section in config")
    
    output_required = {"snapshots_dir", "clips_dir", "clip_seconds"}
    output_missing = output_required - set(data["output"].keys())
    if output_missing:
        raise ValueError(
            f"Missing required output config keys: {output_missing}\n"
            f"Expected: {output_required}"
        )


def create_output_directories(config: Config) -> None:
    """
    Create output directories if they don't exist.
    
    Args:
        config: Loaded configuration
    """
    dirs_to_create = [
        config.output.snapshots_dir,
        config.output.clips_dir,
        Path(config.logging.file).parent,  # Log directory
    ]
    
    for dir_path in dirs_to_create:
        Path(dir_path).mkdir(parents=True, exist_ok=True)


def _dict_to_dataclass(data: Dict[str, Any]) -> Config:
    """Convert raw config dictionary to dataclass."""
    source_data = data["source"]
    source_config = SourceConfig(
        type=source_data["type"],
        file=FileSourceConfig(**source_data.get("file", {})),
        rtsp=RTSPSourceConfig(**source_data.get("rtsp", {})),
    )
    
    config = Config(
        source=source_config,
        capture=CaptureConfig(**data["capture"]),
        display=DisplayConfig(**data["display"]),
        output=OutputConfig(**data["output"]),
        logging=LoggingConfig(**data["logging"]),
    )
    
    return config


def load_config(path: str = "config/config.yaml") -> Config:
    """
    Load and validate configuration from YAML file.
    
    Automatically:
    - Loads environment variables from .env
    - Interpolates ${VAR} placeholders in config
    - Validates all required keys and values
    - Creates output directories
    
    Args:
        path: Path to config.yaml file
        
    Returns:
        Config dataclass with full type hints and IDE autocomplete
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid or environment variables are missing
        yaml.YAMLError: If YAML parsing fails
    """
    # Load .env file
    load_dotenv()
    
    config_file = Path(path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Looked in: {config_file.absolute()}"
        )
    
    # Parse YAML
    try:
        with open(config_file, 'r') as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML config: {e}")
    
    if raw_config is None:
        raise ValueError(f"Config file is empty: {path}")
    
    # Validate structure before interpolation
    validate_config(raw_config)
    
    # Interpolate environment variables
    try:
        raw_config = interpolate_env_vars(raw_config)
    except ValueError as e:
        raise ValueError(f"Environment variable interpolation failed: {e}")
    
    # Convert to dataclass for IDE autocomplete
    config = _dict_to_dataclass(raw_config)
    
    # Create output directories
    create_output_directories(config)
    
    return config
