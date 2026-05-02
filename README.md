# Android Build CI

This repository contains a manually triggered GitHub Actions workflow for building installable Android artifacts (APK / AAB) from the current repository or from another target repository.

[中文说明](README-zh_CN.md) | :star: English README

---

## What this workflow does

The workflow defined in `android.yml`:

- Runs from `workflow_dispatch` manual inputs.
- Checks out a target repository with recursive submodules.
- Uses the target repository default branch when `branch` is empty.
- Supports a `CHECKOUT_TOKEN` secret for private repositories or private submodules, and falls back to `github.token` for normal access.
- Sets up Temurin JDK, Android NDK, and Gradle cache.
- Verifies that the requested NDK revision is installed completely, repairing or installing it with `sdkmanager` when needed.
- Keeps shared CI logic in `.github/scripts/android-ci/` so NDK verification, pre-build resolution, and Gradle option parsing are not duplicated across jobs.
- Resolves source metadata: branch/ref, full SHA, short SHA, repository name, and version name.
- Reads `gradle.properties` for `versionName`, `VERSION_NAME`, or `version`; if none is found, the GitHub run number is used as `version_name`.
- Uses Gradle task introspection to detect Android application modules and real build variants.
- Builds matching variants through a matrix.
- Optionally runs a full `./gradlew build` test job before the build matrix.
- Optionally runs a pre-build shell command, including an auto mode for NekoBox-style `libcore` builds.
- Uploads APK / AAB files as GitHub Actions artifacts.
- Optionally publishes a GitHub Release in the repository that runs this workflow.

## Workflow files

Place the workflow and helper scripts at:

```text
.github/workflows/android.yml
.github/scripts/android-ci/verify-ndk.sh
.github/scripts/android-ci/resolve-prebuild.py
.github/scripts/android-ci/run-prebuild.sh
.github/scripts/android-ci/parse-gradle-options.py
.github/scripts/android-ci/run-gradle.sh
```

The workflow checks out the workflow repository at `github.sha` into a separate helper path, then checks out the target repository. This keeps helper scripts versioned with the workflow even when `repository` points to another target repository.

## Inputs

| Input | Description | Type | Default |
|---|---|:---:|:---:|
| **repository** | Target repository in `owner/repo` format. Leave empty to use the repository that runs this workflow. | `string` | empty |
| **branch** | Target branch, tag, or SHA. Leave empty to use the target repository default branch. | `string` | empty |
| **module** | Target module(s), comma-separated. Use values such as `app` or `:app`. If empty, the workflow auto-detects installable Android application modules. | `string` | `app` |
| **build_flavor** | Build flavor filter(s), comma-separated. Leave empty to accept all flavors. Matching is normalized and substring-based. | `string` | empty |
| **build_type** | Build output selector. | choice: `debug`, `release`, `aab`, `all` | `debug` |
| **build_options** | Extra Gradle arguments appended to `./gradlew build` and build tasks. Accepts shell-style quoting or a JSON array of strings. | `string` | empty |
| **pre_build_command** | Pre-build command before Gradle. Use `auto`, `none`, `skip`, or a custom shell command. | `string` | `auto` |
| **go_version** | Go version passed to `actions/setup-go` when the pre-build command needs Go. | `string` | `^1.25` |
| **build_test** | Run a separate `./gradlew build` job before the build matrix. | `boolean` | `false` |
| **upload_release** | Publish a GitHub Release after successful builds. | `boolean` | `false` |
| **os_version** | Runner image for test/build jobs. | choice: `ubuntu-latest`, `ubuntu-22.04` | `ubuntu-latest` |
| **jdk_version** | Temurin JDK version. | choice: `26`, `25`, `24`, `23`, `22`, `21`, `17`, `11`, `8` | `21` |
| **ndk_version** | Android NDK alias. | choice: `r29`, `r28c`, `r27d`, `r26d`, `r25c`, `r24`, `r23c`, `r22b`, `r21e`, `r20b` | `r27d` |

## Build type behavior

| `build_type` | Gradle tasks matched | Output |
|---|---|---|
| `debug` | `assemble*Debug` | APK |
| `release` | `assemble*Release` | APK |
| `aab` | `bundle*Release` | AAB |
| `all` | `assemble*Debug`, `assemble*Release`, `bundle*Release` | APK and AAB |

Notes:

- AAB output is release-only.
- `install*` tasks are used only to help detect installable application modules; they are not built directly.
- Multi-flavor Gradle variants are represented by the flavor part of the Gradle task name, for example `assembleFreeGoogleRelease` has flavor `FreeGoogle`.

## Module and flavor behavior

### Modules

- Module names are normalized to Gradle path format. For example, `app` becomes `:app`.
- If `module` is provided, every requested module must exist in `./gradlew projects`.
- If `module` is empty, the workflow scans all Gradle subprojects and keeps modules that expose app-style install or bundle tasks.
- If a requested module exists but does not expose installable Android application tasks, the workflow fails fast.

### Flavors

- `build_flavor` accepts comma-separated filters such as `free,paid`.
- Flavor matching is case-insensitive after removing non-alphanumeric characters.
- The workflow treats a filter as matching when it is contained in the normalized Gradle flavor name.
- If no variants match the requested module, flavor, and build type filters, the workflow fails fast and prints available tasks.


## Build options behavior

`build_options` is normalized once in `setup-matrix` and reused by the test and build jobs as a JSON array. This catches quoting mistakes before the build matrix starts and avoids each job reparsing the raw input differently.

Supported formats:

```text
--info --scan '-Pchannel=free beta'
["--info", "--scan", "-Pchannel=free beta"]
```

The shell-style form uses POSIX shell-like parsing, so quoted values with spaces are preserved. Empty arguments and newline-containing arguments are rejected.

