"""Provision the pinned pgvector Windows binaries for a local PostgreSQL server.

The PostgreSQL Windows installer does not include pgvector.  This module keeps
the Windows one-click deployment self-contained by selecting a binary package
for the detected PostgreSQL major version, checking its SHA-256 digest, and
copying only the extension files into the PostgreSQL installation directories
under an elevated PowerShell process.

The prebuilt packages are community-maintained because the official pgvector
project documents source compilation for Windows.  Every supported asset is
pinned by URL, filename, and digest so a changed release cannot be silently
installed by the launcher.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import winreg


PGVECTOR_WINDOWS_VERSION = "0.8.6"
PGVECTOR_WINDOWS_REPOSITORY = "andreiramani/pgvector_pgsql_windows"
PGVECTOR_WINDOWS_RELEASE_BASE = (
    "https://github.com/andreiramani/pgvector_pgsql_windows/releases/download"
)
SUPPORTED_POSTGRES_MAJOR_VERSIONS = tuple(range(13, 19))
MAX_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class PgvectorWindowsAsset:
    postgres_major: int
    filename: str
    sha256: str

    @property
    def url(self) -> str:
        return (
            f"{PGVECTOR_WINDOWS_RELEASE_BASE}/"
            f"{PGVECTOR_WINDOWS_VERSION}_{self.postgres_major}/{self.filename}"
        )


# SHA-256 digests are the GitHub release-asset digests published for the
# v0.8.6 Windows builds.  The PG17 package is also copied into the Windows
# release archive by .github/workflows/release.yml.
PGVECTOR_WINDOWS_ASSETS: dict[int, PgvectorWindowsAsset] = {
    13: PgvectorWindowsAsset(
        13,
        "vector.v0.8.6-pg13.zip",
        "d80bc89dca13ef25204b551f68daff05ad60f13bb34a4e892d4472b50cc62262",
    ),
    14: PgvectorWindowsAsset(
        14,
        "vector.v0.8.6-pg14.zip",
        "b32a743b01e5c178708197f7b8e5fe1da64566b52fefaf3e0f6e26c560ee561c",
    ),
    15: PgvectorWindowsAsset(
        15,
        "vector.v0.8.6-pg15.zip",
        "ac109a074654faf03e5b989963ed855f9acb0ceb5953c4ab8a285212800d1c19",
    ),
    16: PgvectorWindowsAsset(
        16,
        "vector.v0.8.6-pg16.zip",
        "faeaecb100488397ce5d38424b8c931be0f29e1668be7d4e75c26fe2eb056522",
    ),
    17: PgvectorWindowsAsset(
        17,
        "vector.v0.8.6-pg17.zip",
        "420388e9e9f05d92f06d6967ce8772483629b27a66ca9255925fa0fdd445438e",
    ),
    18: PgvectorWindowsAsset(
        18,
        "vector.v0.8.6-pg18.zip",
        "bda17eb97d9e687e3da701adbf4b65a342943b3e0cdc81935ccf0b9833a1ed62",
    ),
}


def asset_for_postgres_major(postgres_major: int) -> PgvectorWindowsAsset:
    """Return the pinned asset for a supported PostgreSQL major version."""

    try:
        return PGVECTOR_WINDOWS_ASSETS[int(postgres_major)]
    except (KeyError, TypeError, ValueError) as exc:
        supported = ", ".join(str(version) for version in SUPPORTED_POSTGRES_MAJOR_VERSIONS)
        raise RuntimeError(
            f"当前 PostgreSQL 主版本 {postgres_major} 没有受支持的 Windows pgvector "
            f"{PGVECTOR_WINDOWS_VERSION} 预编译包；支持版本：{supported}。"
        ) from exc


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Calculate a file digest without loading the archive into memory."""

    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_asset_digest(path: str | os.PathLike[str], asset: PgvectorWindowsAsset) -> None:
    actual = sha256_file(path)
    if actual.lower() != asset.sha256.lower():
        raise RuntimeError(
            f"pgvector 下载包校验失败：{asset.filename} 的 SHA-256 不匹配，"
            f"期望 {asset.sha256}，实际 {actual}。"
        )


