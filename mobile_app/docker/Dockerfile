# Self-contained Android toolchain + headless emulator + H3 backend runtime.
# Everything (adb included) lives inside the container; nothing is installed on
# the host and no port is published. Build with tools/android.sh image.
FROM eclipse-temurin:21-jdk-noble

ARG CMDLINE_TOOLS=commandlinetools-linux-16111833_latest.zip
ARG GRADLE_VERSION=9.4.1
ARG API=36

ENV ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_HOME=/opt/android-sdk \
    GRADLE_USER_HOME=/cache/gradle \
    ANDROID_USER_HOME=/cache/android \
    ANDROID_AVD_HOME=/cache/android/avd \
    PATH=/opt/gradle/bin:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:/opt/android-sdk/emulator:/root/.local/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        unzip curl ca-certificates git ffmpeg python3 \
        libpulse0 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libasound2t64 \
        libgl1 libegl1 libxkbfile1 libxdamage1 libxrandr2 libdrm2 libgbm1 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://dl.google.com/android/repository/${CMDLINE_TOOLS}" -o /tmp/tools.zip \
    && mkdir -p /opt/android-sdk/cmdline-tools \
    && unzip -q /tmp/tools.zip -d /opt/android-sdk/cmdline-tools \
    && mv /opt/android-sdk/cmdline-tools/cmdline-tools /opt/android-sdk/cmdline-tools/latest \
    && rm /tmp/tools.zip

RUN yes | sdkmanager --licenses >/dev/null \
    && sdkmanager --install \
        "platform-tools" "emulator" \
        "platforms;android-${API}" "build-tools;36.0.0" \
        "system-images;android-${API};google_apis;x86_64" >/dev/null

RUN curl -fsSL "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" -o /tmp/gradle.zip \
    && unzip -q /tmp/gradle.zip -d /opt \
    && mv "/opt/gradle-${GRADLE_VERSION}" /opt/gradle \
    && rm /tmp/gradle.zip

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Linked, not copied: edits to box.sh apply without rebuilding the image.
RUN ln -s /workspace/mobile_app/docker/box.sh /usr/local/bin/box

WORKDIR /workspace

# Usage (host side is only these zdocker calls; everything else is `box`):
#   zdocker build -t h3-android:dev mobile_app/docker
#   zdocker run -d --name h3-android --device /dev/kvm \
#       -v "$PWD:/workspace" -v h3-android-cache:/cache h3-android:dev sleep infinity
#   zdocker exec h3-android box help
#   zdocker rm -f h3-android
