import json
import os
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from collections import defaultdict
from pathlib import Path

import giturlparse
import tomllib

from constants import (
    BOOT_CONFIG_DIR,
    BOOT_CONFIG_EXCLUDE,
    BOOT_CONFIG_INCLUDE,
    BOOT_CONFIG_PREV_PATH,
    BOOT_INIT_MODEL,
    BOOT_INIT_NODE,
    BOOT_INIT_NODE_EXCLUDE,
    BOOT_POST_INIT_SCRIPTS,
    BOOT_PRE_INIT_SCRIPTS,
    BOOT_UPDATE_NODE,
    CIVITAI_API_TOKEN,
    CN_NETWORK,
    COMFYUI_EXTRA_ARGS,
    COMFYUI_MN_CLI,
    COMFYUI_PATH,
    HF_API_TOKEN,
    HF_ENDPOINT,
    HF_ENDPOINT_NETLOC,
    CIVITAI_ENDPOINT,
    CIVITAI_ENDPOINT_NETLOC,
)
from models import ModelManager
from nodes import NodeManager
from utils import (
    Progress,
    compile_pattern,
    exec_command,
    exec_script,
    json_default,
    logger,
)


class BootConfigManager:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.node_exclude = BOOT_INIT_NODE_EXCLUDE
        self.current_config = self.load_boot_config()
        self.prev_config = self.load_prev_config(BOOT_CONFIG_PREV_PATH)
        self.current_nodes = self.load_nodes_config(self.current_config)
        self.current_models = self.load_models_config(self.current_config)
        self.prev_nodes = self.load_nodes_config(self.prev_config)
        self.prev_models = self.load_models_config(self.prev_config)

    def _sort_by_numeric_prefix(self, file_path: Path) -> tuple:
        filename = file_path.name
        # Extract numeric prefix if it exists
        pattern = compile_pattern(r"^(\d+)-")
        match = pattern.match(filename)
        if match:
            return (int(match.group(1)), filename)
        # If no numeric prefix, sort after numbered files
        return (float("inf"), filename)

    def _drop_duplicates_config(
        self, config: list[dict], cond_key: list[str]
    ) -> tuple[list[dict], list[dict], int]:
        unique_items = []
        duplicate_items = []
        unique_kv_tracker = set()
        for item in config:
            unique_kv = tuple(item[key] for key in cond_key)
            if unique_kv not in unique_kv_tracker:
                unique_items.append(item)
                unique_kv_tracker.add(unique_kv)
            else:
                duplicate_items.append(item)
        return unique_items, duplicate_items

    def _preprocess_url(self, url: str) -> str:
        parsed_url = urlparse(url)
        # check if url is valid
        if not parsed_url.netloc:
            raise Exception(f"Invalid URL: {url}")
        # chinese mainland network settings
        if CN_NETWORK:
            fr_map = {
                "huggingface.co": HF_ENDPOINT_NETLOC,
                "civitai.com": CIVITAI_ENDPOINT_NETLOC,
            }
            if parsed_url.netloc in fr_map:
                url = parsed_url._replace(netloc=fr_map[parsed_url.netloc]).geturl()
        return url

    def load_boot_config(self) -> dict:
        config_dir = Path(self.config_dir)
        config_files = []

        if config_dir.is_dir():
            logger.info(f"📂 Loading boot config from {self.config_dir}")
            config_files = list(config_dir.rglob("*.toml"))
        elif config_dir.is_file():
            logger.warning("⚠️ Invalid boot config detected, removing...")
            config_dir.unlink()
            return {}

        if BOOT_CONFIG_INCLUDE or BOOT_CONFIG_EXCLUDE:
            include_pattern = compile_pattern(BOOT_CONFIG_INCLUDE)
            exclude_pattern = compile_pattern(BOOT_CONFIG_EXCLUDE)
            filtered_files = [
                f
                for f in config_files
                if (not include_pattern or include_pattern.search(f.name))
                and (not exclude_pattern or not exclude_pattern.search(f.name))
            ]
            if include_pattern:
                logger.info(f"⚡ Include filter: {BOOT_CONFIG_INCLUDE}")
            if exclude_pattern:
                logger.info(f"⚡ Exclude filter: {BOOT_CONFIG_EXCLUDE}")
            config_files = filtered_files

        # sort config files by numeric prefix
        config_files.sort(key=self._sort_by_numeric_prefix)

        logger.info(f"📄 Found {len(config_files)} config files:")
        for file in config_files:
            logger.info(f"└─ {file}")

        boot_config = defaultdict(list)
        try:
            for file in config_files:
                config = tomllib.loads(file.read_text())
                for key, value in config.items():
                    boot_config[key].extend(value)
        except Exception as e:
            logger.error(f"❌ Failed to load boot config: {str(e)}")
            exit(1)
        return boot_config

    def load_prev_config(self, prev_path: Path) -> dict:
        if prev_path.is_file():
            logger.info(f"📂 Loading previous config: {prev_path}")
        elif prev_path.is_dir():
            logger.warning("⚠️ Invalid previous config detected, removing...")
            shutil.rmtree(prev_path)
        else:
            logger.info("ℹ️ No previous config found")
            return {}
        return json.loads(prev_path.read_text())

    def write_config_cache(self, path: Path, config: dict) -> bool:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps(config, default=json_default, indent=4))
            logger.info(f"✅ Current config saved to {path}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save current config: {str(e)}")
            return False

    def load_nodes_config(self, boot_config: dict) -> list[dict]:
        nodes_config = boot_config.get("custom_nodes", [])
        if not nodes_config:
            return []

        for node in nodes_config.copy():
            try:
                # source: registry
                if "node_id" in node:
                    node["source"] = "registry"
                    node["name"] = node["node_id"]
                    # use 'latest' as default version
                    if "version" not in node:
                        node["version"] = "latest"
                # source: git
                elif "url" in node:
                    node["source"] = "git"
                    node["url"] = self._preprocess_url(node["url"])
                    node_repo = giturlparse.parse(node["url"])
                    # validate git url
                    if not node_repo.valid:
                        raise Exception(f"Invalid git URL: {node['url']}")
                    node["name"] = node_repo.name.lower()
                else:
                    raise Exception("None of 'node_id' or 'url' found in node config")
                if node["name"] in self.node_exclude:
                    logger.warning(f"⚠️ Skip excluded node: {node['name']}")
                    nodes_config.remove(node)
                    continue
            except KeyError as e:
                logger.warning(f"⚠️ Invalid node config: {str(e)}\n{node}")
                continue

        # drop duplicates
        nodes_config, duplicates = self._drop_duplicates_config(nodes_config, ["name"])
        if duplicates:
            logger.warning(f"⚠️ Found {len(duplicates)} duplicate nodes:")
            for node in duplicates:
                logger.warning(f"└─ {node['name']}")

        return nodes_config

    def load_models_config(self, boot_config: dict) -> list[dict]:
        models_config = boot_config.get("models", [])
        if not models_config:
            return []

        for model in models_config.copy():
            try:
                model["url"] = self._preprocess_url(model["url"])
                model["path"] = str(COMFYUI_PATH / model["dir"] / model["filename"])
            except KeyError as e:
                logger.warning(f"⚠️ Invalid model config: {model}\n{str(e)}")
                continue

        # drop duplicates
        models_config, duplicates = self._drop_duplicates_config(
            models_config, ["path"]
        )
        if duplicates:
            logger.warning(f"⚠️ Found {len(duplicates)} duplicate models:")
            for model in duplicates:
                logger.warning(f"└─ {model['filename']}")

        return models_config


