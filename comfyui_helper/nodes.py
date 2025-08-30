import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import giturlparse

from .constants import (
    BOOT_INIT_NODE_EXCLUDE,
    BOOT_POST_INSTALL_NODE_SCRIPTS_DIR,
    COMFYUI_MN_CLI,
    COMFYUI_PATH,
)
from .utils import (
    Progress,
    compile_pattern,
    exec_cm_cli,
    exec_command,
    exec_script,
    is_valid_git_path,
    logger,
    preprocess_url,
    print_list_tree,
)


@dataclass
class Node:
    name: str
    source: str
    version: str | None = None
    url: str | None = None
    script: Path | str | None = None
    path: Path = field(init=False)

    def __post_init__(self):
        if self.source not in ["git", "registry"]:
            raise ValueError(f"Invalid source: {self.source}")
        if self.source == "git" and not self.url:
            raise ValueError("Git source requires a URL")
        if self.source == "registry" and not self.version:
            self.version = "nightly"
        if self.script:
            self.script = BOOT_POST_INSTALL_NODE_SCRIPTS_DIR / self.script
        self.path = COMFYUI_PATH / "custom_nodes" / self.name

    def __eq__(self, other):
        if not isinstance(other, Node):
            return NotImplemented
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        info = f"{self.name} ({self.source})"
        if self.version and self.version != "nightly":
            info += f" @ {self.version}"
        return info

    def is_exists(self) -> bool:
        if not self.path.exists():
            return False
        if self.path.is_file():
            logger.warning(f"⚠️ {self.name} path invalid, removing: {self.path}")
            self.path.unlink()
            return False
        if self.path.is_dir():
            if self.source == "git" and not is_valid_git_path(self.path):
                logger.warning(
                    f"⚠️ {self.name} not a valid git repo, removing: {self.path}"
                )
                shutil.rmtree(self.path)
                return False
            return True
        return False

    def is_excluded(self) -> bool:
        if self.name in BOOT_INIT_NODE_EXCLUDE:
            return True
        return False

    def setup(self) -> bool:
        try:
            exec_cm_cli("post-install", [str(self.path)], check=True)
            logger.info(f"✅ Successfully initialize node: {self.path.name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize node {self.path.name}: {str(e)}")
            return False

    def update(self) -> bool:
        try:
            exec_cm_cli("update", [str(self.path)], check=True)
            logger.info(f"✅ Successfully update node: {self.path.name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update node {self.path.name}: {str(e)}")
            return False

    def _check_registry_install(
        self, install_result: subprocess.CompletedProcess
    ) -> tuple[bool | None, str | None]:
        # reference:original cm-cli.py output format
        # https://github.com/ltdrdata/ComfyUI-Manager/blob/411c0633a3d542ac20ea8cb47c9578f22fb19854/cm-cli.py#L162

        # check if error msg print exists
        errors_pattern = compile_pattern(r"ERROR:(?P<msg>.+)")
        errors_match = errors_pattern.finditer(install_result.stdout)
        if errors_match:
            for error in errors_match:
                error_msg = error.group("msg").strip()
                if "An error occurred while installing" in error_msg:
                    # try to get more detailed error message from next line
                    following_stdout = (
                        install_result.stdout[error.end() :].strip().splitlines()
                    )
                    next_line = following_stdout[0].strip()
                    error_msg = next_line if next_line else error_msg
                return False, error_msg

        # check if installation result print exists
        result_pattern = compile_pattern(r"1\/1\s\[(?P<result>.+?)\]\s(?P<msg>.+)")
        result_match = result_pattern.search(install_result.stdout)
        if result_match:
            result = result_match.group("result")
            if result == "INSTALLED":
                logger.info(f"✅ Successfully installed node: {self.name}")
                return True, None
            elif result == "SKIP":
                logger.info(f"ℹ️ {self.name} already exists. Skipped.")
                return None, result
            elif result == "ENABLED":
                logger.warning(f"⚠️ {self.name} already exists, but just enabled.")
                return None, result
        # if no result found, return False
        return False, "Failed to parse installation result"

    def install(self, setup_exists=False) -> bool | None:
        # pre: check if node is excluded or exists
        if self.is_excluded():
            logger.warning(f"⚠️ {self.name} is excluded from installation. Skipped.")
            # will be treat as existed
            return None
        if self.is_exists():
            if setup_exists:
                logger.warning(f"⚠️ {self.name} already exists, trying to setup...")
                return self.setup()
            else:
                logger.info(f"ℹ️ {self.name} already exists. Skipped.")
                return None
        # main install process
        logger.info(f"📦 Installing node: {self.name}")
        try:
            if self.source == "registry":
                install_output = exec_cm_cli(
                    "install", [f"{self.name}@{self.version}"], check=True
                )
                install_result, error_msg = self._check_registry_install(install_output)
                if install_result is None:
                    # "SKIP" or "ENABLED" -> node exists, will skip post install process
                    return None
                elif install_result is False:
                    raise Exception(f"{error_msg}")
            if self.source == "git":
                if self.version:
                    exec_command(
                        ["git", "clone", "-b", self.version, self.url, str(self.path)],
                        check=True,
                    )
                else:
                    exec_command(["git", "clone", self.url, str(self.path)], check=True)
                if not self.setup():
                    # remove downloaded files, will treat as not exist node to retry
                    shutil.rmtree(self.path)
                    raise Exception("failed to setup")
            logger.info(f"✅ Successfully installed node: {self.name}")
        except Exception as e:
            logger.error(f"❌ Failed to install node {self.name}: {str(e)}")
            return False
        # post: exec script
        if self.script:
            logger.info(f"🛠️ Executing post-install-node script: {self.script}")
            exec_script(self.script)
        return True

    def remove(self) -> bool | None:
        # pre: check if node is excluded or exists
        if self.is_excluded():
            logger.warning(f"⚠️ {self.name} is excluded from removal. Skipped.")
            # will be treat as not existed
            return None
        if not self.is_exists():
            logger.info(f"ℹ️ {self.name} not found. Skipped.")
            return None
        # main uninstall process
        logger.info(f"🗑️ Removing node: {self.name}")
        try:
            # if nodes source from registry, try to use cm-cli process uninstalling first
            if self.source == "registry":
                exec_cm_cli("uninstall", [self.name], check=True)
            # check again if node exists
            if self.path.exists():
                shutil.rmtree(self.path)
            logger.info(f"✅ Uninstalled node: {self.name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to uninstall node {self.name}: {str(e)}")
            return False


