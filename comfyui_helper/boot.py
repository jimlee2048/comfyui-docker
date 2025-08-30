import json
import os
import shutil
import signal
import subprocess
import sys
import logging
from pathlib import Path

from .constants import (
    BOOT_CONFIG_DIR,
    BOOT_CONFIG_EXCLUDE,
    BOOT_CONFIG_INCLUDE,
    BOOT_PREV_STATE_PATH,
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
    json_default,
    exec_scripts_in_dir,
    logger,
    print_list_tree,
)


class StateManager:
    def __init__(self, store_path: Path):
        self._current_state = {}
        self._prev_state = self._load_prev_state(store_path)
        self.store_path = store_path

    @property
    def prev_state(self):
        return self._prev_state

    def _load_prev_state(self, path: Path) -> dict:
        if path is None:
            logger.info("ℹ️ No previous state path provided")
            return {}

        if path.is_file():
            logger.info("📂 Detected previous state, loading...")
            try:
                content = json.loads(path.read_text())
                logger.debug(f"🛠️ Loaded previous state: {content}")
                return content
            except Exception as e:
                logger.error(f"❌ Failed to load previous state '{path}': {str(e)}")
                return {}
        elif path.is_dir():
            logger.warning("⚠️ Detected invalid previous state, removing...")
            try:
                shutil.rmtree(path)
            except Exception as e:
                logger.error(f"❌ Failed to remove invalid state: {str(e)}")
            return {}
        else:
            logger.info("ℹ️ No previous state found")
            return {}

    @property
    def current_state(self):
        return self._current_state

    def update(self, category: str, items: list):
        if category in self._current_state:
            self._current_state[category].extend(items)
        else:
            self._current_state[category] = items
        logger.debug(f"🛠️ Updated current state: {self.current_state}")
        self.write()

    def write(self) -> bool:
        path = self.store_path
        config = self.current_state
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(config, default=json_default, indent=4)
            path.write_text(content)
            logger.info(f"✅ Current state saved to {path}")
            logger.debug(f"🛠️ Saved state file content: {content}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save current state: {str(e)}")
            return False


