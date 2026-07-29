"""Configuration loader with environment variable support."""

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv


def load_env_file(env_path: str = ".env") -> None:
    """Load environment variables from .env file."""
    env_file = Path(env_path)
    if env_file.exists():
        load_dotenv(env_file)


def interpolate_env_vars(value: Any) -> Any:
    """Recursively interpolate ${VAR} placeholders with environment variables."""
    if isinstance(value, str):
        # Replace ${VAR} with environment variable value
        def replace_var(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        
        return re.sub(r'\$\{([^}]+)\}', replace_var, value)
    elif isinstance(value, dict):
        return {k: interpolate_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [interpolate_env_vars(item) for item in value]
    return value


def load_config(config_path: str = "config/config.yaml") -> Dict[str, Any]:
    """
    Load config from YAML file with environment variable interpolation.
    
    Args:
        config_path: Path to config.yaml file
        
    Returns:
        Configuration dictionary with environment variables interpolated
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If YAML parsing fails
    """
    # Load .env file first
    load_env_file()
    
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Interpolate environment variables
    config = interpolate_env_vars(config)
    
    return config


if __name__ == "__main__":
    # Example usage
    config = load_config()
    print("Loaded configuration:")
    print(yaml.dump(config, default_flow_style=False))