class ComfyUIInitializer:
    def __init__(
        self,
        boot_config: Path = None,
        comfyui_path: Path = None,
        pre_init_scripts: Path = None,
        post_init_scripts: Path = None,
    ):
        self.comfyui_path = comfyui_path
        self.pre_scripts_dir = pre_init_scripts
        self.post_scripts_dir = post_init_scripts
        self.config_loader = BootConfigManager(boot_config)
        self.current_config = self.config_loader.current_config
        self.prev_config = self.config_loader.prev_config
        self.current_nodes = self.config_loader.current_nodes
        self.current_models = self.config_loader.current_models
        self.prev_nodes = self.config_loader.prev_nodes
        self.prev_models = self.config_loader.prev_models

    def _exec_scripts_in_dir(self, dir: Path) -> bool:
        if not dir or not dir.is_dir():
            logger.warning(f"⚠️ {dir} is not a valid directory.")
            return False
        scripts = sorted(dir.glob("*.sh"))
        if not scripts:
            logger.info(f"ℹ️ No scripts found in {dir.name}.")
            return False
        scripts_count = len(scripts)
        logger.info(f"🛠️ Found {scripts_count} scripts in {dir.name}:")
        for script in scripts:
            logger.info(f"└─ {script.name}")
        progress = Progress()
        progress.start(scripts_count)
        for script in scripts:
            progress.advance(
                msg=f"🛠️ Executing {dir.name} script: {script.name}", style="info"
            )
            exec_script(script)
        return True

    def run(self):
        # execute pre-init scripts
        if self.pre_scripts_dir.is_dir():
            logger.info("🛠️ Scanning pre-init scripts...")
            self._exec_scripts_in_dir(self.pre_scripts_dir)
        elif self.pre_scripts_dir.is_file():
            logger.warning(f"⚠️ {self.pre_scripts_dir} invalid, removing...")
            self.pre_scripts_dir.unlink()
        # if UPDATE_NODE is enabled, try to update all installed nodes
        if self.prev_config and BOOT_UPDATE_NODE:
            logger.info("🔄 Updating all installed nodes...")
            try:
                exec_command([sys.executable, COMFYUI_MN_CLI, "update", "all"])
            except Exception:
                logger.error("❌ Failed to execute node update command, skipping...")
        # init nodes and models
        failed_config = defaultdict(list)
        if self.current_config and BOOT_INIT_NODE:
            node_manager = NodeManager(self.comfyui_path)
            node_manager.init_nodes(self.current_nodes, self.prev_nodes)
            failed_config["custom_nodes"] = node_manager.failed_list
        if self.current_config and BOOT_INIT_MODEL:
            model_manager = ModelManager(self.comfyui_path)
            model_manager.init_models(self.current_models, self.prev_models)
            failed_config["models"] = model_manager.failed_list
        # execute post init scripts
        if self.post_scripts_dir.is_dir():
            logger.info("🛠️ Scanning post-init scripts...")
            self._exec_scripts_in_dir(self.post_scripts_dir)
        elif self.post_scripts_dir.is_file():
            logger.warning(f"⚠️ {self.post_scripts_dir} invalid, removing...")
            self.post_scripts_dir.unlink()

        # check if any failed config
        if failed_config["custom_nodes"]:
            logger.error(
                f"❌ Failed to init {len(failed_config['custom_nodes'])} nodes, will retry on next boot:"
            )
            for node in failed_config["custom_nodes"]:
                logger.error(f"└─ {node['name']}")
        if failed_config["models"]:
            logger.error(
                f"❌ Failed to init {len(failed_config['models'])} models, will retry on next boot:"
            )
            for model in failed_config["models"]:
                logger.error(f"└─ {model['filename']}")
        # cache succeeded config
        # successed config = current config - failed config
        succeeded_config = defaultdict(list)
        for key, items in self.current_config.items():
            if key == "custom_nodes":
                succeeded_config[key] = [
                    node for node in items if node not in failed_config["custom_nodes"]
                ]
            elif key == "models":
                succeeded_config[key] = [
                    model for model in items if model not in failed_config["models"]
                ]
        self.config_loader.write_config_cache(BOOT_CONFIG_PREV_PATH, succeeded_config)

        # launch comfyui
        logger.info("🚀 Launching ComfyUI...")
        launch_args_list = ["--listen", "0.0.0.0,::", "--port", "8188"] + (
            COMFYUI_EXTRA_ARGS.split() if COMFYUI_EXTRA_ARGS else []
        )
        subprocess.run(
            [sys.executable, str(self.comfyui_path / "main.py")] + launch_args_list,
            check=False,
        )


if __name__ == "__main__":
    logger.info("Starting boot process")

    # check if comfyui path exists
    if not COMFYUI_PATH.is_dir():
        logger.error(f"❌ Invalid ComfyUI path: {COMFYUI_PATH}")
        exit(1)

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

    app = ComfyUIInitializer(
        BOOT_CONFIG_DIR, COMFYUI_PATH, BOOT_PRE_INIT_SCRIPTS, BOOT_POST_INIT_SCRIPTS
    )
    logger.info("Initializing ComfyUI...")
    app.run()
