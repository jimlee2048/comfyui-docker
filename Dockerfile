FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV WORKDIR=/workspace
WORKDIR ${WORKDIR}
ENV COMFYUI_PATH=${WORKDIR}/ComfyUI
ENV COMFYUI_MN_PATH=${COMFYUI_PATH}/custom_nodes/comfyui-manager

ARG DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential cmake ninja-build wget curl aria2 ffmpeg libgl1-mesa-dev libopengl0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# install comfyui - method 1: manually clone
RUN git clone --single-branch https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_PATH} \
    && git clone --single-branch https://github.com/ltdrdata/ComfyUI-Manager.git ${COMFYUI_MN_PATH}

# install comfyui - method 2: using comfy-cli
# RUN comfy --skip-prompt install --version=nightly --skip-torch-or-directml --nvidia --cuda-version 12.4

# master(nightly), or version tag like v0.1.0
# https://github.com/comfyanonymous/ComfyUI/tags
ARG COMFYUI_VERSION=master
RUN git -C ${COMFYUI_PATH} reset --hard ${COMFYUI_VERSION}
# main(nightly), or version tag like v0.1.0
# https://github.com/ltdrdata/ComfyUI-Manager/tags
ARG COMFYUI_MN_VERSION=main
RUN git -C ${COMFYUI_MN_PATH} reset --hard ${COMFYUI_MN_VERSION}

# pip config
# let .pyc files be stored in one place
ENV PYTHONPYCACHEPREFIX="/root/.cache/pycache"
# suppress [WARNING: Running pip as the 'root' user]
ENV PIP_ROOT_USER_ACTION=ignore

# install comfyui basic requirements
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    -r ${COMFYUI_PATH}/requirements.txt \
    -r ${COMFYUI_MN_PATH}/requirements.txt \
    xformers \
    --index-url https://download.pytorch.org/whl/cu124 \
    --extra-index-url https://pypi.org/simple

# isolate critical python packages
ENV PIP_USER=true
ENV PATH="${PATH}:/root/.local/bin"

# install extra pip packages for comfyui, if you don't mind image size
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    "numpy<2" \
    pyopengl pyopengl-accelerate \
    onnx onnxruntime onnxruntime-gpu \
    transformers \
    # i hate this stupid solution to avoid possible conflict :(
    opencv-python opencv-python-headless opencv-contrib-python opencv-contrib-python-headless \
    huggingface_hub

# install boot script requirements
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt \
    && pip cache purge \
    && python ${COMFYUI_MN_PATH}/cm-cli.py save-snapshot

COPY boot.py .
VOLUME [ "${COMFYUI_PATH}/user", "${COMFYUI_PATH}/output" , "${COMFYUI_PATH}/models", "${COMFYUI_PATH}/custom_nodes", "/root/.local/lib/python3.11"]
EXPOSE 8188
CMD [ "python", "boot.py" ]