## Pre-build command behavior

`pre_build_command` is resolved by the shared `.github/scripts/android-ci/resolve-prebuild.py` helper before the test job and before each build matrix job.

| Value | Behavior |
|---|---|
| empty / `none` / `skip` | Do not run a pre-build command. |
| `auto` | If both `./run` and `libcore/build.sh` exist, run `./run lib core`; otherwise do nothing. |
| any other value | Run the value as a shell command with `bash -eo pipefail -c`. |

When auto mode detects a NekoBox-style `libcore` build:

- Go is installed with the requested `go_version`.
- `app/libs/libcore.aar` is used as the expected output and cache path.
- `./run`, `libcore/*.sh`, and `buildScript/*.sh` are made executable when present.
- If the cached output already exists, the pre-build command is skipped.
- If the command finishes but the expected output is missing, the job fails.

For manual commands, Go is installed when the command text contains `go`, `gomobile`, or `./run lib core`.

> Security note: custom `pre_build_command` is arbitrary shell. Only allow trusted maintainers to trigger this workflow with custom commands.

## Test job

When `build_test=true`, the workflow runs a separate `test` job before the build matrix:

```bash
./gradlew build --no-daemon --stacktrace <normalized build_options>
```

The test job checks out the exact source SHA resolved by `setup-matrix`, sets up JDK/NDK, optionally runs the same pre-build flow, and then runs the full Gradle build.

## Build artifacts

Each build matrix entry runs one Gradle task:

```bash
./gradlew <module>:<gradle_task> --no-daemon --stacktrace <normalized build_options>
```

Artifacts are uploaded from the matching module directory:

```text
<module_dir>/build/outputs/**/*.apk
<module_dir>/build/outputs/**/*.aab
```

Artifact names include:

```text
<repository-name>-<module>-<flavor>-<debug|release|aab>-<UTC timestamp>
```

The flavor part is omitted when the variant has no flavor.

## Release behavior

`upload_release=false` only uploads workflow artifacts.

`upload_release=true` creates or updates a GitHub Release after all build matrix jobs succeed:

- Release repository: the repository that runs this workflow.
- Tag: `v<version_name>`.
- Release name: `<repository_name> v<version_name>`.
- Release files: downloaded build artifacts matching `<repository_name>-*`.

The release job uses `contents: write`; other jobs use read-only contents permission.

## Workflow summary

The workflow writes a GitHub step summary containing:

- Resolved repository and repository name.
- Branch input and resolved branch/ref.
- Source SHA.
- Module, flavor, build type, raw/normalized build options, pre-build command, and Go version.
- Build/test/release options.
- OS, JDK, requested NDK, resolved NDK revision, and `ANDROID_NDK_HOME`.
- Version name.
- Final build matrix with module, flavor, build type, artifact type, Gradle task, and artifact name.

## Examples

### 1. Build the default module in the current repository

```yaml
repository: ""
branch: ""
module: app
build_type: debug
```

### 2. Build a release AAB from another repository

```yaml
repository: some-owner/some-repo
branch: main
module: app
build_type: aab
upload_release: true
```

### 3. Build multiple modules and flavors

```yaml
module: app,store
build_flavor: free,paid
build_type: all
```

### 4. Run a NekoBox-style pre-build automatically

```yaml
module: app
build_type: release
pre_build_command: auto
go_version: ^1.25
```

### 5. Run a custom pre-build command

```yaml
module: app
build_type: release
pre_build_command: ./scripts/prepare-native-libs.sh
```

## Triggering from another CI

Use GitHub's `workflow_dispatch` API.

Request:

```bash
POST /repos/{owner}/{repo}/actions/workflows/android.yml/dispatches
```

Example payload:

```json
{
  "ref": "main",
  "inputs": {
    "repository": "owner/repo",
    "branch": "main",
    "module": "app",
    "build_flavor": "free,paid",
    "build_type": "all",
    "build_options": "--info '-Pchannel=free beta'",
    "pre_build_command": "auto",
    "go_version": "^1.25",
    "build_test": "true",
    "upload_release": "false",
    "os_version": "ubuntu-latest",
    "jdk_version": "21",
    "ndk_version": "r27d"
  }
}
```

Authentication can use:

- GitHub Personal Access Token
- GitHub App token
- Any token with permission to dispatch workflows in the workflow repository

For private target repositories or private recursive submodules, add a repository secret named `CHECKOUT_TOKEN` with read access to the target repository and its submodules.

### GitHub CLI

```bash
gh workflow run android.yml \
  --repo owner/workflow-repo \
  -f repository=owner/target-repo \
  -f branch=main \
  -f module=app \
  -f build_flavor=free,paid \
  -f build_type=all \
  -f build_options="--info '-Pchannel=free beta'" \
  -f pre_build_command=auto \
  -f go_version='^1.25' \
  -f build_test=true \
  -f upload_release=false \
  -f os_version=ubuntu-latest \
  -f jdk_version=21 \
  -f ndk_version=r27d
```

## Common failure causes

- Target repository not found or access denied.
- Target branch, tag, or SHA not found.
- Private repository or submodule requires `CHECKOUT_TOKEN`.
- Module name typo or module does not exist in `./gradlew projects`.
- Requested module is not an installable Android application module.
- Requested flavor/build type combination does not exist.
- `build_options` has invalid shell quoting / JSON syntax, or contains arguments that Gradle does not understand.
- Custom `pre_build_command` fails.
- Auto pre-build mode runs but does not produce `app/libs/libcore.aar`.
- Requested NDK version cannot be installed or is incomplete after repair.

## License

[MIT License](./LICENSE)

    Copyright (c) 2026 shiguobaona

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
