# Install script for nit — AI testing, documentation & quality agent
# Usage: irm https://raw.githubusercontent.com/getnit-dev/nit/main/release/scripts/install.ps1 | iex

$ErrorActionPreference = "Stop"

$Repo = "getnit-dev/nit"
$BinaryName = "nit"

# --- Detect architecture ---

function Get-Arch {
    $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    switch ($arch) {
        "X64"   { return "x64" }
        "Arm64" { return "arm64" }
        default {
            Write-Error "Unsupported architecture: $arch. nit supports x64 and arm64."
            exit 1
        }
    }
}

# --- Fetch latest version from GitHub ---

function Get-LatestVersion {
    $response = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest"
    return $response.tag_name
}

# --- Main ---

function Install-Nit {
    Write-Host "Installing nit..."

    $arch = Get-Arch
    $target = "windows-$arch"
    $version = Get-LatestVersion

    if (-not $version) {
        Write-Error "Could not determine latest version. Check https://github.com/$Repo/releases"
        exit 1
    }

    Write-Host "  Version:  $version"
    Write-Host "  Platform: $target"

    $url = "https://github.com/$Repo/releases/download/$version/$BinaryName-$target.zip"
    $installDir = Join-Path $env:LOCALAPPDATA "nit"

    # Create install directory
    if (-not (Test-Path $installDir)) {
        New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    }

    # Download and extract
    $tmpFile = Join-Path $env:TEMP "nit-download.zip"

    Write-Host "  Downloading $url..."
    Invoke-WebRequest -Uri $url -OutFile $tmpFile -UseBasicParsing

    Expand-Archive -Path $tmpFile -DestinationPath $installDir -Force
    Remove-Item $tmpFile -Force

    Write-Host ""
    Write-Host "nit $version installed to $installDir\$BinaryName.exe"

    # Add to user PATH if not already there
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$installDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$installDir;$userPath", "User")
        Write-Host ""
        Write-Host "Added $installDir to your user PATH."
        Write-Host "Restart your terminal for the PATH change to take effect."
    }

    Write-Host ""
    Write-Host "Run 'nit --version' to verify the installation."
}

Install-Nit
