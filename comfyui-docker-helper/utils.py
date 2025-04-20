import logging
import os
import sys
import re
import subprocess
from pathlib import Path

import git
from rich.console import Console
from rich.logging import RichHandler

console = Console(width=160, log_path=False)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, show_path=False)],
)
logger = logging.getLogger("boot")



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

def is_valid_git_repo(path: str) -> bool:
    try:
        _ = git.Repo(path).git_dir
        return True
    except Exception:
        return False

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

class Progress:
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
