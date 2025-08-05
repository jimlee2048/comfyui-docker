import logging
import os
import re
import subprocess
import sys
import time
import urllib
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

import aria2p
import git

from .constants import (
    CIVITAI_ENDPOINT_NETLOC,
    CN_NETWORK,
    COMFYUI_MN_CLI,
    HF_ENDPOINT_NETLOC,
    LOG_LEVEL,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=LOG_LEVEL, format="%(message)s", datefmt="[%X]")


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


def preprocess_url(url: str) -> str:
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


def is_valid_git_path(path: str) -> bool:
    try:
        _ = git.Repo(path).git_dir
        return True
    except Exception:
        return False


def is_huggingface_url(url: str) -> bool:
    parsed_url = urllib.parse.urlparse(url)
    return parsed_url.netloc in [
        "hf.co",
        "huggingface.co",
        "huggingface.com",
        "hf-mirror.com",
    ]


def is_civitai_url(url: str) -> bool:
    parsed_url = urllib.parse.urlparse(url)
    return parsed_url.netloc in ["civitai.com", "civitai.work"]


def url_add_query_param(url: str, key: str, value: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query[key] = value
    return parts._replace(query=urllib.parse.urlencode(query)).geturl()


def move_file(src: Path, dst: Path) -> bool | None:
    if not src.exists():
        logger.warning(f"⚠️ {src} not found. Skipped.")
        return None
    if dst.exists():
        logger.warning(f"⚠️ {dst} already exists. Skipped.")
        return None
    if src == dst:
        logger.warning("⚠️ Source and destination are the same. Skipped.")
        return None
    try:
        logger.info(f"📦 Moving file: {src} -> {dst}")
        src.rename(dst)
    except Exception as e:
        logger.error(f"❌ Failed to move file: {src} -> {dst}\n{str(e)}")
        return False
    logger.info(f"✅ Moved file: {src} -> {dst}")
    return True


# experimental: use subprocess.Popen to get real-time output
# reference: https://github.com/python/cpython/blob/main/Lib/subprocess.py#L514
def exec_command(
    command: list[str], check=False, **kwargs
) -> subprocess.CompletedProcess:
    stdout_output = ""
    stderr_output = ""
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs
    ) as proc:
        try:
            for line in proc.stdout:
                logger.info(line.strip())
                stdout_output += line
        except Exception:
            proc.kill()
            raise
        retcode = proc.poll()
        if check and retcode:
            raise subprocess.CalledProcessError(
                proc.returncode, command, output=stdout_output, stderr=stderr_output
            )
    return subprocess.CompletedProcess(
        proc.args, proc.returncode, stdout_output, stderr_output
    )


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


def exec_scripts_in_dir(dir: Path) -> bool:
    if not dir.is_dir():
        logger.warning(f"⚠️ {dir} is not a valid directory.")
        return False

    script_patterns = []
    if os.name == "posix":
        script_patterns = ["*.py", "*.sh"]
    elif os.name == "nt":
        script_patterns = ["*.py", "*.bat", "*.ps1"]
    else:
        script_patterns = ["*.py"]

    queue: list[Path] = []
    for pattern in script_patterns:
        queue.extend(dir.glob(pattern))
    queue = sorted(queue)
    if not queue:
        logger.info(f"ℹ️ No supported scripts found in {dir.name}.")
        return False

    queue_length = len(queue)
    logger.info(f"🛠️ Found {queue_length} scripts in {dir.name}:")
    for script in queue:
        logger.info(f"└─ {script.name}")

    succeed = []
    failed = []
    with Progress(total_steps=queue_length) as p:
        for script in queue:
            p.advance()
            logger.info(f"🛠️ Executing script in {dir.name}: {script.name}")
            returncode = exec_script(script)
            if returncode == 0:
                succeed.append(script.name)
            else:
                logger.warning(f"⚠️ Script {script.name} failed with code {returncode}")
                failed.append(script.name)

    if not failed:
        logger.info(f"✅ All {len(succeed)} scripts in {dir.name} succeeded.")
        return True
    elif not succeed:
        logger.error(f"❌ All {len(failed)} scripts in {dir.name} failed.")
        return False
    else:
        logger.warning(f"⚠️ {len(failed)} scripts in {dir.name} failed.")
        return True


def exec_cm_cli(
    command: str,
    args: list[str] = None,
    **kwargs,
) -> subprocess.CompletedProcess:
    if args is None:
        args = []
    return exec_command([sys.executable, COMFYUI_MN_CLI, command] + args, **kwargs)


def filter_path_list(
    list: list[Path], include_pattern: str = None, exclude_pattern: str = None
) -> list[Path]:
    if include_pattern:
        include_pattern = compile_pattern(include_pattern)
        list = [path for path in list if include_pattern.search(str(path))]
    if exclude_pattern:
        exclude_pattern = compile_pattern(exclude_pattern)
        list = [path for path in list if not exclude_pattern.search(str(path))]
    return list