def _zip_basename(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def extract_extension_files(
    archive_path: str | os.PathLike[str],
    destination_dir: str | os.PathLike[str],
) -> dict[str, Path]:
    """Extract only pgvector extension files into a controlled staging tree.

    The archive is never extracted wholesale.  This avoids Zip Slip and keeps
    README/build artifacts out of the PostgreSQL installation.
    """

    destination = Path(destination_dir)
    lib_dir = destination / "lib"
    extension_dir = destination / "share" / "extension"
    lib_dir.mkdir(parents=True, exist_ok=True)
    extension_dir.mkdir(parents=True, exist_ok=True)

    matched: dict[str, tuple[str, zipfile.ZipInfo]] = {}
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"拒绝处理包含符号链接的 pgvector 压缩包成员：{info.filename}")
            if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                raise RuntimeError(f"pgvector 压缩包成员过大：{info.filename}")

            basename = _zip_basename(info.filename)
            if basename.lower() == "vector.dll":
                key = "vector.dll"
                output_name = "vector.dll"
            elif basename.lower() == "vector.control":
                key = "vector.control"
                output_name = "vector.control"
            elif re.fullmatch(r"vector--.+\.sql", basename, flags=re.IGNORECASE):
                key = basename.casefold()
                output_name = basename
            else:
                continue
            if key in matched:
                raise RuntimeError(f"pgvector 压缩包存在重复成员：{basename}")
            matched[key] = (output_name, info)

        required = {"vector.dll", "vector.control"}
        missing = sorted(required - matched.keys())
        sql_members = [key for key in matched if key.lower().startswith("vector--")]
        if missing or not sql_members:
            missing_text = ", ".join(missing) if missing else "vector--*.sql"
            raise RuntimeError(f"pgvector 压缩包缺少必要文件：{missing_text}")

        output: dict[str, Path] = {}
        for key, (output_name, info) in matched.items():
            target_dir = lib_dir if key == "vector.dll" else extension_dir
            target = target_dir / output_name
            with archive.open(info, "r") as source, open(target, "wb") as target_stream:
                shutil.copyfileobj(source, target_stream)
            output[key] = target
        return output


def _registry_installation_roots(postgres_major: int) -> list[str]:
    roots: list[str] = []
    registry_paths = (
        r"SOFTWARE\PostgreSQL\Installations",
        r"SOFTWARE\WOW6432Node\PostgreSQL\Installations",
    )
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for registry_path in registry_paths:
            try:
                with winreg.OpenKey(hive, registry_path) as installations:
                    subkey_count = winreg.QueryInfoKey(installations)[0]
                    for index in range(subkey_count):
                        name = winreg.EnumKey(installations, index)
                        try:
                            with winreg.OpenKey(installations, name) as installation:
                                version = str(winreg.QueryValueEx(installation, "Version")[0])
                                base_directory = str(
                                    winreg.QueryValueEx(installation, "Base Directory")[0]
                                )
                        except OSError:
                            continue
                        if version.split(".", 1)[0] == str(postgres_major):
                            roots.append(base_directory)
            except OSError:
                continue
    return roots


