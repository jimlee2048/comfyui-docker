FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04

ENV WORKDIR=/workspace
WORKDIR ${WORKDIR}
ENV COMFYUI_PATH=${WORKDIR}/ComfyUI
ENV COMFYUI_MN_PATH=${COMFYUI_PATH}/custom_nodes/comfyui-manager

ARG DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    python3.12-full python3.12-dev python3-pip ca-certificates git build-essential cmake ninja-build wget curl aria2 ffmpeg libgl1-mesa-dev libopengl0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# pip config
# let .pyc files be stored in one place
ENV PYTHONPYCACHEPREFIX="/root/.cache/pycache"
# suppress [WARNING: Running pip as the 'root' user]
ENV PIP_ROOT_USER_ACTION=ignore
# bypass PEP 668
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PIP_EXTRA_INDEX_URL="https://download.pytorch.org/whl/nightly/cu128"

# install comfyui - method 1: manually clone
RUN git clone --single-branch https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_PATH} \
    && git clone --single-branch https://github.com/Comfy-Org/ComfyUI-Manager.git ${COMFYUI_MN_PATH}

# master(nightly), or version tag like v0.1.0
# https://github.com/comfyanonymous/ComfyUI/tags
ARG COMFYUI_VERSION=master
RUN git -C ${COMFYUI_PATH} fetch --all --tags --prune \
    && git -C ${COMFYUI_PATH} reset --hard ${COMFYUI_VERSION}
# main(nightly), or version tag like v0.1.0
# https://github.com/ltdrdata/ComfyUI-Manager/tags
ARG COMFYUI_MN_VERSION=main
RUN git -C ${COMFYUI_MN_PATH} reset --hard ${COMFYUI_MN_VERSION}

# install pytorch nightly
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    --pre torch torchvision torchaudio

# install comfyui basic requirements
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    -r ${COMFYUI_PATH}/requirements.txt \
    -r ${COMFYUI_MN_PATH}/requirements.txt

# install triton
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --pre triton  

# ARG TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;9.0;10.0;12.0+PTX"
# ARG MAX_JOBS=4
# # install xformers
# RUN --mount=type=cache,target=/root/.cache/pip \
#     pip install -U git+https://github.com/facebookresearch/xformers.git

ARG SAGEATTENTION_CUDA_ARCH_LIST="8.0 8.6 8.9 9.0 12.0"
ARG TORCH_IS_NIGHTLY=1
ARG TORCH_MINOR_VERSION=8
ARG TORCH_PATCH_VERSION=0
ARG CUDA_MINOR_VERSION=8
# install sageattention2
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -U git+https://github.com/woct0rdho/SageAttention.git

# isolate critical python packages
ENV PIP_USER=true
ENV PATH="${PATH}:/root/.local/bin"

# install extra pip packages for comfyui, if you don't mind image size
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    "numpy<2" \
    pyopengl pyopengl-accelerate \
    onnx onnxruntime onnxruntime-gpu \
    transformers diffusers accelerate \
    # i hate this stupid solution to avoid possible conflict :(
    opencv-python opencv-python-headless opencv-contrib-python opencv-contrib-python-headless \
    huggingface_hub

# install boot script requirements
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt \
    nvitop

COPY boot.py .
VOLUME [ "${COMFYUI_PATH}/user", "${COMFYUI_PATH}/output" , "${COMFYUI_PATH}/models", "${COMFYUI_PATH}/custom_nodes"]
EXPOSE 8188
CMD [ "python3", "boot.py" ]