import os
import sys
import subprocess
import shutil
import re
import time
from pathlib import Path
import tomllib
import urllib.parse
import json
import git
import giturlparse
import logging
from rich.console import Console
from rich.logging import RichHandler
from collections import defaultdict
import aria2p


console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, show_path=False)]
)
logger = logging.getLogger("boot")


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


def compile_pattern(pattern_str: str) -> re.Pattern:
    if not pattern_str:
        return None
    try:
        return re.compile(pattern_str)
    except re.error as e:
        logger.error(f"❌ Invalid regex pattern: {pattern_str}\n{str(e)}")
        return None


def json_default(obj):
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError


def exec_command(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    except subprocess.CalledProcessError as e:
        logger.error(f"{e.stdout}")
        logger.error(f"❌ Failed to execute command: {e.cmd}\n{e.stderr}")
        return e


# experimental: use subprocess.Popen to get real-time output
# reference: https://github.com/python/cpython/blob/main/Lib/subprocess.py#L514
# def exec_command(command: list[str], cwd: str = None, check: bool = False, **kwargs) -> subprocess.CompletedProcess:
#     stdout_output = ""
#     stderr_output = ""
#     with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd, **kwargs) as proc:
#         try:
#             for line in proc.stdout:
#                 logger.info(line.strip())
#                 stdout_output += line
#         except subprocess.TimeoutExpired as exc:
#             proc.kill()
#             if os.name == "nt":
#                 exc.stdout, exc.stderr = process.communicate()
#             else:
#                 proc.wait()
#             raise
#         except:
#             proc.kill()
#             raise
#         retcode = proc.poll()
#         if check and retcode:
#             raise subprocess.CalledProcessError(proc.returncode, command, output=stdout_output, stderr=stderr_output)
#     return subprocess.CompletedProcess(proc.args, proc.returncode, stdout_output, stderr_output)


def exec_script(script: Path, check: bool = None) -> int:
    if not script.is_file():
        logger.warning(f"⚠️ Invalid script path: {script}")
        return 1
    try:
        if script.suffix == ".py":
            interpreter = [sys.executable]
        elif script.suffix == ".sh" and os.name == "posix":
            interpreter = ["bash"]
        elif script.suffix in [".bat", ".ps1"] and os.name == "nt":
            interpreter = ["powershell", "-File"]
        else:
            logger.warning(f"⚠️ Unsupported script type: {script}. Skipped.")
            return 1
        cmd = interpreter + [str(script)]
        res = exec_command(cmd)
        returncode = res.returncode
        if returncode == 0:
            logger.info(f"✅ Successfully executed script: {script}")
            return returncode
        elif check:
            raise subprocess.CalledProcessError(returncode, cmd, output=res.stdout)
        else:
            logger.warning(f"⚠️ {script} exited with non-zero code: {returncode}")
            return returncode
    except subprocess.CalledProcessError as e:
        logger.error(f"{e.stdout}")
        logger.error(f"❌ Failed to execute script: {script}")
        return e.returncode
    except Exception as e:
        logger.error(f"❌ Failed to execute script: {script}\n{str(e)}")
        return 1


class BootProgress:
    def __init__(self):
        self.total_steps = 0
        self.current_step = 0
        self.log_level_info = "info"
        self.log_level_warning = "warning"
        self.log_level_error = "error"

    def start(self, total_steps: int):
        self.total_steps = total_steps
        self.current_step = 0

    def advance(self, msg: str = None, style: str = None):
        self.current_step += 1
        if msg:
            self.print(msg, style)

    def print(self, msg: str = None, style: str = None):
        overall_progress = f"[{self.current_step}/{self.total_steps}]"
        if msg is None:
            logger.info(f"{overall_progress}")
            return
        if style == self.log_level_info:
            logger.info(f"{overall_progress} {msg}")
        elif style == self.log_level_warning:
            logger.warning(f"{overall_progress} {msg}")
        elif style == self.log_level_error:
            logger.error(f"{overall_progress} {msg}")
        else:
            logger.info(f"{overall_progress} {msg}")


class BootConfigManager:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.node_exclude = INIT_NODE_EXCLUDE
        self.current_config = self.load_boot_config()
        self.prev_config = self.load_prev_config(BOOT_CONFIG_PREV_PATH)
        self.current_nodes = self.load_nodes_config(self.current_config)
        self.current_models = self.load_models_config(self.current_config)
        self.prev_nodes = self.load_nodes_config(self.prev_config)
        self.prev_models = self.load_models_config(self.prev_config)

    def _drop_duplicates_config(self, config: list[dict], cond_key: list[str]) -> tuple[list[dict], list[dict], int]:
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
        parsed_url = urllib.parse.urlparse(url)
        # check if url is valid
        if not parsed_url.netloc:
            raise Exception(f"Invalid URL: {url}")
        # chinese mainland network settings
        if CN_NETWORK:
            fr_map = {
                'huggingface.co': 'hf-mirror.com',
                'civitai.com': 'civitai.work'
            }
            if parsed_url.netloc in fr_map:
                url = parsed_url._replace(netloc=fr_map[parsed_url.netloc]).geturl()
        return url

    def load_boot_config(self) -> dict:

        config_dir = Path(self.config_dir)

        if config_dir.is_dir():
            logger.info(f"📂 Loading boot config from {self.config_dir}")
            config_files = list(config_dir.rglob("*.toml"))
        elif config_dir.is_file():
            logger.warning(f"⚠️ Invalid boot config detected, removing...")
            config_dir.unlink()
            return {}

        if BOOT_CONFIG_INCLUDE or BOOT_CONFIG_EXCLUDE:
            include_pattern = compile_pattern(BOOT_CONFIG_INCLUDE)
            exclude_pattern = compile_pattern(BOOT_CONFIG_EXCLUDE)
            filtered_files = [
                f for f in config_files
                if (not include_pattern or include_pattern.search(f.name)) and
                (not exclude_pattern or not exclude_pattern.search(f.name))
            ]
            if include_pattern:
                logger.info(f"⚡ Include filter: {BOOT_CONFIG_INCLUDE}")
            if exclude_pattern:
                logger.info(f"⚡ Exclude filter: {BOOT_CONFIG_EXCLUDE}")
            config_files = filtered_files

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
            logger.warning(f"⚠️ Invalid previous config detected, removing...")
            shutil.rmtree(prev_path)
        else:
            logger.info(f"ℹ️ No previous config found")
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
        nodes_config = boot_config.get('custom_nodes', [])
        if not nodes_config:
            return []

        for node in nodes_config.copy():
            try:
                # source: registry
                if 'node_id' in node:
                    node['source'] = "registry"
                    node['name'] = node['node_id']
                    # use 'latest' as default version
                    if 'version' not in node:
                        node['version'] = "latest"
                # source: git
                elif 'url' in node:
                    node['source'] = "git"
                    node['url'] = self._preprocess_url(node['url'])
                    node_repo = giturlparse.parse(node['url'])
                    # validate git url
                    if not node_repo.valid:
                        raise Exception(f"Invalid git URL: {node['url']}")
                    node['name'] = node_repo.name.lower()
                else:
                    raise Exception("None of 'node_id' or 'url' found in node config")
                if node['name'] in self.node_exclude:
                    logger.warning(f"⚠️ Skip excluded node: {node['name']}")
                    nodes_config.remove(node)
                    continue
            except KeyError as e:
                logger.warning(f"⚠️ Invalid node config: {str(e)}\n{node}")
                continue

        # drop duplicates
        nodes_config, duplicates = self._drop_duplicates_config(nodes_config, ['name'])
        if duplicates:
            logger.warning(f"⚠️ Found {len(duplicates)} duplicate nodes:")
            for node in duplicates:
                logger.warning(f"└─ {node['name']}")

        return nodes_config

    def load_models_config(self, boot_config: dict) -> list[dict]:
        models_config = boot_config.get('models', [])
        if not models_config:
            return []

        for model in models_config.copy():
            try:
                model['url'] = self._preprocess_url(model['url'])
                model['path'] = str(COMFYUI_PATH / model['dir'] / model['filename'])
            except KeyError as e:
                logger.warning(f"⚠️ Invalid model config: {model}\n{str(e)}")
                continue

        # drop duplicates
        models_config, duplicates = self._drop_duplicates_config(models_config, ['path'])
        if duplicates:
            logger.warning(f"⚠️ Found {len(duplicates)} duplicate models:")
            for model in duplicates:
                logger.warning(f"└─ {model['filename']}")

        return models_config


class NodeManager:
    def __init__(self, comfyui_path: Path):
        self.comfyui_path = comfyui_path
        self.progress = BootProgress()
        self.node_exclude = INIT_NODE_EXCLUDE
        self.failed_list = []

    def _is_valid_git_repo(self, path: str) -> bool:
        try:
            _ = git.Repo(path).git_dir
            return True
        except Exception as e:
            return False

    def is_node_exists(self, config: dict) -> bool:
        node_name = config['name']
        node_source = config['source']
        node_path = self.comfyui_path / "custom_nodes" / node_name
        if not node_path.exists():
            return False
        elif node_path.is_dir():
            if node_source == "git" and not self._is_valid_git_repo(node_path):
                logger.warning(f"⚠️ {node_name} invalid, removing: {node_path}")
                shutil.rmtree(node_path)
                return False
            return True
        elif node_path.is_file():
            logger.warning(f"⚠️ {node_name} invalid, removing: {node_path}")
            node_path.unlink()
            return False

    def install_node(self, config: dict) -> bool:
        try:
            node_name = config['name']
            node_source = config['source']
            node_path = self.comfyui_path / "custom_nodes" / node_name
            if node_name in self.node_exclude:
                self.progress.advance(msg=f"⚠️ Not allowed to install excluded node: {node_name}", style="warning")
                return False
            if self.is_node_exists(config):
                self.progress.advance(msg=f"ℹ️ {node_name} already exists. Skipped.", style="info")
                return True
            self.progress.advance(msg=f"📦 Installing node: {node_name}", style="info")

            # install node from registry
            if node_source == "registry":
                node_version = config['version']
                install_result = exec_command([sys.executable, COMFYUI_MN_CLI, "install", f"{node_name}@{node_version}"], check=True)

                # reference:original cm-cli.py output format
                # https://github.com/ltdrdata/ComfyUI-Manager/blob/411c0633a3d542ac20ea8cb47c9578f22fb19854/cm-cli.py#L162
                # check if error msg print exists
                ignore_errors = [
                    "PyTorch is not installed",
                    "pip's dependency resolver does not currently take into account all the packages that are installed"
                ]
                ignore_errors_pattern = f"(?!.*({'|'.join(re.escape(err) for err in ignore_errors)}))"
                error_pattern = compile_pattern(rf"ERROR:(?P<msg>{ignore_errors_pattern}.+)")
                error_match = error_pattern.finditer(install_result.stdout)
                for error in error_match:
                    error_msg = error.group("msg").strip()
                    if "An error occurred while installing" in error_msg:
                        # try to get more detailed error message from next line
                        remaining_stdout = install_result.stdout[error.end():].strip().splitlines()
                        next_line = remaining_stdout[0].strip()
                        error_msg = next_line if next_line else error_msg
                    raise Exception(f"{error_msg}")

                # check if installation result print exists
                result_pattern = compile_pattern(r"1\/1\s\[(?P<result>.+?)\]\s(?P<msg>.+)")
                result_match = result_pattern.search(install_result.stdout)
                if result_match:
                    result = result_match.group("result")
                    if result == "INSTALLED":
                        self.progress.print(f"✅ Successfully installed node: {node_name}", style="info")
                    elif result == "SKIP":
                        self.progress.print(f"ℹ️ {node_name} already exists. Skipped.", style="info")
                        return True
                    elif result == "ENABLED":
                        self.progress.print(f"⚠️ {node_name} already exists. Enabled.", style="warning")
                        return True
                else:
                    raise Exception(f"Failed to parse installation result")
            # install node from git
            elif node_source == "git":
                node_url = config['url']
                # use git command to clone repo
                exec_command(["git", "clone", node_url, str(node_path)], check=True)
                # use cm_cli.py to init node
                install_result = exec_command([sys.executable, COMFYUI_MN_CLI, "post-install", str(node_path)], check=True)
                self.progress.print(f"✅ Successfully installed node: {node_name}", style="info")
            else:
                raise Exception(f"Unsupported source: {node_source}")

            # execute post-install-node script
            if 'script' in config:
                script = config['script']
                logger.info(f"🛠️ Executing post-install-node script: {script}")
                exec_script(POST_INSTALL_NODE_SCRIPTS / script)
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
            node_name = config['name']
            node_source = config['source']
            if node_name in self.node_exclude:
                self.progress.advance(msg=f"⚠️ Not allowed to uninstall excluded node: {node_name}", style="warning")
                return False
            if not self.is_node_exists(config):
                self.progress.advance(msg=f"ℹ️ {node_name} not found. Skipped.", style="info")
                return True
            self.progress.advance(msg=f"🗑️ Uninstalling node: {node_name}", style="info")
            # if nodes source from registry, try to use cm-cli process uninstalling first
            if node_source == "registry":
                exec_command([sys.executable, COMFYUI_MN_CLI, "uninstall", node_name], check=True)
            # check again if node exists
            possible_path = self.comfyui_path / "custom_nodes" / node_name
            if possible_path.exists():
                shutil.rmtree(possible_path)
            logger.info(f"✅ Uninstalled node: {node_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to uninstall node {node_name}: {str(e)}")
            return False

    def init_nodes(self, current_config: list[dict], prev_config: list[dict] = None) -> bool:
        if not current_config:
            logger.info(f"📦 No nodes in config")
            return False

        if not prev_config:
            install_nodes = current_config
            uninstall_nodes = []
        else:
            install_nodes = [node for node in current_config if node not in prev_config]
            uninstall_nodes = [node for node in prev_config if node not in current_config]

        if not install_nodes and not uninstall_nodes:
            logger.info(f"ℹ️ No changes in nodes")
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


class ModelManager:
    def __init__(self, comfyui_path: Path):
        self.comfyui_path = comfyui_path
        self.progress = BootProgress()
        self.failed_list = []
        self.aria2 = aria2p.API(
            aria2p.Client(
                host="http://localhost",
                port=6800,
                secret=""
            )
        )
        self._start_aria2c()

    def _start_aria2c(self):
        logger.info(f"🚀 Starting aria2c...")
        try:
            subprocess.run([
                "aria2c",
                "--daemon=true",
                "--enable-rpc",
                "--rpc-listen-port=6800",
                "--max-concurrent-downloads=1",
                "--max-connection-per-server=16",
                "--split=16",
                "--continue=true",
                "--disable-ipv6=true",
            ], check=True)
            # sleep a while to ensure aria2c is ready
            time.sleep(2)

            # check if aria2c is ready
            max_retries = 3
            for _ in range(max_retries):
                try:
                    self.aria2.get_stats()
                    logger.info(f"✅ aria2c is ready")
                    break
                except Exception as e:
                    logger.warning(f"⚠️ aria2c still not ready, retrying...")
                    time.sleep(2)
            else:
                raise Exception(f"aria2c is not ready after {max_retries} retries")

            # purge all completed, removed or failed downloads from the queue
            self.aria2.purge()

            # set os env COMFYUI_MANAGER_ARIA2_SERVER and COMFYUI_MANAGER_ARIA2_SECRET
            os.environ['COMFYUI_MANAGER_ARIA2_SERVER'] = "http://localhost:6800/jsonrpc"
            os.environ['COMFYUI_MANAGER_ARIA2_SECRET'] = ""
        except Exception as e:
            logger.error(f"❌ Failed to start aria2c: {str(e)}")

    def _is_huggingface_url(self, url: str) -> bool:
        parsed_url = urllib.parse.urlparse(url)
        return parsed_url.netloc in ["hf.co", "huggingface.co", "huggingface.com", "hf-mirror.com"]

    def _is_civitai_url(self, url: str) -> bool:
        parsed_url = urllib.parse.urlparse(url)
        return parsed_url.netloc in ["civitai.com", "civitai.work"]

    def is_model_exists(self, config: dict) -> bool:
        model_path = Path(config['path'])
        model_dir = model_path.parent
        model_filename = config['filename']

        # remove huggingface cache
        if (model_dir / ".cache").exists():
            logger.warning(f"⚠️ Found cache directory: {str(model_dir)}, removing...")
            shutil.rmtree(model_dir / ".cache")

        # check if previous download cache exists
        previous_download_cache = model_dir / (model_filename + ".aria2")
        previous_download_exists = previous_download_cache.exists()
        if previous_download_exists:
            logger.warning(f"⚠️ Found previous download cache: {str(previous_download_cache)}, removing...")
            previous_download_cache.unlink()

        if model_path.exists():
            if previous_download_exists:
                logger.warning(f"⚠️ {model_filename} download incomplete, removing...")
                model_path.unlink()
                return False
            if model_path.is_file():
                return True
            elif model_path.is_dir():
                logger.warning(f"⚠️ {model_filename} invalid, removing: {model_path}")
                shutil.rmtree(model_path)
        return False

    def download_model(self, config: dict) -> bool:
        model_url = config['url']
        model_dir = config['dir']
        model_filename = config['filename']

        if self.is_model_exists(config):
            self.progress.advance(msg=f"ℹ️ {model_filename} already exists in {model_dir}. Skipped.", style="info")
            return True

        self.progress.advance(msg=f"⬇️ Downloading: {model_filename} -> {model_dir}", style="info")
        download_options = defaultdict(str)
        download_options['dir'] = str(self.comfyui_path / model_dir)
        download_options['out'] = model_filename

        for attempt in range(1, 4):
            try:
                download = self.aria2.add_uris([model_url], download_options)
                while not download.is_complete:
                    download.update()
                    if download.status == "error":
                        download.remove(files=True)
                        raise Exception(f"{download.error_message}")
                    if download.status == "removed":
                        raise Exception(f"Download was removed")
                    self.progress.print(f"{model_filename}: {download.progress_string()} | {download.completed_length_string()}/{download.total_length_string()} [{download.eta_string()}, {download.download_speed_string()}]", "info")
                    time.sleep(1)
                logger.info(f"✅ Downloaded: {model_filename} -> {model_dir}")
                return True
            except Exception as e:
                e_msg = str(e)
                self.progress.print(f"⚠️ Download attempt {attempt} failed: {e_msg}", "warning")
                # if HTTP authorization failed, try to add authorization info
                if "authorization failed" in e_msg.lower():
                    # hugingface: auth header
                    if attempt == 1 and self._is_huggingface_url(model_url) and HF_API_TOKEN:
                        download_options['header'] = f"Authorization: Bearer {HF_API_TOKEN}"
                        self.progress.print(f"🔑 Retrying with provided HF_API_TOKEN", "info")
                    # civitai: query token
                    elif attempt == 1 and self._is_civitai_url(model_url) and CIVITAI_API_TOKEN:
                        parts = urllib.parse.urlsplit(model_url)
                        query = dict(urllib.parse.parse_qsl(parts.query))
                        query['token'] = CIVITAI_API_TOKEN
                        model_url = parts._replace(query=urllib.parse.urlencode(query)).geturl()
                        self.progress.print(f"🔑 Retrying with provided CIVITAI_API_TOKEN", "info")
                    else:
                        self.progress.print(f"❌ Authorization failed for {model_url}. Skipped.", "error")
                        return False

        logger.error(f"❌ Exceeded max retries: {model_filename} -> {model_dir}")
        return False

    def move_model(self, src: Path, dst: Path) -> bool:
        try:
            self.progress.advance(msg=f"📦 Moving: {src} -> {dst}", style="info")
            src.rename(dst)
            return True
        except Exception as e:
            logger.error(f"❌ Failed to move model: {src} -> {dst}\n{str(e)}")
            return False

    def remove_model(self, config: dict) -> bool:
        try:
            model_path = Path(config['path'])
            model_filename = config['filename']
            if not self.is_model_exists(config):
                self.progress.advance(msg=f"ℹ️ {model_filename} not found in path: {model_path}. Skipped.", style="info")
                return True
            self.progress.advance(msg=f"🗑️ Removing model: {model_filename}", style="info")
            model_path.unlink()
            logger.info(f"✅ Removed model: {model_filename}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to remove model {model_filename}: {str(e)}")
            return False

    def init_models(self, current_config: list, prev_config: list = None) -> bool:
        if not current_config:
            logger.info(f"📦 No models in config")
            return False

        models_to_download = []
        models_to_move = []
        models_to_remove = []
        if not prev_config:
            models_to_download = current_config
        else:
            for model in current_config:
                if model not in prev_config:
                    models_to_download.append(model)
                else:
                    prev_model = next((m for m in prev_config if m['url'] == model['url']), None)
                    prev_path = Path(prev_model['path'])
                    current_path = Path(model['path'])
                    if current_path != prev_path:
                        models_to_move.append({"src": prev_path, "dst": current_path})
            for prev_model in prev_config:
                if not any(model['url'] == prev_model['url'] for model in current_config):
                    models_to_remove.append(prev_model)

        if not models_to_download and not models_to_move and not models_to_remove:
            logger.info(f"ℹ️ No changes in models")
            return False
        if models_to_download:
            download_count = len(models_to_download)
            logger.info(f"⬇️ Downloading {download_count} models:")
            for model in models_to_download:
                logger.info(f"└─ {model['filename']}")
            self.progress.start(download_count)
            for model in models_to_download:
                if not self.download_model(model):
                    self.failed_list.append(model)
        if models_to_move:
            move_count = len(models_to_move)
            logger.info(f"📦 Moving {move_count} models:")
            for model in models_to_move:
                logger.info(f"└─ {model['src']} -> {model['dst']}")
            self.progress.start(move_count)
            for model in models_to_move:
                if not self.move_model(model['src'], model['dst']):
                    self.failed_list.append(model)
        if models_to_remove:
            remove_count = len(models_to_remove)
            logger.info(f"🗑️ Removing {remove_count} models:")
            for model in models_to_remove:
                logger.info(f"└─ {model['filename']}")
            self.progress.start(remove_count)
            for model in models_to_remove:
                if not self.remove_model(model):
                    self.failed_list.append(model)
        return True


class ComfyUIInitializer:
    def __init__(self, boot_config: Path = None, comfyui_path: Path = None, pre_init_scripts: Path = None, post_init_scripts: Path = None):
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
        progress = BootProgress()
        progress.start(scripts_count)
        for script in scripts:
            progress.advance(msg=f"🛠️ Executing {dir.name} script: {script.name}", style="info")
            exec_script(script)
        return True

    def run(self):
        # execute pre-init scripts
        if self.pre_scripts_dir.is_dir():
            logger.info(f"🛠️ Scanning pre-init scripts...")
            self._exec_scripts_in_dir(self.pre_scripts_dir)
        elif self.pre_scripts_dir.is_file():
            logger.warning(f"⚠️ {self.pre_scripts_dir} invalid, removing...")
            self.pre_scripts_dir.unlink()
        # init nodes and models
        failed_config = defaultdict(list)
        if self.current_config and INIT_NODE:
            node_manager = NodeManager(self.comfyui_path)
            node_manager.init_nodes(self.current_nodes, self.prev_nodes)
            failed_config['custom_nodes'] = node_manager.failed_list
        if self.current_config and INIT_MODEL:
            model_manager = ModelManager(self.comfyui_path)
            model_manager.init_models(self.current_models, self.prev_models)
            failed_config['models'] = model_manager.failed_list
        # execute post init scripts
        if self.post_scripts_dir.is_dir():
            logger.info(f"🛠️ Scanning post-init scripts...")
            self._exec_scripts_in_dir(self.post_scripts_dir)
        elif self.post_scripts_dir.is_file():
            logger.warning(f"⚠️ {self.post_scripts_dir} invalid, removing...")
            self.post_scripts_dir.unlink()

        # check if any failed config
        if failed_config['custom_nodes']:
            logger.error(f"❌ Failed to init {len(failed_config['custom_nodes'])} nodes, will retry on next boot:")
            for node in failed_config['custom_nodes']:
                logger.error(f"└─ {node['name']}")
        if failed_config['models']:
            logger.error(f"❌ Failed to init {len(failed_config['models'])} models, will retry on next boot:")
            for model in failed_config["models"]:
                logger.error(f"└─ {model['filename']}")
        # cache succeeded config
        # successed config = current config - failed config
        succeeded_config = defaultdict(list)
        for key, items in self.current_config.items():
            if key == "custom_nodes":
                succeeded_config[key] = [node for node in items if node not in failed_config['custom_nodes']]
            elif key == "models":
                succeeded_config[key] = [model for model in items if model not in failed_config["models"]]
        self.config_loader.write_config_cache(BOOT_CONFIG_PREV_PATH, succeeded_config)

        # launch comfyui
        logger.info(f"🚀 Launching ComfyUI...")
        launch_args_list = ["--listen", "0.0.0.0,::", "--port", "8188"] + (COMFYUI_EXTRA_ARGS.split() if COMFYUI_EXTRA_ARGS else [])
        subprocess.run([sys.executable, str(self.comfyui_path / "main.py")] + launch_args_list, check=False)


if __name__ == '__main__':
    logger.info(f"Starting boot process")

    # Environment variables
    WORKDIR = Path(os.environ.get('WORKDIR', "/workspace"))
    COMFYUI_PATH = Path(os.environ.get('COMFYUI_PATH', None)) or WORKDIR / "comfyui"
    COMFYUI_MN_PATH = Path(os.environ.get('COMFYUI_MN_PATH', None)) or COMFYUI_PATH / "custom_nodes" / "comfyui-manager"
    COMFYUI_MN_CLI = str(COMFYUI_MN_PATH / "cm-cli.py")
    BOOT_CONFIG_DIR = WORKDIR / "boot_config"
    BOOT_CONFIG_PREV_PATH = WORKDIR / ".cache" / "boot_config.prev.json"
    SCRIPTS_DIR = WORKDIR / "scripts"
    PRE_INIT_SCRIPTS = SCRIPTS_DIR / "pre-init"
    POST_INSTALL_NODE_SCRIPTS = SCRIPTS_DIR / "post-install-node"
    POST_INIT_SCRIPTS = SCRIPTS_DIR / "post-init"

    HF_API_TOKEN = os.environ.get('HF_API_TOKEN', None)
    CIVITAI_API_TOKEN = os.environ.get('CIVITAI_API_TOKEN', None)
    COMFYUI_EXTRA_ARGS = os.environ.get('COMFYUI_EXTRA_ARGS', None)

    BOOT_CONFIG_INCLUDE = os.environ.get('BOOT_CONFIG_INCLUDE', None)
    BOOT_CONFIG_EXCLUDE = os.environ.get('BOOT_CONFIG_EXCLUDE', None)
    INIT_NODE = get_bool_env('INIT_NODE', True)
    INIT_NODE_EXCLUDE = {"comfyui-manager"}
    INIT_MODEL = get_bool_env('INIT_MODEL', True)
    CN_NETWORK = get_bool_env('CN_NETWORK', False)

    # check if comfyui path exists
    if not COMFYUI_PATH.is_dir():
        logger.error(f"❌ Invalid ComfyUI path: {COMFYUI_PATH}")
        exit(1)

    # chinese mainland network settings
    if CN_NETWORK:
        logger.info(f"🌐 Using CN network optimization")
        # pip source to ustc mirror
        os.environ['PIP_INDEX_URL'] = 'https://mirrors.ustc.edu.cn/pypi/web/simple'
        # huggingface endpoint to hf-mirror.com
        os.environ['HF_ENDPOINT'] = "https://hf-mirror.com"
        if HF_API_TOKEN:
            logger.warning(f"⚠️ HF_API_TOKEN will be sent to hf-mirror.com")
        if CIVITAI_API_TOKEN:
            logger.warning(f"⚠️ CIVITAIAPI_TOKEN will be sent to civitai.work")

    app = ComfyUIInitializer(BOOT_CONFIG_DIR, COMFYUI_PATH, PRE_INIT_SCRIPTS, POST_INIT_SCRIPTS)
    logger.info(f"Initializing ComfyUI...")
    app.run()
