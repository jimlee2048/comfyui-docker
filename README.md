# ComfyUI Docker Image
[![GitHub Repo](https://img.shields.io/badge/GitHub-jimlee2048%2Fcomfyui--docker-blue?logo=github)](https://github.com/jimlee2048/comfyui-docker)
[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-jimlee2048%2Fcomfyui--docker-blue?logo=docker)](https://hub.docker.com/r/jimlee2048/comfyui-docker)
[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/jimlee2048/comfyui-docker/build-publish.yml)](https://github.com/jimlee2048/comfyui-docker/actions/workflows/build-publish.yml)
[![Docker Image Version (tag latest)](https://img.shields.io/docker/v/jimlee2048/comfyui-docker/latest?label=latest)](https://hub.docker.com/r/jimlee2048/comfyui-docker)
[![Docker Pulls](https://img.shields.io/docker/pulls/jimlee2048/comfyui-docker)](https://hub.docker.com/r/jimlee2048/comfyui-docker)

A Customizable [ComfyUI](https://github.com/comfyanonymous/ComfyUI) docker image with automatic environment setup.

⚠️ **Note**: This image is designed for personal use with GUI access, not for production server deployments.

## Features
- Ready-to-use Python environment with common ML packages: `nunchaku`, `sageattention`, ~~`xformers`~~, `transformers`, `onnxruntime`, `opencv-python`, etc.
  - `xformers` is temporarily disabled while PyTorch 2.9 and CUDA 13.0 support is upstreamed.
  - See [Dockerfile](Dockerfile.cuda) for complete details
- Automated management of custom nodes & models:
  - Configuration-driven setup during startup
  - Pre/Post initialization script hooks (supports `.py`, `.sh`, `.bat`, `.ps1`)
  - Multiple config files support, with optional regex-based filter for flexible updates
- Built-in [aria2](https://github.com/aria2/aria2) for accelerated large model files downloads
- Use [cm-cli](https://github.com/ltdrdata/ComfyUI-Manager/blob/main/docs/en/cm-cli.md) to install custom nodes.
- Support install custom nodes from [Comfy Registry](https://registry.comfy.org/)
- Optional optimizations for users in the Chinese Mainland (mirrors for pip/Hugging Face/Civitai)

## Available Image Tags

| Image Tag           | Compute Platform                                                                                            | PyTorch Version                                                                                      | Python Version                                                                                    | ComfyUI Version                                                                                                                                                           | Note                                                                      |
| ------------------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `latest` / `vX.Y.Z` | [![CUDA](https://img.shields.io/badge/CUDA-13.0-76B900?logo=nvidia)](https://hub.docker.com/r/nvidia/cuda/) | [![PyTorch](https://img.shields.io/badge/PyTorch-2.9-EE4C2C?logo=pytorch)](https://pytorch.org/)     | [![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python)](https://www.python.org/) | [![ComfyUI Release](https://img.shields.io/github/v/release/comfyanonymous/ComfyUI?label=release&logo=github)](https://github.com/comfyanonymous/ComfyUI/releases/latest) | Recommend                                                                 |
| `nightly`           | [![CUDA](https://img.shields.io/badge/CUDA-13.0-76B900?logo=nvidia)](https://hub.docker.com/r/nvidia/cuda/) | [![PyTorch](https://img.shields.io/badge/PyTorch-2.9-EE4C2C?logo=pytorch)](https://pytorch.org/)     | [![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python)](https://www.python.org/) | [![ComfyUI Nightly](https://img.shields.io/github/last-commit/comfyanonymous/ComfyUI?label=nightly&logo=github)](https://github.com/comfyanonymous/ComfyUI/tree/master)   |                                                                           |

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
1. Clone this repository, mount `docker/` as working directory:
    ```bash
    git clone https://github.com/jimlee2048/comfyui-docker
    cd comfyui-docker/docker
    ```

2. Create and configure `docker/.env` file base on example:
    ```bash
    cp example.env .env
    ```
    see [docker/example.env](https://github.com/jimlee2048/comfyui-docker/blob/main/docker/example.env) for more details.

3. (Optional) Set up automatic node/model management:
    - Set `INIT_NODE=true`  or/and `INIT_MODEL=true` in `docker/.env`
    - Create your boot config in `docker/config/`
    see [docker/config/example.toml](https://github.com/jimlee2048/comfyui-docker/blob/main/docker/config/example.toml) for more details.

4. Create and configure `docker/compose.yml` file base on example:
    ```bash
    cp compose.example.yml compose.yml
    ```
    see [docker/compose.example.yml](https://github.com/jimlee2048/comfyui-docker/blob/main/docker/compose.example.yml) for more details.

5. Launch ComfyUI:
    - Run in foreground to see logs, recommended for first run.
      ```bash
      docker compose up
      ```
    - Or in background as services.
      ```bash
      docker compose up -d
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

- Option 2: Pull latest image:
  ```bash
  docker compose pull
  docker compose down
  docker compose up -d
  ```

## TODO
- [ ] ROCm version for AMD GPU
- [ ] XPU version for Intel GPU
