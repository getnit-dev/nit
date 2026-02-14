#!/bin/sh
# Install script for nit — AI testing, documentation & quality agent
# Usage: curl -fsSL https://raw.githubusercontent.com/getnit-dev/nit/main/release/scripts/install.sh | sh
set -e

REPO="getnit-dev/nit"
BINARY_NAME="nit"

# --- Detect platform and architecture ---

detect_platform() {
    os="$(uname -s)"
    arch="$(uname -m)"

    case "$os" in
        Linux)  platform="linux" ;;
        Darwin) platform="darwin" ;;
        *)
            echo "Error: Unsupported operating system: $os" >&2
            echo "nit supports Linux and macOS. For Windows, use install.ps1." >&2
            exit 1
            ;;
    esac

    case "$arch" in
        x86_64|amd64)   arch="x64" ;;
        aarch64|arm64)   arch="arm64" ;;
        *)
            echo "Error: Unsupported architecture: $arch" >&2
            echo "nit supports x64 and arm64." >&2
            exit 1
            ;;
    esac

    echo "${platform}-${arch}"
}

# --- Determine install directory ---

get_install_dir() {
    if [ -w "/usr/local/bin" ]; then
        echo "/usr/local/bin"
    else
        dir="${HOME}/.local/bin"
        mkdir -p "$dir"
        echo "$dir"
    fi
}

# --- Fetch latest version from GitHub ---

get_latest_version() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
            | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"//;s/".*//'
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "https://api.github.com/repos/${REPO}/releases/latest" \
            | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"//;s/".*//'
    else
        echo "Error: curl or wget is required" >&2
        exit 1
    fi
}

# --- Download and install ---

main() {
    echo "Installing nit..."

    target="$(detect_platform)"
    version="$(get_latest_version)"

    if [ -z "$version" ]; then
        echo "Error: Could not determine latest version." >&2
        echo "Check https://github.com/${REPO}/releases for available versions." >&2
        exit 1
    fi

    echo "  Version:  ${version}"
    echo "  Platform: ${target}"

    url="https://github.com/${REPO}/releases/download/${version}/${BINARY_NAME}-${target}.tar.gz"
    install_dir="$(get_install_dir)"

    # Download and extract
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' EXIT

    echo "  Downloading ${url}..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "${tmpdir}/nit.tar.gz"
    else
        wget -qO "${tmpdir}/nit.tar.gz" "$url"
    fi

    tar -xzf "${tmpdir}/nit.tar.gz" -C "$tmpdir"
    chmod +x "${tmpdir}/${BINARY_NAME}"
    mv "${tmpdir}/${BINARY_NAME}" "${install_dir}/${BINARY_NAME}"

    echo ""
    echo "nit ${version} installed to ${install_dir}/${BINARY_NAME}"

    # Check if install dir is in PATH
    case ":${PATH}:" in
        *":${install_dir}:"*) ;;
        *)
            echo ""
            echo "WARNING: ${install_dir} is not in your PATH."
            echo "Add it by running:"
            echo ""
            echo "  export PATH=\"${install_dir}:\$PATH\""
            echo ""
            echo "Or add that line to your shell profile (~/.bashrc, ~/.zshrc, etc.)."
            ;;
    esac

    echo ""
    echo "Run 'nit --version' to verify the installation."
}

main
