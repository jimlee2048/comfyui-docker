# ComfyUI Docker Image
[![GitHub Repo](https://img.shields.io/badge/GitHub-jimlee2048%2Fcomfyui--docker-blue?logo=github)](https://github.com/jimlee2048/comfyui-docker)
[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-jimlee2048%2Fcomfyui--docker-blue?logo=docker)](https://hub.docker.com/r/jimlee2048/comfyui-docker)
[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/jimlee2048/comfyui-docker/build-publish.yml)](https://github.com/jimlee2048/comfyui-docker/actions/workflows/build-publish.yml)
[![Docker Image Version (tag latest)](https://img.shields.io/docker/v/jimlee2048/comfyui-docker/latest?label=latest)](https://hub.docker.com/r/jimlee2048/comfyui-docker)
[![Docker Pulls](https://img.shields.io/docker/pulls/jimlee2048/comfyui-docker)](https://hub.docker.com/r/jimlee2048/comfyui-docker)

A Customizable [ComfyUI](https://github.com/comfyanonymous/ComfyUI) docker image with automatic environment setup.

⚠️ **Note**: This image is designed for personal use with GUI access, not for production server deployments.

## Features
- Ready-to-use Python environment with common ML packages: `xformers`, `transformers`, `onnxruntime`, `opencv-python`, etc.
  - See [Dockerfile](Dockerfile) for complete details
- Automated management of custom nodes & models:
  - Configuration-driven setup during startup
  - Pre/Post initialization script hooks (supports `.py`, `.sh`, `.bat`, `.ps1`)
  - Multiple config files support, with optional regex-based filter for flexible updates
- Built-in [aria2](https://github.com/aria2/aria2) for accelerated large model files downloads
- Use [cm-cli](https://github.com/ltdrdata/ComfyUI-Manager/blob/main/docs/en/cm-cli.md) to install custom nodes.
- Support install custom nodes from [Comfy Registry](https://registry.comfy.org/)
- Optional optimizations for users in the Chinese Mainland (mirrors for pip/Hugging Face/Civitai)

## Available Image Tags

| Image Tag           | Base Image                                                                                                                                         | Python Version                                                                                    | ComfyUI Version                                                                                                                                                           |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nightly`           | [![CUDA](https://img.shields.io/badge/NVIDIA-CUDA--12.8.1--cudnn--devel--ubuntu24.04-76B900?logo=nvidia)](https://hub.docker.com/r/nvidia/cuda/)   | [![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python)](https://www.python.org/) | [![ComfyUI Nightly](https://img.shields.io/github/last-commit/comfyanonymous/ComfyUI?label=nightly&logo=github)](https://github.com/comfyanonymous/ComfyUI/tree/master)   |
| `latest` / `vX.Y.Z` | [![PyTorch](https://img.shields.io/badge/PyTorch-2.6.0--cuda12.6--cudnn9--runtime-EE4C2C?logo=pytorch)](https://hub.docker.com/r/pytorch/pytorch/) | [![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python)](https://www.python.org/) | [![ComfyUI Release](https://img.shields.io/github/v/release/comfyanonymous/ComfyUI?label=release&logo=github)](https://github.com/comfyanonymous/ComfyUI/releases/latest) |

## Environment Variables
| Variable            | Description                                                                                                                                                       | Default                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| INIT_NODE           | Enable automatic installs/removes of custom nodes at startup                                                                                                      | true                                                                       |
| UPDATE_NODE         | Enable automatic updates of custom nodes at startup                                                                                                               | false                                                                      |
| INIT_MODEL          | Enable automatic downloads/removes of models at startup                                                                                                           | true                                                                       |
| BOOT_CONFIG_INCLUDE | Regex pattern for including boot config files.                                                                                                                    |                                                                            |
| BOOT_CONFIG_EXCLUDE | Regex pattern for excluding boot config files.                                                                                                                    |                                                                            |
| COMFYUI_EXTRA_ARGS  | Additional ComfyUI launch arguments.                                                                                                                              |                                                                            |
| HF_API_TOKEN        | [Hugging Face access token](https://huggingface.co/settings/tokens) for downloading access restricted models.                                                     |                                                                            |
| CIVITAI_API_TOKEN   | [Civitai API token](https://education.civitai.com/civitais-guide-to-downloading-via-api/#how-do-i-download-via-the-api) for downloading access restricted models. |                                                                            |
| CN_NETWORK          | Enable network optimization for Chinese Mainland users. Changes default HF/Civitai endpoints.                                                                     | false                                                                      |
| HF_ENDPOINT         | Override the Hugging Face download endpoint.                                                                                                                      | `https://huggingface.co` (or `https://hf-mirror.com` if CN_NETWORK=`true`) |
| CIVITAI_ENDPOINT    | Override the Civitai download endpoint.                                                                                                                           | `https://civitai.com` (or `https://civitai.work` if CN_NETWORK=`true`)     |

## Quick Start
1. Clone this repository:
    ```bash
    git clone https://github.com/jimlee2048/comfyui-docker
    cd comfyui-docker
    ```

2. Create and configure `.env` file base on example:
    ```bash
    cp example.env .env
    # Edit .env to set your preferences
    ```

3. (Optional) Set up automatic node/model management:
    - Enable in `.env`:
      ```env
      INIT_NODE=true
      INIT_MODEL=true
      ```
    - Create your boot config in `config/`:
        - Start with `config/example.toml`
        - Or, reference my [personal config](https://github.com/jimlee2048/config-aigc-playground/tree/main/comfyui/config)

4. Review and adjust `docker-compose.yml` as needed:
    - Choose ComfyUI version via image tag
    - Configure volume mappings for persistent data

5. Launch ComfyUI:
    ```bash
    docker compose up -d  # Run in background
    # or
    docker compose up    # Run in foreground
    ```
    First run may take longer due to node installation and model downloads.

6. Access ComfyUI at `http://localhost:8188`

7. To stop:
    ```bash
    docker compose down
    ```

## Updates & Maintenance

### Configuration Changes
When modifying boot config or environment variables, do not use ComfyUI Manager's restart function on the web interface.

Instead, restart the container to apply changes:
```bash
docker compose down
docker compose up -d
```

### ComfyUI Updates
- Option 1: Use ComfyUI Manager in the web interface

- Option 2: Pull latest image (may break some custom nodes):
  ```bash
  docker compose pull
  docker compose down
  docker compose up -d
  ```
## TODO
- [ ] ROCm version for AMD GPU
- [ ] XPU version for Intel GPU