class NodesManager:
    def __init__(self, current_config: list[dict], prev_state: list[dict] = None):
        self.current_config = self._load_config(current_config)
        self.prev_state = self._load_config(prev_state) if prev_state else []

    def _node_factory(self, config: dict) -> Node:
        # from prev state
        if "path" in config:
            source = config["source"]
            name = config["name"]
            version = config.get("version")
            url = config.get("url")
            script = config.get("script")
        # source: registry
        elif "node_id" in config:
            source = "registry"
            name = config["node_id"]
            version = config.get("version")
            url = config.get("url")
            script = config.get("script")
        # source: git
        elif "url" in config:
            source = "git"
            url = preprocess_url(config["url"])
            repo = giturlparse.parse(url)
            if not repo.valid:
                raise ValueError(f"Invalid git URL: {url}")
            name = repo.name.lower()
            version = config.get("branch")
            script = config.get("script")
        else:
            raise ValueError("Invalid node config. Missing 'node_id' or 'url'")
        # create node object
        return Node(
            name,
            source,
            version,
            url,
            script,
        )

    def _load_config(self, nodes_config: list[dict]) -> list[Node]:
        # 1. load all nodes as Node objects
        all_nodes: list[Node] = []
        for config in nodes_config:
            try:
                # create node object
                node = self._node_factory(config)
                all_nodes.append(node)
            except Exception as e:
                logger.warning(f"⚠️ Skip invalid node config: {str(e)}\n{config}")
                continue

        # 2. remove duplicates while preserving order (keep first occurrence)
        unique_nodes = list(dict.fromkeys(all_nodes))

        # 3. log warnings for duplicates found
        if len(unique_nodes) < len(all_nodes):
            node_counts = Counter(all_nodes)
            duplicate_nodes = [node for node, count in node_counts.items() if count > 1]
            logger.warning(f"⚠️ Found {len(duplicate_nodes)} duplicate nodes:")
            print_list_tree(duplicate_nodes)

        return unique_nodes

    def init_nodes(
        self,
    ) -> tuple[list[Node], list[Node], list[Node], list[Node]] | None:
        if not self.current_config:
            logger.info("📦 No nodes in config")
            return None

        install_queue = []
        remove_queue = []

        if self.prev_state:
            setup_exists = False
            # compare with previous state
            install_queue = [
                node for node in self.current_config if node not in self.prev_state
            ]
            remove_queue = [
                node for node in self.prev_state if node not in self.current_config
            ]
        else:
            # maybe upgrade from old image, should ensure all exist nodes are setup
            setup_exists = True
            install_queue = self.current_config

        if not (install_queue or remove_queue):
            logger.info("ℹ️ No nodes config changes to proceed.")
            return None

        installed = []
        removed = []
        existed = []
        failed = []

        # install
        if install_queue:
            install_count = len(install_queue)
            logger.info(f"📦 Installing {install_count} nodes:")
            print_list_tree(install_queue)
            with Progress(total_steps=install_count) as p:
                for node in install_queue:
                    p.advance()
                    result = node.install(setup_exists=setup_exists)
                    if result is True:
                        installed.append(node)
                    elif result is None:
                        existed.append(node)
                    elif result is False:
                        failed.append(node)

        # remove
        if remove_queue:
            remove_count = len(remove_queue)
            logger.info(f"🗑️ Removing {remove_count} nodes:")
            print_list_tree(remove_queue)
            with Progress(total_steps=remove_count) as p:
                for node in remove_queue:
                    p.advance()
                    result = node.remove()
                    if result is True:
                        removed.append(node)
                    elif result is False:
                        failed.append(node)
                    # None means file not found - don't count as removed or failed
        return (
            installed,
            removed,
            existed,
            failed,
        )

    def update_nodes(self) -> tuple[list[Node], list[Node]] | None:
        updated = []
        failed = []

        if not self.current_config:
            logger.info("📦 No nodes in config")
            return None
        update_count = len(self.current_config)
        logger.info(f"📦 Updating {update_count} nodes:")
        print_list_tree(self.current_config)
        with Progress(total_steps=update_count) as p:
            for node in self.current_config:
                p.advance()
                if node.update() is False:
                    failed.append(node)
                else:
                    updated.append(node)
        return updated, failed

    @classmethod
    def update_all_nodes(cls) -> bool:
        logger.info("🔄 Updating all installed nodes...")
        try:
            exec_command([sys.executable, COMFYUI_MN_CLI, "update", "all"])
            logger.info(
                "✅ Successfully executed node update command. You may need to check actual node status."
            )
            return True
        except Exception:
            logger.error("❌ Failed to execute node update command")
            return False
