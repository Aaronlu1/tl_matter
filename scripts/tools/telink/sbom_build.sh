#!/usr/bin/env bash
#
# Copyright (c) 2026 Project CHIP Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Build a single Telink Matter example with the Zephyr build system and emit an
# SPDX bill of materials for it.
#
# This must be invoked through scripts/run_in_build_env.sh so that the Matter
# (pigweed) build environment is active -- the Zephyr CMake integration for
# Matter shells out to GN/ninja/python from that environment:
#
#   ./scripts/run_in_build_env.sh \
#       "bash scripts/tools/telink/build_with_sbom.sh <board> <app-dir> <build-dir> <sbom-dir>"
#
# The SPDX generation relies on Zephyr's built-in `west spdx` command (zspdx),
# which walks the CMake file-based API codemodel. That query file has to exist
# *before* CMake configures, which is why `west spdx --init` runs first.

set -euo pipefail

BOARD="${1:?board required, e.g. tl3238x}"
APP_DIR="${2:?app source dir required, e.g. examples/lighting-app/telink}"
BUILD_DIR="${3:?build dir required, e.g. out/tl3238x-lighting}"
SBOM_DIR="${4:?sbom output dir required, e.g. out/sbom}"

: "${TELINK_ZEPHYR_BASE:?TELINK_ZEPHYR_BASE is not set -- run this inside the Telink build container}"

# Same environment wiring the Matter Telink builder uses
# (see scripts/build/builders/telink.py:get_cmd_prefixes).
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_BASE="$TELINK_ZEPHYR_BASE"
if [[ -n "${TELINK_ZEPHYR_SDK_DIR:-}" ]]; then
    export ZEPHYR_SDK_INSTALL_DIR="$TELINK_ZEPHYR_SDK_DIR"
fi

# shellcheck disable=SC1091
source "$ZEPHYR_BASE/zephyr-env.sh"

# Resolve to absolute paths so `west spdx` and `west build` agree on the build
# directory regardless of what the caller's cwd was.
BUILD_DIR="$(realpath -m "$BUILD_DIR")"
SBOM_DIR="$(realpath -m "$SBOM_DIR")"
APP_DIR="$(realpath "$APP_DIR")"
mkdir -p "$SBOM_DIR"

echo "=== board      : $BOARD"
echo "=== app dir    : $APP_DIR"
echo "=== build dir  : $BUILD_DIR"
echo "=== sbom dir   : $SBOM_DIR"
echo "=== zephyr base: $ZEPHYR_BASE"
echo

# Step 1: enable the CMake file-based API *before* configuring.
echo "=== [1/3] west spdx --init"
west spdx --init --build-dir="$BUILD_DIR"

# Step 2: build.
echo "=== [2/3] west build -b $BOARD"
west build -d "$BUILD_DIR" -b "$BOARD" "$APP_DIR"

# Step 3: generate the SBOM from the compile graph.
echo "=== [3/3] west spdx"
west spdx \
    --build-dir="$BUILD_DIR" \
    --spdx-dir="$SBOM_DIR" \
    --namespace-prefix "${SBOM_NAMESPACE_PREFIX:-https://github.com/Aaronlu1/tl_matter}"

echo
echo "=== SPDX documents produced:"
ls -la "$SBOM_DIR"

# Fail loudly rather than uploading an empty artifact set.
for doc in app.spdx zephyr.spdx build.spdx modules-deps.spdx; do
    if [[ ! -s "$SBOM_DIR/$doc" ]]; then
        echo "ERROR: expected SPDX document '$doc' is missing or empty" >&2
        exit 1
    fi
done

echo
echo "=== SBOM generation OK"
