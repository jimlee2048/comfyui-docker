import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .constants import CIVITAI_API_TOKEN, COMFYUI_PATH, HF_API_TOKEN
from .download import Downloader
from .utils import (
    Progress,
    is_civitai_url,
    is_huggingface_url,
    logger,
    move_file,
    url_add_query_param,
)


@dataclass
class Model:
    url: str
    filename: str
    dir: Path | str
    path: Path = field(init=False)

    def __post_init__(self):
        self.dir = Path(self.dir)
        self.path = COMFYUI_PATH / self.dir / self.filename
        self.purge_redundancy()

    def __eq__(self, other):
        if not isinstance(other, Model):
            return NotImplemented
        return self.path == other.path

    def __hash__(self):
        return hash(self.path)

    def purge_redundancy(self):
        # remove huggingface cache
        hf_cache = COMFYUI_PATH / self.dir / ".cache"
        if hf_cache.exists():
            logger.warning(
                f"⚠️ Found huggingface cache directory: {str(hf_cache)}, removing..."
            )
            shutil.rmtree(hf_cache)
        # remove incomplete aria2download
        aria2_cache = COMFYUI_PATH / self.dir / (self.filename + ".aria2")
        if aria2_cache.exists():
            logger.warning(
                f"⚠️ Found incomplete download: {str(self.path)}, removing..."
            )
            aria2_cache.unlink()
            # if .aria2 exists, mean previous download is incomplete, should also remove the file
            self.path.unlink(missing_ok=True)
        return True

    def is_exists(self):
        return self.path.exists()

    def download(self, downloader: Downloader) -> bool | None:
        if self.is_exists():
            logger.info(f"ℹ️ {self.filename} already exists in {self.dir}. Skipped.")
            return None
        download_header = None
        if is_huggingface_url(self.url) and HF_API_TOKEN:
            download_header = f"Authorization: Bearer {HF_API_TOKEN}"
        elif is_civitai_url(self.url) and CIVITAI_API_TOKEN:
            self.url = url_add_query_param(self.url, "token", CIVITAI_API_TOKEN)
        return downloader.download(
            url=self.url,
            filename=self.filename,
            dir=str(COMFYUI_PATH / self.dir),
            header=download_header,
        )

    def remove(self) -> bool | None:
        if not self.is_exists():
            logger.info(f"ℹ️ {self.filename} not found in {self.dir}. Skipped.")
            return None
        try:
            logger.info(f"🗑️ Removing model: {self.filename}")
            self.path.unlink()
        except Exception as e:
            logger.error(f"❌ Failed to remove model {self.filename}: {str(e)}")
            return False
        logger.info(f"✅ Removed model: {self.filename}")
        return True


class ModelsManager:
    def __init__(self, current_config: list[dict], prev_config: list[dict] = None):
        self.current_config = self._load_config(current_config)
        self.prev_config = self._load_config(prev_config) if prev_config else []
        self.downloader = Downloader()

    def _model_factory(self, config: dict) -> Model:
        return Model(
            url=config.get("url"),
            filename=config.get("filename"),
            dir=config.get("dir"),
        )

    def _load_config(self, models_config: list[dict]) -> list[Model]:
        # use set to drop duplicates
        models = set()
        for config in models_config:
            try:
                # create model object
                model = self._model_factory(config)
                # add model to set, drop duplicates
                if model in models:
                    logger.warning(f"⚠️ Skip duplicate model: {model.filename}")
                    continue
                models.add(model)
            except Exception as e:
                logger.warning(f"⚠️ Skip invalid model config: {str(e)}\n{config}")
                continue
        return list(models)

    def init_models(
        self,
    ) -> tuple[list[Model], list[Model], list[Model], list[Model]] | None:
        if not self.current_config:
            logger.info("📦 No models in config")
            return None

        download_queue: list[Model] = []
        remove_queue: list[Model] = []
        move_queue: list[dict[Model, Model]] = []

        if self.prev_config:
            prev_url_to_models = {model.url: model for model in self.prev_config}
            current_url_to_models = {model.url: model for model in self.current_config}

            processed_urls = set()

            for current_model in self.current_config:
                if current_model.url in processed_urls:
                    continue
                # move_queue
                if current_model.url in prev_url_to_models:
                    prev_model = prev_url_to_models[current_model.url]
                    if current_model.path != prev_model.path:
                        move_queue.append(
                            {
                                "prev_model": prev_model,
                                "current_model": current_model,
                            }
                        )
                        processed_urls.add(current_model.url)
                # download_queue
                else:
                    download_queue.append(current_model)
                    processed_urls.add(current_model.url)

            # remove_queue
            for prev_model in self.prev_config:
                if prev_model.url in processed_urls:
                    continue
                if prev_model.url not in current_url_to_models:
                    remove_queue.append(prev_model)
                    processed_urls.add(prev_model.url)
        else:
            download_queue = self.current_config

        downloaded = []
        removed = []
        moved = []
        failed = []

        # process move_queue
        if move_queue:
            queue_length = len(move_queue)
            logger.info(f"📦 Moving {queue_length} models:")
            for task in move_queue:
                logger.info(
                    f"└─ {task['prev_model'].path} -> {task['current_model'].path}"
                )
            with Progress(total_steps=queue_length) as p:
                for task in move_queue:
                    p.advance()
                    prev_model = task["prev_model"]
                    current_model = task["current_model"]
                    if not move_file(prev_model.path, current_model.path):
                        failed.append(prev_model)
                    else:
                        moved.append(current_model)
        # process remove_queue
        if remove_queue:
            queue_length = len(remove_queue)
            logger.info(f"🗑️ Removing {queue_length} models:")
            for model in remove_queue:
                logger.info(f"└─ {model.filename}")
            with Progress(total_steps=queue_length) as p:
                for model in remove_queue:
                    p.advance()
                    result = model.remove()
                    if result is False:
                        failed.append(model)
                    elif result is True:  # Only count actual removals as success
                        removed.append(model)
                    # None means file not found - don't count as removed or failed
        # process download_queue
        if download_queue:
            queue_length = len(download_queue)
            logger.info(f"⬇️ Downloading {queue_length} models:")
            for model in download_queue:
                logger.info(f"└─ {model.filename}")
            with Progress(total_steps=queue_length) as p:
                for model in download_queue:
                    p.advance()
                    result = model.download(self.downloader)
                    if result is False:
                        failed.append(model)
                    else:  # None means already exists, True means success
                        downloaded.append(model)

        return (downloaded, removed, moved, failed)
