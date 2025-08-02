import os
from pathlib import Path
from urllib.parse import urlparse


def get_bool_env(var_name: str, default: bool = False) -> bool:
    value = os.environ.get(var_name)
    if value is None:
        return default
    value = value.lower()
    if value in ("true", "1", "t", "yes", "y"):
        return True
    elif value in ("false", "0", "f", "no", "n"):
        return False
    else:
        # raise ValueError(f"Invalid bool value for environment variable '{var_name}': '{value}'")
        return default


WORKDIR = Path(os.environ.get("WORKDIR", "/workspace"))
COMFYUI_PATH = Path(os.environ.get("COMFYUI_PATH", None)) or WORKDIR / "comfyui"
COMFYUI_MN_PATH = (
    Path(os.environ.get("COMFYUI_MN_PATH", None))
    or COMFYUI_PATH / "custom_nodes" / "comfyui-manager"
)
COMFYUI_MN_CLI = str(COMFYUI_MN_PATH / "cm-cli.py")
COMFYUI_EXTRA_ARGS = os.environ.get("COMFYUI_EXTRA_ARGS", None)

BOOT_CONFIG_INCLUDE = os.environ.get("BOOT_CONFIG_INCLUDE", None)
BOOT_CONFIG_EXCLUDE = os.environ.get("BOOT_CONFIG_EXCLUDE", None)
BOOT_CONFIG_DIR = WORKDIR / "boot_config"
BOOT_PREV_STATE_PATH = WORKDIR / ".cache" / "prev-state.json"
BOOT_SCRIPTS_DIR = WORKDIR / "scripts"
BOOT_PRE_INIT_SCRIPTS_DIR = BOOT_SCRIPTS_DIR / "pre-init"
BOOT_POST_INSTALL_NODE_SCRIPTS_DIR = BOOT_SCRIPTS_DIR / "post-install-node"
BOOT_POST_INIT_SCRIPTS_DIR = BOOT_SCRIPTS_DIR / "post-init"

BOOT_UPDATE_NODE = get_bool_env("UPDATE_NODE", False)
BOOT_INIT_NODE = get_bool_env("INIT_NODE", True)
BOOT_INIT_NODE_EXCLUDE = {"comfyui-manager"}
BOOT_INIT_MODEL = get_bool_env("INIT_MODEL", True)

HF_API_TOKEN = os.environ.get("HF_API_TOKEN", None)
CIVITAI_API_TOKEN = os.environ.get("CIVITAI_API_TOKEN", None)

CN_NETWORK = get_bool_env("CN_NETWORK", False)
if CN_NETWORK:
    # Use mirror sites for Hugging Face and Civitai when CN_NETWORK is true
    HF_ENDPOINT_DEFAULT = "https://hf-mirror.com"
    CIVITAI_ENDPOINT_DEFAULT = "https://civitai.work"
else:
    # Use official sites otherwise
    HF_ENDPOINT_DEFAULT = "https://huggingface.co"
    CIVITAI_ENDPOINT_DEFAULT = "https://civitai.com"
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", HF_ENDPOINT_DEFAULT)
CIVITAI_ENDPOINT = os.environ.get("CIVITAI_ENDPOINT", CIVITAI_ENDPOINT_DEFAULT)
HF_ENDPOINT_NETLOC = urlparse(HF_ENDPOINT).netloc
CIVITAI_ENDPOINT_NETLOC = urlparse(CIVITAI_ENDPOINT).netloc

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