def print_list_tree(list: list) -> None:
    for item in list:
        logger.info(f"└─ {str(item)}")


class Progress:
    def __init__(self, total_steps: int, logger: logging.Logger = logger):
        self.logger = logger
        self.total_steps = total_steps
        self.current_step = 0
        self.logger = logger
        self._original_methods = {}
        self.patch_levels = self._get_available_log_levels()

    def __enter__(self):
        # save original logger methods
        for level in self.patch_levels:
            self._original_methods[level] = getattr(self.logger, level)
        # patch logger methods
        for level in self.patch_levels:
            wrapped_method = partial(
                self._log_with_progress, original_log_func=self._original_methods[level]
            )
            setattr(self.logger, level, wrapped_method)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # restore original logger methods
        for level in self.patch_levels:
            if level in self._original_methods:
                setattr(self.logger, level, self._original_methods[level])

    def _get_available_log_levels(self):
        available_levels = []
        level_names = logging.getLevelNamesMapping().keys()
        for level_name in level_names:
            method_name = level_name.lower()
            if hasattr(self.logger, method_name) and callable(
                getattr(self.logger, method_name)
            ):
                available_levels.append(method_name)
        return available_levels

    def _log_with_progress(self, msg: str, *args, original_log_func, **kwargs):
        progress_prefix = f"[{self.current_step}/{self.total_steps}]"
        new_msg = f"{progress_prefix} {msg}"
        original_log_func(new_msg, *args, **kwargs)

    def advance(self) -> None:
        if self.current_step < self.total_steps:
            self.current_step += 1


class Downloader:
    def __init__(self):
        self.aria2 = self._launch_aria2c()

    def _check_aria2c(
        self,
        aria2: aria2p.API,
        max_retries: int = 3,
        retries_interval: int = 2,
    ):
        if not isinstance(aria2, aria2p.API):
            return False
        for _ in range(max_retries):
            try:
                aria2.get_stats()
                return True
            except Exception:
                time.sleep(retries_interval)
        return False

    def _launch_aria2c(self, port: int = 6800):
        aria2 = aria2p.API(aria2p.Client(host="http://localhost", port=port, secret=""))
        # check if aria2c is already running
        if self._check_aria2c(aria2, max_retries=0):
            logger.info("✅ aria2c is already running")
            return aria2
        # if not, try to launch aria2c
        logger.info("🚀 Launching aria2c...")
        try:
            subprocess.run(
                [
                    "aria2c",
                    "--daemon=true",
                    "--enable-rpc",
                    f"--rpc-listen-port={port}",
                    "--max-concurrent-downloads=1",
                    "--max-connection-per-server=16",
                    "--split=16",
                    "--continue=true",
                    "--disable-ipv6=true",
                ],
                check=True,
            )
            # sleep a while to ensure aria2c is ready
            time.sleep(2)
            # check if aria2c is ready
            if not self._check_aria2c(aria2):
                raise RuntimeError("Failed to connect to aria2c after launching.")
            # purge all completed, removed or failed downloads from the queue
            aria2.purge()
            return aria2
        except Exception as e:
            logger.error(f"❌ Failed to launch aria2c: {str(e)}")
            raise e

    def download(
        self,
        url: str,
        filename: str,
        dir: str,
        header: str = None,
        max_retries: int = 3,
        retries_interval: int = 2,
    ):
        download_options = {"dir": dir, "out": filename}
        if header:
            download_options["header"] = header

        for attempt in range(max_retries):
            try:
                download = self.aria2.add_uris([url], download_options)
                # print download progress
                while not download.is_complete:
                    download.update()
                    if download.status == "error":
                        download.remove(files=True)
                        raise Exception(f"{download.error_message}")
                    if download.status == "removed":
                        raise Exception("Download was removed")
                    logger.info(
                        f"{filename}: {download.progress_string()} | {download.completed_length_string()}/{download.total_length_string()} [{download.eta_string()}, {download.download_speed_string()}]"
                    )
                    time.sleep(1)
                logger.info(f"✅ Downloaded: {filename} -> {dir}")
                return True
            except Exception as e:
                e_msg = str(e)
                logger.error(f"❌ Failed to download {filename}: {e_msg}")
                # if authorization failed, abort
                if "authorization failed" in e_msg.lower():
                    logger.warning(
                        "⚠️ Please check your token in environment variables."
                    )
                    return False
                # if max retries reached, abort
                elif attempt == max_retries - 1:
                    break
                # retry
                else:
                    logger.warning(
                        f"⚠️ Retrying in {retries_interval} seconds... ({attempt + 1}/{max_retries})"
                    )
                    time.sleep(retries_interval)
        logger.error("❌ Max retries reached, abort.")
        return False
