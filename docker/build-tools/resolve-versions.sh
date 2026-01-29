#!/usr/bin/env bash
set -euo pipefail

output_file="${1:-/etc/profile.d/build-versions.sh}"

: "${PYTHON_VERSION:?PYTHON_VERSION is required}"
: "${TORCH_VERSION:?TORCH_VERSION is required}"
: "${CUDA_VERSION:?CUDA_VERSION is required}"
: "${CUDA_CUDNN_VARIANT:?CUDA_CUDNN_VARIANT is required}"
: "${CUDA_DISTRO:?CUDA_DISTRO is required}"

python_version="${PYTHON_VERSION}"
pytorch_version="${TORCH_VERSION}"
cuda_version="${CUDA_VERSION}"
cuda_cudnn_variant="${CUDA_CUDNN_VARIANT}"
cuda_distro="${CUDA_DISTRO}"

if [[ ! "${python_version}" =~ ^[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: PYTHON_VERSION must be major.minor (got ${python_version})" >&2
  exit 1
fi

if [[ ! "${pytorch_version}" =~ ^[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: TORCH_VERSION must be major.minor (got ${pytorch_version})" >&2
  exit 1
fi

if [[ ! "${cuda_version}" =~ ^[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: CUDA_VERSION must be major.minor (got ${cuda_version})" >&2
  exit 1
fi

python_version_nodot="${python_version//./}"
python_tag="cp${python_version_nodot}"
python_bin="python${python_version}"

IFS='.' read -r cuda_major cuda_minor <<< "${cuda_version}"
cuda_version_short="${cuda_major}.${cuda_minor}"

resolve_latest_cuda_patch() {
  local version_short="$1"
  local variant="$2"
  local distro="$3"
  local next_url
  local response
  local latest_patch=""
  local page_patch

  next_url="https://hub.docker.com/v2/repositories/nvidia/cuda/tags/?page_size=100&name=${version_short}"

  while [[ -n "${next_url}" && "${next_url}" != "null" ]]; do
    response="$(curl -fsSL "${next_url}")"
    page_patch="$(jq -r --arg short "${version_short}" \
      --arg variant "${variant}" \
      --arg distro "${distro}" \
      '[ .results[].name
        | select(startswith($short + ".") and endswith("-" + $variant + "-" + $distro))
        | capture("^[0-9]+\\.[0-9]+\\.(?<patch>[0-9]+)-")?.patch
        | select(. != null)
        | tonumber ] | max // empty' <<< "${response}")"

    if [[ -n "${page_patch}" ]]; then
      if [[ -z "${latest_patch}" || "${page_patch}" -gt "${latest_patch}" ]]; then
        latest_patch="${page_patch}"
      fi
    fi

    next_url="$(jq -r '.next // empty' <<< "${response}")"
  done

  echo "${latest_patch}"
}

resolved_cuda_patch="$(resolve_latest_cuda_patch "${cuda_version_short}" "${cuda_cudnn_variant}" "${cuda_distro}")"
if [[ -z "${resolved_cuda_patch}" ]]; then
  echo "ERROR: No CUDA image tag found for ${cuda_version_short}.x-${cuda_cudnn_variant}-${cuda_distro}" >&2
  exit 1
fi
resolved_cuda_version="${cuda_version_short}.${resolved_cuda_patch}"

cuda_tag="cu${cuda_major}${cuda_minor}"
torch_tag="torch${pytorch_version}"
cuda_torch_tag="${cuda_tag}${torch_tag}"
cuda_base_tag_resolved="${resolved_cuda_version}-${cuda_cudnn_variant}-${cuda_distro}"

cat > "${output_file}" <<EOF
export PYTHON_VERSION="${python_version}"
export PYTHON_TAG="${python_tag}"
export PYTHON_BIN="${python_bin}"
export TORCH_VERSION="${pytorch_version}"
export TORCH_TAG="${torch_tag}"
export CUDA_VERSION_RESOLVED="${resolved_cuda_version}"
export CUDA_TAG="${cuda_tag}"
export CUDA_CUDNN_VARIANT="${cuda_cudnn_variant}"
export CUDA_DISTRO="${cuda_distro}"
export CUDA_TORCH_TAG="${cuda_torch_tag}"
EOF

cat <<EOF
Resolved build versions:
  PYTHON_VERSION=${python_version}
  PYTHON_TAG=${python_tag}
  TORCH_VERSION=${pytorch_version}
  TORCH_TAG=${torch_tag}
  CUDA_VERSION_RESOLVED=${resolved_cuda_version}
  CUDA_CUDNN_VARIANT=${cuda_cudnn_variant}
  CUDA_DISTRO=${cuda_distro}
  CUDA_TAG=${cuda_tag}
  CUDA_BASE_TAG_RESOLVED=${cuda_base_tag_resolved}
EOF
