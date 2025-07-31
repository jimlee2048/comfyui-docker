import os
import subprocess
import sys
from pathlib import Path

from .constants import (
    BOOT_CONFIG_DIR,
    BOOT_CONFIG_EXCLUDE,
    BOOT_CONFIG_INCLUDE,
    BOOT_CONFIG_PREV_PATH,
    BOOT_INIT_MODEL,
    BOOT_INIT_NODE,
    BOOT_POST_INIT_SCRIPTS_DIR,
    BOOT_PRE_INIT_SCRIPTS_DIR,
    BOOT_UPDATE_NODE,
    CIVITAI_API_TOKEN,
    CIVITAI_ENDPOINT,
    CIVITAI_ENDPOINT_NETLOC,
    CN_NETWORK,
    COMFYUI_EXTRA_ARGS,
    COMFYUI_PATH,
    HF_API_TOKEN,
    HF_ENDPOINT,
    HF_ENDPOINT_NETLOC,
)
from .config import ConfigManager
from .models import ModelsManager
from .nodes import NodesManager
from .utils import (
    exec_scripts_in_dir,
    logger,
    print_list_tree,
)


class ComfyUILauncher:
    def __init__(
        self,
        app_path: Path,
        boot_config: Path,
        prev_boot_config: Path,
        include_config: str = None,
        exclude_config: str = None,
        pre_init_scripts: Path = None,
        post_init_scripts: Path = None,
        update_nodes: bool = False,
        init_nodes: bool = False,
        init_models: bool = False,
        listen: str = "0.0.0.0,::",
        port: int = 8188,
        extra_args: str = None,
    ):
        self.app_path = app_path
        self.boot_config = boot_config
        self.prev_boot_config = prev_boot_config
        self.include_config = include_config
        self.exclude_config = exclude_config
        self.pre_init_scripts = pre_init_scripts
        self.post_init_scripts = post_init_scripts
        self.update_nodes = update_nodes
        self.init_nodes = init_nodes
        self.init_models = init_models
        self.listen = listen
        self.port = port
        self.extra_args = extra_args
        self._check_boot_env()

    def _check_boot_env(self):
        # check if comfyui path exists
        if not self.app_path.is_dir():
            logger.error(f"❌ Invalid ComfyUI path: {self.app_path}")
            raise FileNotFoundError(f"Invalid ComfyUI path: {self.app_path}")

        # chinese mainland network settings
        if CN_NETWORK:
            logger.info("🌐 Applying CN network optimization")
            # pip source to ustc mirror
            os.environ["PIP_INDEX_URL"] = "https://mirrors.ustc.edu.cn/pypi/web/simple"
        if HF_API_TOKEN and HF_ENDPOINT_NETLOC.lower() not in ("huggingface.co"):
            logger.warning(
                f"⚠️ HF_API_TOKEN will be sent to a third party endpoint: {HF_ENDPOINT}"
            )
        if CIVITAI_API_TOKEN and CIVITAI_ENDPOINT_NETLOC.lower() not in ("civitai.com"):
            logger.warning(
                f"⚠️ CIVITAI_API_TOKEN will be sent to a third party endpoint: {CIVITAI_ENDPOINT}"
            )

    def startup(self):
        # 0. load boot config
        boot_config = ConfigManager(
            config_dir=self.boot_config,
            prev_config_path=self.prev_boot_config,
            include_pattern=self.include_config,
            exclude_pattern=self.exclude_config,
        )
        current_config = boot_config.config
        prev_config = boot_config.prev_config

        # 1. exec pre-init scripts
        if self.pre_init_scripts:
            if self.pre_init_scripts.is_dir():
                logger.info("🛠️ Executing pre-init scripts...")
                exec_scripts_in_dir(self.pre_init_scripts)
            elif self.pre_init_scripts.is_file():
                logger.warning(f"⚠️ {self.pre_init_scripts} invalid, removing...")
                self.pre_init_scripts.unlink()

        # 2. if UPDATE_NODE=true, try to update all installed nodes
        if prev_config and self.update_nodes:
            NodesManager.update_all_nodes()
        failed_config = {}

        # 3. init nodes
        current_nodes_config = current_config.get("custom_nodes", [])
        prev_nodes_config = prev_config.get("custom_nodes", [])
        if self.init_nodes and current_nodes_config:
            nodes_manager = NodesManager(current_nodes_config, prev_nodes_config)
            result = nodes_manager.init_nodes()
            if result is not None:
                _, _, failed = result
                if failed:
                    failed_config["custom_nodes"] = failed

        # 4. init models
        current_models_config = current_config.get("models", [])
        prev_models_config = prev_config.get("models", [])
        if self.init_models and current_models_config:
            models_manager = ModelsManager(current_models_config, prev_models_config)
            result = models_manager.init_models()
            if result is not None:
                _, _, _, failed = result
                if failed:
                    failed_config["models"] = failed

        # 5. exec post-init scripts
        if self.post_init_scripts:
            if self.post_init_scripts.is_dir():
                logger.info("🛠️ Executing post-init scripts...")
                exec_scripts_in_dir(self.post_init_scripts)
            elif self.post_init_scripts.is_file():
                logger.warning(f"⚠️ {self.post_init_scripts} invalid, removing...")
                self.post_init_scripts.unlink()

        # 6. report failed config
        if failed_config:
            logger.error("❌ Failed to process config, will retry on next boot:")
            for key, value in failed_config.items():
                logger.error(f"❌ Failed {len(value)} {key}:")
                print_list_tree(value)

        # 7. save succeeded config
        succeeded_config = {}
        for key, value in current_config.items():
            if key in failed_config:
                succeeded_config[key] = [
                    item for item in value if item not in failed_config[key]
                ]
            else:
                succeeded_config[key] = value
        boot_config.save_config(path=self.prev_boot_config, config=succeeded_config)

        # 8. launch comfyui
        logger.info("🚀 Launching ComfyUI...")
        launch_args = ["--listen", self.listen, "--port", str(self.port)]
        if self.extra_args:
            launch_args.extend(self.extra_args.split())
        cmd = [sys.executable, str(self.app_path / "main.py")] + launch_args
        subprocess.run(cmd, check=False)


def main():
    """Main entry point for the comfyui-boot console script."""
    launcher = ComfyUILauncher(
        listen="0.0.0.0,::",
        port=8188,
        extra_args=COMFYUI_EXTRA_ARGS,
        app_path=COMFYUI_PATH,
        boot_config=BOOT_CONFIG_DIR,
        prev_boot_config=BOOT_CONFIG_PREV_PATH,
        include_config=BOOT_CONFIG_INCLUDE,
        exclude_config=BOOT_CONFIG_EXCLUDE,
        pre_init_scripts=BOOT_PRE_INIT_SCRIPTS_DIR,
        post_init_scripts=BOOT_POST_INIT_SCRIPTS_DIR,
        update_nodes=BOOT_UPDATE_NODE,
        init_nodes=BOOT_INIT_NODE,
        init_models=BOOT_INIT_MODEL,
    )
    launcher.startup()


if __name__ == "__main__":
    main()
