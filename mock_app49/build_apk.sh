#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

docker run --rm --user root \
    -v "$repo_root/mock_app49:/workspace" \
    -v "/home/alex/git/my/ha_app/.ci-cd/android/.local/sdk:/opt/android-sdk" \
    -v "/home/alex/git/my/ha_app/.ci-cd/android/.local/gradle-cache:/home/gradle/.gradle" \
    -v "/home/alex/git/my/ha_app/.ci-cd/android/.local/android-home:/root/.android" \
    -e ANDROID_SDK_ROOT=/opt/android-sdk \
    -e GRADLE_USER_HOME=/home/gradle/.gradle \
    -w /workspace \
    casa-de-tequila-android-builder:agp-9.2.1 bash -lc '
        set -euo pipefail
        gradle assembleDebug --no-daemon
        chown -R 1000:1000 /workspace/app/build
    '

apk="$repo_root/mock_app49/app/build/outputs/apk/debug/app-debug.apk"
echo "Build concluído com sucesso!"
ls -lh "$apk"
