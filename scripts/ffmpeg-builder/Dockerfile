# syntax=docker/dockerfile:1.7
FROM ubuntu@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea

ARG DEBIAN_FRONTEND=noninteractive
ADD --checksum=sha256:6bac2a01979e210d9eac1d4d56747ec709ea60654744d66705dc3c36e7629e50 \
    https://snapshot.ubuntu.com/ubuntu/20260801T000000Z/pool/main/c/ca-certificates/ca-certificates_20260601~24.04.1_all.deb \
    /tmp/ca-certificates.deb
RUN mkdir -p /tmp/ca-certificates /etc/ssl/certs \
    && dpkg-deb --extract /tmp/ca-certificates.deb /tmp/ca-certificates \
    && find /tmp/ca-certificates/usr/share/ca-certificates -type f -name '*.crt' \
      -exec cat '{}' + > /etc/ssl/certs/ca-certificates.crt
RUN rm -f /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources \
    && printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20260801T000000Z noble main universe' \
      'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20260801T000000Z noble-updates main universe' \
      'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20260801T000000Z noble-security main universe' \
      > /etc/apt/sources.list \
    && printf 'Acquire::Check-Valid-Until "false";\n' > /etc/apt/apt.conf.d/99snapshot \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      autoconf automake binutils-mingw-w64-x86-64 ca-certificates \
      curl g++-mingw-w64-x86-64-posix gcc-mingw-w64-x86-64-posix \
      libtool make nasm pkg-config xz-utils \
    && rm -rf /var/lib/apt/lists/* /tmp/ca-certificates /tmp/ca-certificates.deb

COPY Dockerfile /recipe/Dockerfile
COPY build.sh /recipe/build.sh
RUN chmod 0755 /recipe/build.sh \
    && dpkg-query -W -f='${binary:Package}=${Version}\n' | sort > /recipe/toolchain-packages.txt

ENTRYPOINT ["/recipe/build.sh"]
