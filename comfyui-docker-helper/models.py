import os
import shutil
import subprocess
import time
import urllib
from collections import defaultdict
from pathlib import Path
import aria2p

from constants import HF_API_TOKEN, CIVITAI_API_TOKEN
from utils import logger, Progress


class ModelManager:
    def __init__(self, comfyui_path: Path):
        self.comfyui_path = comfyui_path
        self.progress = Progress()
        self.failed_list = []
        self.aria2 = aria2p.API(
            aria2p.Client(host="http://localhost", port=6800, secret="")
        )
        self._start_aria2c()

    def _start_aria2c(self):
        logger.info("🚀 Starting aria2c...")
        try:
            subprocess.run(
                [
                    "aria2c",
                    "--daemon=true",
                    "--enable-rpc",
                    "--rpc-listen-port=6800",
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
            max_retries = 3
            for _ in range(max_retries):
                try:
                    self.aria2.get_stats()
                    logger.info("✅ aria2c is ready")
                    break
                except Exception:
                    logger.warning("⚠️ aria2c still not ready, retrying...")
                    time.sleep(2)
            else:
                raise Exception(f"aria2c is not ready after {max_retries} retries")

            # purge all completed, removed or failed downloads from the queue
            self.aria2.purge()

            # set os env COMFYUI_MANAGER_ARIA2_SERVER and COMFYUI_MANAGER_ARIA2_SECRET
            os.environ["COMFYUI_MANAGER_ARIA2_SERVER"] = "http://localhost:6800/jsonrpc"
            os.environ["COMFYUI_MANAGER_ARIA2_SECRET"] = ""
        except Exception as e:
            logger.error(f"❌ Failed to start aria2c: {str(e)}")

    def _is_huggingface_url(self, url: str) -> bool:
        parsed_url = urllib.parse.urlparse(url)
        return parsed_url.netloc in [
            "hf.co",
            "huggingface.co",
            "huggingface.com",
            "hf-mirror.com",
        ]

    def _is_civitai_url(self, url: str) -> bool:
        parsed_url = urllib.parse.urlparse(url)
        return parsed_url.netloc in ["civitai.com", "civitai.work"]

    def is_model_exists(self, config: dict) -> bool:
        model_path = Path(config["path"])
        model_dir = model_path.parent
        model_filename = config["filename"]

        # remove huggingface cache
        if (model_dir / ".cache").exists():
            logger.warning(f"⚠️ Found cache directory: {str(model_dir)}, removing...")
            shutil.rmtree(model_dir / ".cache")

        # check if previous download cache exists
        previous_download_cache = model_dir / (model_filename + ".aria2")
        previous_download_exists = previous_download_cache.exists()
        if previous_download_exists:
            logger.warning(
                f"⚠️ Found previous download cache: {str(previous_download_cache)}, removing..."
            )
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
        model_url = config["url"]
        model_dir = config["dir"]
        model_filename = config["filename"]

        if self.is_model_exists(config):
            self.progress.advance(
                msg=f"ℹ️ {model_filename} already exists in {model_dir}. Skipped.",
                style="info",
            )
            return True

        self.progress.advance(
            msg=f"⬇️ Downloading: {model_filename} -> {model_dir}", style="info"
        )
        download_options = defaultdict(str)
        download_options["dir"] = str(self.comfyui_path / model_dir)
        download_options["out"] = model_filename

        for attempt in range(1, 4):
            try:
                download = self.aria2.add_uris([model_url], download_options)
                while not download.is_complete:
                    download.update()
                    if download.status == "error":
                        download.remove(files=True)
                        raise Exception(f"{download.error_message}")
                    if download.status == "removed":
                        raise Exception("Download was removed")
                    self.progress.print(
                        f"{model_filename}: {download.progress_string()} | {download.completed_length_string()}/{download.total_length_string()} [{download.eta_string()}, {download.download_speed_string()}]",
                        "info",
                    )
                    time.sleep(1)
                logger.info(f"✅ Downloaded: {model_filename} -> {model_dir}")
                return True
            except Exception as e:
                e_msg = str(e)
                self.progress.print(
                    f"⚠️ Download attempt {attempt} failed: {e_msg}", "warning"
                )
                # if HTTP authorization failed, try to add authorization info
                if "authorization failed" in e_msg.lower():
                    # hugingface: auth header
                    if (
                        attempt == 1
                        and self._is_huggingface_url(model_url)
                        and HF_API_TOKEN
                    ):
                        download_options["header"] = (
                            f"Authorization: Bearer {HF_API_TOKEN}"
                        )
                        self.progress.print(
                            "🔑 Retrying with provided HF_API_TOKEN", "info"
                        )
                    # civitai: query token
                    elif (
                        attempt == 1
                        and self._is_civitai_url(model_url)
                        and CIVITAI_API_TOKEN
                    ):
                        parts = urllib.parse.urlsplit(model_url)
                        query = dict(urllib.parse.parse_qsl(parts.query))
                        query["token"] = CIVITAI_API_TOKEN
                        model_url = parts._replace(
                            query=urllib.parse.urlencode(query)
                        ).geturl()
                        self.progress.print(
                            "🔑 Retrying with provided CIVITAI_API_TOKEN", "info"
                        )
                    else:
                        self.progress.print(
                            f"❌ Authorization failed for {model_url}. Skipped.",
                            "error",
                        )
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
            model_path = Path(config["path"])
            model_filename = config["filename"]
            if not self.is_model_exists(config):
                self.progress.advance(
                    msg=f"ℹ️ {model_filename} not found in path: {model_path}. Skipped.",
                    style="info",
                )
                return True
            self.progress.advance(
                msg=f"🗑️ Removing model: {model_filename}", style="info"
            )
            model_path.unlink()
            logger.info(f"✅ Removed model: {model_filename}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to remove model {model_filename}: {str(e)}")
            return False

    def init_models(self, current_config: list, prev_config: list = None) -> bool:
        if not current_config:
            logger.info("📦 No models in config")
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
                    prev_model = next(
                        (m for m in prev_config if m["url"] == model["url"]), None
                    )
                    prev_path = Path(prev_model["path"])
                    current_path = Path(model["path"])
                    if current_path != prev_path:
                        models_to_move.append({"src": prev_path, "dst": current_path})
            for prev_model in prev_config:
                if not any(
                    model["url"] == prev_model["url"] for model in current_config
                ):
                    models_to_remove.append(prev_model)

        if not models_to_download and not models_to_move and not models_to_remove:
            logger.info("ℹ️ No changes in models")
            return False
        if models_to_move:
            move_count = len(models_to_move)
            logger.info(f"📦 Moving {move_count} models:")
            for model in models_to_move:
                logger.info(f"└─ {model['src']} -> {model['dst']}")
            self.progress.start(move_count)
            for model in models_to_move:
                if not self.move_model(model["src"], model["dst"]):
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
        if models_to_download:
            download_count = len(models_to_download)
            logger.info(f"⬇️ Downloading {download_count} models:")
            for model in models_to_download:
                logger.info(f"└─ {model['filename']}")
            self.progress.start(download_count)
            for model in models_to_download:
                if not self.download_model(model):
                    self.failed_list.append(model)
        return True

