# Repository Guidelines

## Project Structure & Module Organization
- `Dockerfile.cuda` defines the CUDA-enabled image; keep toolchain pins in sync with upstream releases.
- `docker/` contains user-facing assets: `.env` template, boot configs, and compose example.
- `dev/` mirrors `docker/` but is safe for local experiments (custom configs, bind mounts, scratch volumes).
- `src/comfyui_helper/` houses the Python package that handles config parsing, node/model sync, and boot hooks; each module should stay single-purpose (`config.py`, `nodes.py`, `models.py`, etc.).
- `docker/scripts/<hook>/` directories are executed inside the container; scripts must be idempotent and log to stdout for compose visibility.

## Build, Test, and Development Commands
- `uv sync` installs Python dependencies from `uv.lock`; run at repo root before touching `src/`.
- `uv run comfyui-boot --help` exercises the helper entry point locally and is the fastest regression check for config parsing.
- `docker build -f Dockerfile.cuda -t comfyui-docker:dev .` rebuilds the full image with your changes baked in.
- `cd docker && docker compose up` boots ComfyUI using the sample compose setup (`-d` for detached, `docker compose down` to stop).

## Coding Style & Naming Conventions
- Target Python 3.12 with 4-space indentation and type hints on public functions.
- Modules, functions, and filenames stay `snake_case`; constants are `UPPER_SNAKE`.
- Hook scripts follow `NN-description.sh` ordering to guarantee execution priority.
- Config keys in TOML remain lowercase/kebab (see `docker/config/example.toml`); environment variables stay uppercase with `_`.

## Testing Guidelines
- Adopt `pytest` for any new coverage; place suites under `tests/` mirroring the `comfyui_helper` structure.
- Name tests `test_<feature>_<behavior>` and prioritize parsers, git operations, and download orchestration.
- Run `uv run pytest -q`; aim to touch every module modified in the PR and add regression cases for bug fixes.

## Commit & Pull Request Guidelines
- Follow the Conventional Commit style already in history (`chore:`, `fix:`, `refactor:`, `feat:`) and keep commits scoped.
- Describe PR motivation, testing steps (`uv run pytest`, `docker compose up`), and link issues when available.
- Include logs or screenshots when behavior inside the container changes (new scripts, compose defaults, env vars).

## Security & Configuration Tips
- Never commit populated `.env`, license files, or model assets; rely on the examples under `docker/`.
- API tokens (`HF_API_TOKEN`, `CIVITAI_API_TOKEN`) must come from the host environment; scripts should only read them via `os.environ`.