class ComfyUILauncher:
    def __init__(
        self,
        app_path: Path,
        config_dir: Path,
        state_path: Path,
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
        self.config_dir = config_dir
        self.state_path = state_path
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
        self.config_manager = None
        self.state_manager = None
        self.comfyui_process = None
        self._check_env()
        self._setup_signal_handlers()

    def _check_env(self):
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

    def _setup_signal_handlers(self):
        def shutdown_handler(_signum, _frame):
            if self.comfyui_process and self.comfyui_process.poll() is None:
                logger.info("🛑 Received termination signal, shutting down...")
                self.comfyui_process.terminate()
            else:
                logger.info(
                    "🛑 Received termination signal, but ComfyUI process is not running."
                )

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

    def _pre_init_hook(self):
        # exec pre-init custom scripts
        if self.pre_init_scripts:
            if self.pre_init_scripts.is_dir():
                logger.info("🛠️ Executing pre-init scripts...")
                exec_scripts_in_dir(self.pre_init_scripts)
            elif self.pre_init_scripts.is_file():
                logger.warning(f"⚠️ {self.pre_init_scripts} invalid, removing...")
                self.pre_init_scripts.unlink()

    def _post_init_hook(self):
        # exec post-init custom scripts
        if self.post_init_scripts:
            if self.post_init_scripts.is_dir():
                logger.info("🛠️ Executing post-init custom scripts...")
                exec_scripts_in_dir(self.post_init_scripts)
            elif self.post_init_scripts.is_file():
                logger.warning(f"⚠️ {self.post_init_scripts} invalid, removing...")
                self.post_init_scripts.unlink()

    def _post_exit_hook(self):
        pass

    def startup(self):
        # 1. load config & state
        self.config_manager = ConfigManager(
            config_dir=self.config_dir,
            include_pattern=self.include_config,
            exclude_pattern=self.exclude_config,
        )
        current_config = self.config_manager.config

        self.state_manager = StateManager(self.state_path)
        prev_state = self.state_manager.prev_state

        # 2. pre-init hook
        self._pre_init_hook()

        # 3. if UPDATE_NODE=true, try to update all installed nodes
        if prev_state and self.update_nodes:
            NodesManager.update_all_nodes()

        # 4. init nodes
        nodes_current_config = current_config.get("custom_nodes", [])
        nodes_init_result = None
        if self.init_nodes and nodes_current_config:
            nodes_prev_state = prev_state.get("custom_nodes", [])
            nodes_manager = NodesManager(nodes_current_config, nodes_prev_state)
            nodes_init_result = nodes_manager.init_nodes()
            if nodes_init_result is not None:
                nodes_installed, nodes_removed, nodes_existed, nodes_failed = (
                    nodes_init_result
                )
                nodes_successed = [
                    node
                    for node in nodes_manager.current_config
                    if node not in nodes_failed
                ]
                self.state_manager.update("custom_nodes", nodes_successed)

        # 5. init models
        models_current_config = current_config.get("models", [])
        models_init_result = None
        if self.init_models and models_current_config:
            models_prev_state = prev_state.get("models", [])
            models_manager = ModelsManager(models_current_config, models_prev_state)
            models_init_result = models_manager.init_models()
            if models_init_result is not None:
                (
                    models_downloaded,
                    models_removed,
                    models_moved,
                    models_existed,
                    models_failed,
                ) = models_init_result
                models_successed = [
                    model
                    for model in models_manager.current_config
                    if model not in models_failed
                ]
                self.state_manager.update("models", models_successed)

        # 6. post-init hook
        self._post_init_hook()

        # 7. init summary
        logger.info("--- Initialize Summary ---")

        if self.init_nodes:
            if nodes_init_result is None:
                logger.info("🧩 Nodes: No config changes, initialization skipped.")
            else:
                nodes_total_count = len(nodes_current_config)
                nodes_failed_count = len(nodes_failed)
                nodes_success_count = len(nodes_successed)
                logger.info(
                    f"🧩 Nodes: {nodes_success_count}/{nodes_total_count} success:"
                )
                nodes_success_details = [
                    f"installed: {len(nodes_installed)}",
                    f"removed: {len(nodes_removed)}",
                    f"existed: {len(nodes_existed)}",
                ]
                print_list_tree(nodes_success_details)
                if nodes_failed_count:
                    logger.warning(
                        f"⚠️ Nodes: {nodes_failed_count} failed to process, will retry on next boot:"
                    )
                    print_list_tree(nodes_failed, level=logging.WARNING)

        if self.init_models:
            if models_init_result is None:
                logger.info("📦 Models: No config changes, initialization skipped.")
            else:
                models_total_count = len(models_current_config)
                models_failed_count = len(models_failed)
                models_success_count = len(models_successed)
                logger.info(
                    f"📦 Models: {models_success_count}/{models_total_count} success:"
                )
                models_success_details = [
                    f"downloaded: {len(models_downloaded)}",
                    f"removed: {len(models_removed)}",
                    f"moved: {len(models_moved)}",
                    f"existed: {len(models_existed)}",
                ]
                print_list_tree(models_success_details)
                if models_failed_count:
                    logger.warning(
                        f"⚠️ Models: {models_failed_count} failed to process, will retry on next boot:"
                    )
                    print_list_tree(models_failed, level=logging.WARNING)

        logger.info("--------------------")

        # 8. launch comfyui
        logger.info("🚀 Launching ComfyUI...")
        launch_args = ["--listen", self.listen, "--port", str(self.port)]
        if self.extra_args:
            launch_args.extend(self.extra_args.split())
        cmd = [sys.executable, str(self.app_path / "main.py")] + launch_args
        exit_code = 0
        try:
            self.comfyui_process = subprocess.Popen(cmd)
            exit_code = self.comfyui_process.wait()
            logger.info(f"🛑 ComfyUI exited with code: {exit_code}")
        except Exception as e:
            logger.error(
                f"❌ An unexpected error occurred while managing the process: {e}"
            )
            exit_code = 1
        finally:
            self._post_exit_hook()
            sys.exit(exit_code)


def main():
    launcher = ComfyUILauncher(
        listen="0.0.0.0,::",
        port=8188,
        extra_args=COMFYUI_EXTRA_ARGS,
        app_path=COMFYUI_PATH,
        config_dir=BOOT_CONFIG_DIR,
        state_path=BOOT_PREV_STATE_PATH,
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
