#!/usr/bin/env python3
"""Regression tests for resolve-ndk.py."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "resolve-ndk.py"
SPEC = importlib.util.spec_from_file_location("resolve_ndk", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
import sys
sys.path.insert(0, str(SCRIPT.parent))
from ndk_versions import resolve_ndk_package_version, resolve_ndk_revision
SPEC.loader.exec_module(MODULE)


class ResolveNdkTests(unittest.TestCase):
    def test_gradle_base_revision_maps_to_beta_sdk_package(self):
        self.assertEqual(resolve_ndk_revision("29.0.13113456"), "29.0.13113456")
        self.assertEqual(
            resolve_ndk_package_version("29.0.13113456"),
            "29.0.13113456-beta1",
        )

    def test_stable_alias_keeps_stable_sdk_package(self):
        self.assertEqual(resolve_ndk_revision("r29"), "29.0.14033849")
        self.assertEqual(resolve_ndk_package_version("r29"), "29.0.14033849")

    def write(self, root: Path, path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_groovy_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", 'android { ndkVersion "26.1.10909125" }')
            self.assertEqual(MODULE.detect_ndk_versions(root), (["26.1.10909125"], []))

    def test_kotlin_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle.kts", 'android { ndkVersion = "27.3.13750724" }')
            self.assertEqual(MODULE.detect_ndk_versions(root), (["27.3.13750724"], []))

    def test_root_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "build.gradle", 'ext.ndkVersion = "25.2.9519653"')
            self.write(root, "app/build.gradle", "android { ndkVersion rootProject.ext.ndkVersion }")
            self.assertEqual(MODULE.detect_ndk_versions(root), (["25.2.9519653"], []))

    def test_gradle_property(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "gradle.properties", "android.ndkVersion=24.0.8215888")
            self.write(root, "app/build.gradle", 'android { ndkVersion = project.property("android.ndkVersion") }')
            self.assertEqual(MODULE.detect_ndk_versions(root), (["24.0.8215888"], []))

    def test_version_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "gradle/libs.versions.toml", '[versions]\nndk = "28.2.13676358"\n')
            self.write(root, "app/build.gradle.kts", "android { ndkVersion = libs.versions.ndk.get() }")
            self.assertEqual(MODULE.detect_ndk_versions(root), (["28.2.13676358"], []))

    def test_conflicting_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", 'android { ndkVersion = "25.2.9519653" }')
            self.write(root, "native/build.gradle", 'android { ndkVersion = "26.1.10909125" }')
            versions, unresolved = MODULE.detect_ndk_versions(root)
            self.assertEqual(len(versions), 2)
            self.assertFalse(unresolved)

    def test_unresolved_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", "android { ndkVersion = libs.versions.ndk.get() }")
            versions, unresolved = MODULE.detect_ndk_versions(root)
            self.assertFalse(versions)
            self.assertTrue(unresolved)

    def test_flutter_managed_ndk_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "pubspec.yaml", "name: sample\ndependencies:\n  flutter:\n    sdk: flutter\n")
            self.write(
                root,
                "android/app/build.gradle.kts",
                "android { ndkVersion = flutter.ndkVersion }",
            )
            self.assertEqual(MODULE.detect_ndk_versions(root), ([], []))

    def test_no_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", "android { compileSdk 35 }")
            self.assertEqual(MODULE.detect_ndk_versions(root), ([], []))

 
class VerifyNdkTests(unittest.TestCase):
    def test_sdkmanager_installs_beta_package_and_verifies_base_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk_root = root / "sdk"
            sdkmanager = sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
            sdkmanager.parent.mkdir(parents=True)
            log = root / "sdkmanager.log"

            sdkmanager.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$SDKMANAGER_LOG"
sdk_root=""
package=""
install=false
for arg in "$@"; do
    case "$arg" in
        --sdk_root=*) sdk_root="${arg#*=}" ;;
        --install) install=true ;;
        ndk\\;*) package="$arg" ;;
    esac
done
if [ "$install" = true ]; then
    [ "$package" = "ndk;29.0.13113456-beta1" ] || exit 23
    ndk="$sdk_root/ndk/29.0.13113456"
    toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
    mkdir -p "$toolchain"
    cat > "$ndk/source.properties" <<'PROPERTIES'
Pkg.Desc = Android NDK
Pkg.Revision = 29.0.13113456-beta1
Pkg.BaseRevision = 29.0.13113456
PROPERTIES
    printf '#!/usr/bin/env bash\\nexit 0\\n' > "$toolchain/llvm-strip"
    chmod +x "$toolchain/llvm-strip"
fi
""",
                encoding="utf-8",
            )
            sdkmanager.chmod(0o755)

            github_env = root / "github.env"
            github_path = root / "github.path"
            env = os.environ.copy()
            env.update({
                "ANDROID_HOME": str(sdk_root),
                "CI_HELPERS_DIR": str(SCRIPT.parent),
                "REQUESTED_NDK_VERSION": "29.0.13113456",
                "SDKMANAGER_LOG": str(log),
                "GITHUB_ENV": str(github_env),
                "GITHUB_PATH": str(github_path),
                "HOME": str(root / "home"),
            })

            result = subprocess.run(
                ["bash", str(SCRIPT.parent / "verify-ndk.sh")],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = log.read_text(encoding="utf-8")
            self.assertIn("ndk;29.0.13113456-beta1", calls)
            self.assertIn("--channel=3", calls)
            self.assertIn("ANDROID_NDK_HOME=", github_env.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
