from collections import defaultdict
from pathlib import Path

import tomllib

from .utils import (
    compile_pattern,
    filter_path_list,
    logger,
    print_list_tree,
)


class ConfigManager:
    def __init__(
        self,
        config_dir: Path,
        include_pattern: str | None = None,
        exclude_pattern: str | None = None,
    ) -> None:
        self._config = self.load_config(config_dir, include_pattern, exclude_pattern)

    @property
    def config(self):
        return self._config

    def _sort_by_numeric_prefix(self, file_path: Path) -> tuple:
        filename = file_path.name
        # Extract numeric prefix if it exists
        pattern = compile_pattern(r"^(\d+)-")
        match = pattern.match(filename)
        if match:
            return (int(match.group(1)), filename)
        # If no numeric prefix, sort after numbered files
        return (float("inf"), filename)

    def _parse_config_files(self, files: list[Path]) -> dict:
        full_config = defaultdict(list)
        for file in files:
            try:
                config = tomllib.loads(file.read_text())
                for key, value in config.items():
                    full_config[key].extend(value)
            except Exception as e:
                logger.error(f"❌ Failed to parse config file '{file}': {str(e)}")
                continue
        return dict(full_config)

    def load_config(
        self, dir: Path, include_pattern: str = None, exclude_pattern: str = None
    ) -> dict:
        config_files = []
        if dir.is_dir():
            logger.info(f"📂 Loading config: {dir}")
            config_files = list(dir.rglob("*.toml"))
        elif dir.is_file():
            logger.warning("⚠️ Invalid config detected, removing...")
            dir.unlink()
            return {}
        else:
            logger.info("ℹ️ No config directory found")
            return {}

        need_filter = False
        if include_pattern:
            logger.info(f"⚡ Include config filter: {include_pattern}")
            need_filter = True
        if exclude_pattern:
            logger.info(f"⚡ Exclude config filter: {exclude_pattern}")
            need_filter = True
        if need_filter:
            config_files = filter_path_list(
                config_files, include_pattern, exclude_pattern
            )

        # sort config files by numeric prefix
        config_files.sort(key=self._sort_by_numeric_prefix)

        logger.info(f"📄 Found {len(config_files)} config files:")
        print_list_tree(config_files)

        config = self._parse_config_files(config_files)
        if not config:
            logger.info("ℹ️ No valid config found")
        logger.debug(f"🛠️ Loaded config: {config}")

        return config
