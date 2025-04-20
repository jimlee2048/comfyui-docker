
import re
import shutil
import sys
from pathlib import Path

from utils import compile_pattern, is_valid_git_repo, exec_command, exec_script, logger, Progress
from constants import BOOT_INIT_NODE_EXCLUDE, COMFYUI_MN_CLI, BOOT_POST_INSTALL_NODE_SCRIPTS


class NodeManager:
    def __init__(self, comfyui_path: Path):
        self.comfyui_path = comfyui_path
        self.progress = Progress()
        self.node_exclude = BOOT_INIT_NODE_EXCLUDE
        self.failed_list = []

    def is_node_exists(self, config: dict) -> bool:
        node_name = config["name"]
        node_source = config["source"]
        node_path = self.comfyui_path / "custom_nodes" / node_name
        if not node_path.exists():
            return False
        elif node_path.is_dir():
            if node_source == "git" and not is_valid_git_repo(node_path):
                logger.warning(f"⚠️ {node_name} invalid, removing: {node_path}")
                shutil.rmtree(node_path)
                return False
            return True
        elif node_path.is_file():
            logger.warning(f"⚠️ {node_name} invalid, removing: {node_path}")
            node_path.unlink()
            return False

    def setup_node(self, node_path: Path) -> bool:
        try:
            exec_command(
                [sys.executable, COMFYUI_MN_CLI, "post-install", str(node_path)],
                check=True,
            )
            logger.info(f"✅ Successfully initialized node: {node_path.name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize node {node_path.name}: {str(e)}")
            return False

    def install_node(self, config: dict) -> bool:
        try:
            node_name = config["name"]
            node_source = config["source"]
            node_path = self.comfyui_path / "custom_nodes" / node_name
            if node_name in self.node_exclude:
                self.progress.advance(
                    msg=f"⚠️ Not allowed to install excluded node: {node_name}",
                    style="warning",
                )
                return False
            if self.is_node_exists(config):
                self.progress.advance(
                    msg=f"ℹ️ {node_name} already exists. Skipped.", style="info"
                )
                return True
            self.progress.advance(msg=f"📦 Installing node: {node_name}", style="info")

            # install node from registry
            if node_source == "registry":
                node_version = config["version"]
                install_result = exec_command(
                    [
                        sys.executable,
                        COMFYUI_MN_CLI,
                        "install",
                        f"{node_name}@{node_version}",
                    ],
                    check=True,
                )
                # reference:original cm-cli.py output format
                # https://github.com/ltdrdata/ComfyUI-Manager/blob/411c0633a3d542ac20ea8cb47c9578f22fb19854/cm-cli.py#L162
                # check if error msg print exists
                ignore_errors = [
                    "PyTorch is not installed",
                    "pip's dependency resolver does not currently take into account all the packages that are installed",
                ]
                ignore_errors_pattern = (
                    f"(?!.*({'|'.join(re.escape(err) for err in ignore_errors)}))"
                )
                error_pattern = compile_pattern(
                    rf"ERROR:(?P<msg>{ignore_errors_pattern}.+)"
                )
                error_match = error_pattern.finditer(install_result.stdout)
                for error in error_match:
                    error_msg = error.group("msg").strip()
                    if "An error occurred while installing" in error_msg:
                        # try to get more detailed error message from next line
                        remaining_stdout = (
                            install_result.stdout[error.end() :].strip().splitlines()
                        )
                        next_line = remaining_stdout[0].strip()
                        error_msg = next_line if next_line else error_msg
                    raise Exception(f"{error_msg}")

                # check if installation result print exists
                result_pattern = compile_pattern(
                    r"1\/1\s\[(?P<result>.+?)\]\s(?P<msg>.+)"
                )
                result_match = result_pattern.search(install_result.stdout)
                if result_match:
                    result = result_match.group("result")
                    if result == "INSTALLED":
                        self.progress.print(
                            f"✅ Successfully installed node: {node_name}", style="info"
                        )
                    elif result == "SKIP":
                        self.progress.print(
                            f"ℹ️ {node_name} already exists. Skipped.", style="info"
                        )
                        return True
                    elif result == "ENABLED":
                        self.progress.print(
                            f"⚠️ {node_name} already exists. Enabled.", style="warning"
                        )
                        return True
                else:
                    raise Exception("Failed to parse installation result")
            # install node from git
            elif node_source == "git":
                node_url = config["url"]
                node_branch = config.get("branch", None)
                # use git command to clone repo
                if node_branch:
                    self.progress.print(f"⚠️ Cloning specific branch: {node_branch}")
                    exec_command(
                        ["git", "clone", "-b", node_branch, node_url, str(node_path)],
                        check=True,
                    )
                else:
                    exec_command(["git", "clone", node_url, str(node_path)], check=True)
                self.setup_node(node_path)
                self.progress.print(
                    f"✅ Successfully installed node: {node_name}", style="info"
                )
            else:
                raise Exception(f"Unsupported source: {node_source}")

            # execute post-install-node script
            if "script" in config:
                script = config["script"]
                logger.info(f"🛠️ Executing post-install-node script: {script}")
                exec_script(BOOT_POST_INSTALL_NODE_SCRIPTS / script)
            return True

        except Exception as e:
            logger.error(f"❌ Failed to install node {node_name}: {str(e)}")
            # try to remove node_path if exists
            if node_path.exists():
                logger.warning(f"⚠️ Removing failed installation: {node_name}")
                shutil.rmtree(node_path)
            return False

    def uninstall_node(self, config: dict) -> bool:
        try:
            node_name = config["name"]
            node_source = config["source"]
            if node_name in self.node_exclude:
                self.progress.advance(
                    msg=f"⚠️ Not allowed to uninstall excluded node: {node_name}",
                    style="warning",
                )
                return False
            if not self.is_node_exists(config):
                self.progress.advance(
                    msg=f"ℹ️ {node_name} not found. Skipped.", style="info"
                )
                return True
            self.progress.advance(msg=f"🗑️ Uninstalling node: {node_name}", style="info")
            # if nodes source from registry, try to use cm-cli process uninstalling first
            if node_source == "registry":
                exec_command(
                    [sys.executable, COMFYUI_MN_CLI, "uninstall", node_name], check=True
                )
            # check again if node exists
            possible_path = self.comfyui_path / "custom_nodes" / node_name
            if possible_path.exists():
                shutil.rmtree(possible_path)
            logger.info(f"✅ Uninstalled node: {node_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to uninstall node {node_name}: {str(e)}")
            return False

    def init_nodes(
        self, current_config: list[dict], prev_config: list[dict] = None
    ) -> bool:
        if not current_config:
            logger.info("📦 No nodes in config")
            return False

        if not prev_config:
            install_nodes = current_config
            uninstall_nodes = []
        else:
            install_nodes = [node for node in current_config if node not in prev_config]
            uninstall_nodes = [
                node for node in prev_config if node not in current_config
            ]

        if not install_nodes and not uninstall_nodes:
            logger.info("ℹ️ No changes in nodes")
            return False
        if install_nodes:
            install_count = len(install_nodes)
            logger.info(f"📦 Installing {install_count} nodes:")
            for node in install_nodes:
                logger.info(f"└─ {node['name']} ({node['source']})")
            self.progress.start(install_count)
            for node in install_nodes:
                if not self.install_node(node):
                    self.failed_list.append(node)
        if uninstall_nodes:
            uninstall_count = len(uninstall_nodes)
            logger.info(f"🗑️ Uninstalling {uninstall_count} nodes:")
            for node in uninstall_nodes:
                logger.info(f"└─ {node['name']}")
            self.progress.start(uninstall_count)
            for node in uninstall_nodes:
                if not self.uninstall_node(node):
                    self.failed_list.append(node)
        return True