def _pg_config_root(candidate: str, postgres_major: int) -> str | None:
    try:
        result = subprocess.run(
            [candidate, "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=0x08000000,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"PostgreSQL\s+(\d+)", result.stdout, flags=re.IGNORECASE)
    if not match or int(match.group(1)) != postgres_major:
        return None
    return os.path.dirname(os.path.dirname(os.path.abspath(candidate)))


def _installation_root_matches_major(root: str, postgres_major: int) -> bool:
    """Reject an explicitly configured root that belongs to another PG major."""

    executables = (
        os.path.join(root, "bin", "pg_config.exe"),
        os.path.join(root, "bin", "pg_config"),
        os.path.join(root, "bin", "postgres.exe"),
        os.path.join(root, "bin", "postgres"),
    )
    for executable in executables:
        if not os.path.isfile(executable):
            continue
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=0x08000000,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        match = re.search(r"PostgreSQL\s+(\d+)", result.stdout, flags=re.IGNORECASE)
        return bool(result.returncode == 0 and match and int(match.group(1)) == postgres_major)
    return True


def find_postgres_installation(postgres_major: int) -> str | None:
    """Find the installation root corresponding to the connected server."""

    candidates: list[str] = []
    configured_root = os.environ.get("PGROOT", "").strip()
    if configured_root:
        candidates.append(configured_root)
    candidates.extend(_registry_installation_roots(postgres_major))

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for base in (program_files, program_files_x86, r"C:\PostgreSQL"):
        candidates.append(os.path.join(base, "PostgreSQL", str(postgres_major)))
        candidates.append(os.path.join(base, str(postgres_major)))

    pg_config = shutil.which("pg_config.exe") or shutil.which("pg_config")
    if pg_config:
        discovered = _pg_config_root(pg_config, postgres_major)
        if discovered:
            candidates.append(discovered)

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if (
            os.path.isdir(os.path.join(candidate, "lib"))
            and os.path.isdir(os.path.join(candidate, "share", "extension"))
            and _installation_root_matches_major(candidate, postgres_major)
        ):
            return os.path.abspath(candidate)
    return None


_ELEVATED_INSTALLER_SCRIPT = textwrap.dedent(
    r'''
    param(
        [Parameter(Mandatory = $true)][string]$StageDirectory,
        [Parameter(Mandatory = $true)][string]$PostgresRoot,
        [Parameter(Mandatory = $true)][int]$Major
    )

    $ErrorActionPreference = 'Stop'
    $stage = [IO.Path]::GetFullPath($StageDirectory).TrimEnd('\')
    $root = [IO.Path]::GetFullPath($PostgresRoot).TrimEnd('\')
    $lib = Join-Path $root 'lib'
    $extension = Join-Path $root 'share\extension'

    $files = @(
        @{ Source = (Join-Path $stage 'lib\vector.dll'); Target = (Join-Path $lib 'vector.dll') },
        @{ Source = (Join-Path $stage 'share\extension\vector.control'); Target = (Join-Path $extension 'vector.control') }
    )
    $sqlSource = Join-Path $stage 'share\extension'
    $sqlFiles = @(Get-ChildItem -LiteralPath $sqlSource -Filter 'vector--*.sql' -File)
    foreach ($sqlFile in $sqlFiles) {
        $files += @{ Source = $sqlFile.FullName; Target = (Join-Path $extension $sqlFile.Name) }
    }
    if ($sqlFiles.Count -eq 0) {
        throw 'The staged pgvector package contains no vector--*.sql files.'
    }

    $rootForMatch = $root.TrimEnd('\')
    $services = @(
        Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
        Where-Object {
            $servicePath = [string]$_.PathName
            $pathMatch = $servicePath -and ($servicePath.IndexOf($rootForMatch, [StringComparison]::OrdinalIgnoreCase) -ge 0)
            # Match the service to the selected installation path. A machine
            # can have multiple PostgreSQL instances of the same major version;
            # matching only on the service name could stop an unrelated one.
            ($_.Name -match '(?i)postgres') -and $pathMatch
        }
    )
    $wasRunning = @{}
    foreach ($service in $services) {
        $wasRunning[$service.Name] = $service.State -eq 'Running'
        if ($wasRunning[$service.Name]) {
            Write-Output ("Stopping PostgreSQL service {0}" -f $service.Name)
            Stop-Service -Name $service.Name -Force -ErrorAction Stop
        }
    }

    $copyError = $null
    try {
        if (-not (Test-Path -LiteralPath $lib -PathType Container)) {
            New-Item -ItemType Directory -Path $lib -Force | Out-Null
        }
        if (-not (Test-Path -LiteralPath $extension -PathType Container)) {
            New-Item -ItemType Directory -Path $extension -Force | Out-Null
        }
        foreach ($file in $files) {
            if (-not (Test-Path -LiteralPath $file.Source -PathType Leaf)) {
                throw ("Staged pgvector file is missing: {0}" -f $file.Source)
            }
            Copy-Item -LiteralPath $file.Source -Destination $file.Target -Force
        }
    } catch {
        $copyError = $_
    }

    $restartErrors = @()
    foreach ($service in $services) {
        if ($wasRunning[$service.Name]) {
            try {
                Write-Output ("Starting PostgreSQL service {0}" -f $service.Name)
                Start-Service -Name $service.Name -ErrorAction Stop
            } catch {
                $restartErrors += ("{0}: {1}" -f $service.Name, $_.Exception.Message)
            }
        }
    }

    if ($copyError) {
        throw $copyError
    }
    if ($restartErrors.Count -gt 0) {
        throw ("PostgreSQL service restart failed: " + ($restartErrors -join '; '))
    }
    if ($services.Count -eq 0) {
        Write-Output 'No matching PostgreSQL Windows service found; extension files were copied.'
    }
    Write-Output 'pgvector Windows extension files installed successfully.'
    ''').strip()


def _powershell_quote(value: str | os.PathLike[str]) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_elevated_copy(stage_directory: str, postgres_root: str, postgres_major: int) -> None:
    """Copy staged files with a UAC elevation prompt and wait for completion."""

    powershell = os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    if not os.path.isfile(powershell):
        powershell = "powershell.exe"

    script_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix="-nexora-pgvector-install.ps1",
            encoding="utf-8",
            newline="\n",
            delete=False,
        ) as script:
            script.write(_ELEVATED_INSTALLER_SCRIPT)
            script_path = script.name

        argument_values = (
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
            "-StageDirectory",
            stage_directory,
            "-PostgresRoot",
            postgres_root,
            "-Major",
            str(postgres_major),
        )
        argument_list = subprocess.list2cmdline(argument_values)
        command = (
            f"$process = Start-Process -FilePath {_powershell_quote(powershell)} "
            f"-ArgumentList {_powershell_quote(argument_list)} -Verb RunAs -Wait -PassThru; "
            "exit $process.ExitCode"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=0x08000000,
            shell=False,
        )
        if result.stdout.strip():
            # The caller logs the high-level operation; this output is returned
            # only as part of an error so credentials never enter the log.
            output = result.stdout.strip()
        else:
            output = ""
        if result.returncode != 0:
            detail = result.stderr.strip() or output or "UAC process returned a non-zero exit code"
            raise RuntimeError(f"Windows pgvector 管理员安装失败：{detail}")
    finally:
        if script_path:
            try:
                os.remove(script_path)
            except OSError:
                pass


def install_pgvector_windows(
    postgres_major: int,
    project_root: str | os.PathLike[str],
    download_file: Callable[[str, str, str], None],
    log: Callable[[str], None] | None = None,
) -> PgvectorWindowsAsset:
    """Install the pinned pgvector asset for a local Windows PostgreSQL server."""

    asset = asset_for_postgres_major(postgres_major)
    logger = log or (lambda _message: None)
    temporary_root = Path(tempfile.mkdtemp(prefix="nexora-pgvector-"))
    bundled_archive = (
        Path(project_root) / "third_party" / "pgvector" / asset.filename
    )
    downloaded_archive = temporary_root / asset.filename
    archive_path = bundled_archive if bundled_archive.is_file() else downloaded_archive
    stage_directory = temporary_root / "staged"

    try:
        if bundled_archive.is_file():
            logger(f"检测到随 Windows 发布包附带的 pgvector 资产：{asset.filename}\n")
        else:
            logger(
                f"未检测到随包附带的 pgvector 资产，开始下载 PostgreSQL {postgres_major} "
                f"对应的 pgvector {PGVECTOR_WINDOWS_VERSION}...\n"
            )
            download_file(asset.url, str(downloaded_archive), f"pgvector {PGVECTOR_WINDOWS_VERSION} for PostgreSQL {postgres_major}")

        verify_asset_digest(archive_path, asset)
        logger(f"pgvector 资产校验通过：SHA-256 {asset.sha256}\n")
        extract_extension_files(archive_path, stage_directory)
        postgres_root = find_postgres_installation(postgres_major)
        if not postgres_root:
            raise RuntimeError(
                f"未能定位 PostgreSQL {postgres_major} 的安装目录。请设置 PGROOT 环境变量，"
                "或确认 PostgreSQL 是标准 Windows x64 安装。"
            )

        logger(
            f"正在请求管理员权限，将 pgvector 文件安装到 {postgres_root}；"
            "安装期间会重启对应 PostgreSQL 服务。\n"
        )
        _run_elevated_copy(str(stage_directory), postgres_root, postgres_major)
        logger(f"PostgreSQL {postgres_major} 的 pgvector 文件安装完成。\n")
        return asset
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
