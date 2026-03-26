#!/usr/bin/env python

import os
import json
from pathlib import Path


def load_groq_api_key(api_key=None, debug=False):
    """
    Load Groq API key with priority order:
    1. Direct parameter
    2. GROQ_API_KEY environment variable
    3. ~/.groq/config.json file
    4. ./.groq_key (project-local file)

    Args:
        api_key: Direct API key parameter
        debug: Enable debug output

    Returns:
        str: The API key if found, None otherwise
    """
    # Priority 1: Direct parameter
    if api_key:
        if debug:
            import mmguero
            mmguero.eprint("Using provided API key parameter")
        return api_key

    # Priority 2: Environment variable
    env_key = os.getenv("GROQ_API_KEY")
    if env_key:
        if debug:
            import mmguero
            mmguero.eprint("Using GROQ_API_KEY environment variable")
        return env_key

    # Priority 3: ~/.groq/config.json file
    config_path = Path.home() / ".groq" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                if "api_key" in config:
                    if debug:
                        import mmguero
                        mmguero.eprint(f"Using API key from {config_path}")
                    return config["api_key"]
        except (json.JSONDecodeError, IOError) as e:
            if debug:
                import mmguero
                mmguero.eprint(f"Error reading {config_path}: {e}")

    # Priority 4: ./.groq_key (project-local file)
    local_key_path = Path(".groq_key")
    if local_key_path.exists():
        try:
            with open(local_key_path, 'r') as f:
                key = f.read().strip()
                if key:
                    if debug:
                        import mmguero
                        mmguero.eprint(f"Using API key from {local_key_path}")
                    return key
        except IOError as e:
            if debug:
                import mmguero
                mmguero.eprint(f"Error reading {local_key_path}: {e}")

    return None
