#!/usr/bin/env node
"use strict";

/**
 * postinstall.js — Downloads the correct platform binary for nit.
 *
 * Runs automatically after `npm install getnit`. Detects the current
 * OS and architecture, downloads the matching binary from GitHub Releases,
 * and places it in the bin/ directory.
 */

const https = require("https");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");
const { createGunzip } = require("zlib");

const REPO = "getnit-dev/nit";
const VERSION = require("./package.json").version;

const PLATFORM_MAP = {
  darwin: "darwin",
  linux: "linux",
  win32: "windows",
};

const ARCH_MAP = {
  x64: "x64",
  arm64: "arm64",
};

function getPlatformTarget() {
  const platform = PLATFORM_MAP[process.platform];
  const arch = ARCH_MAP[process.arch];

  if (!platform) {
    console.error(`Unsupported platform: ${process.platform}`);
    console.error("nit supports macOS, Linux, and Windows.");
    process.exit(1);
  }

  if (!arch) {
    console.error(`Unsupported architecture: ${process.arch}`);
    console.error("nit supports x64 and arm64.");
    process.exit(1);
  }

  return `${platform}-${arch}`;
}

function getDownloadUrl(target) {
  const ext = process.platform === "win32" ? "zip" : "tar.gz";
  return `https://github.com/${REPO}/releases/download/v${VERSION}/nit-${target}.${ext}`;
}

function download(url) {
  return new Promise((resolve, reject) => {
    const request = (url) => {
      https
        .get(url, { headers: { "User-Agent": "getnit-npm" } }, (res) => {
          // Follow redirects (GitHub releases redirect to S3)
          if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
            request(res.headers.location);
            return;
          }

          if (res.statusCode !== 200) {
            reject(new Error(`Download failed with status ${res.statusCode}: ${url}`));
            return;
          }

          const chunks = [];
          res.on("data", (chunk) => chunks.push(chunk));
          res.on("end", () => resolve(Buffer.concat(chunks)));
          res.on("error", reject);
        })
        .on("error", reject);
    };
    request(url);
  });
}

async function extractTarGz(buffer, destDir) {
  const tmpFile = path.join(destDir, "nit-download.tar.gz");
  fs.writeFileSync(tmpFile, buffer);

  try {
    execSync(`tar -xzf "${tmpFile}" -C "${destDir}"`, { stdio: "pipe" });
  } finally {
    fs.unlinkSync(tmpFile);
  }
}

async function extractZip(buffer, destDir) {
  const tmpFile = path.join(destDir, "nit-download.zip");
  fs.writeFileSync(tmpFile, buffer);

  try {
    // Use PowerShell on Windows for zip extraction
    execSync(
      `powershell -Command "Expand-Archive -Path '${tmpFile}' -DestinationPath '${destDir}' -Force"`,
      { stdio: "pipe" }
    );
  } finally {
    fs.unlinkSync(tmpFile);
  }
}

async function main() {
  const target = getPlatformTarget();
  const url = getDownloadUrl(target);
  const binDir = path.join(__dirname, "bin");

  console.log(`nit: downloading binary for ${target}...`);

  try {
    const buffer = await download(url);

    // Ensure bin directory exists
    if (!fs.existsSync(binDir)) {
      fs.mkdirSync(binDir, { recursive: true });
    }

    // Extract based on platform
    if (process.platform === "win32") {
      await extractZip(buffer, binDir);
    } else {
      await extractTarGz(buffer, binDir);
    }

    // Rename to nit-binary (wrapper script calls this)
    const binaryName = process.platform === "win32" ? "nit.exe" : "nit";
    const targetName = process.platform === "win32" ? "nit-binary.exe" : "nit-binary";
    const srcPath = path.join(binDir, binaryName);
    const destPath = path.join(binDir, targetName);

    if (fs.existsSync(srcPath) && srcPath !== destPath) {
      fs.renameSync(srcPath, destPath);
    }

    // Set executable permission on Unix
    if (process.platform !== "win32") {
      fs.chmodSync(destPath, 0o755);
    }

    console.log(`nit: binary installed successfully.`);
  } catch (err) {
    console.error(`nit: failed to download binary: ${err.message}`);
    console.error(`nit: you can install nit via pip instead: pip install getnit`);
    // Don't fail the npm install — the user can still use pip
    process.exit(0);
  }
}

main();
