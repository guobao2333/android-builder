# Android Build CI

This repository contains a GitHub Actions workflow for building Android installable artifacts (APK / AAB) from a target repository.

[中文说明](README-zh_CN.md) | :star: English README

---

## What this workflow does

This workflow:
- Checks out a target repository and branch, defaulting to the current repository and `main`
- Uses Gradle task introspection to detect installable Android Application modules
- Detects available build variants, including flavors and build types
- Builds matching variants in parallel through a matrix
- Uploads build outputs as artifacts
- Optionally publishes a GitHub Release (disabled by default)

## Workflow file

Usually located at:

```yaml
.github/workflows/android.yml
```

## Inputs

| Input | Description | Type | Default |
|---|---|:---:|:---:|
| **repository** | Target repository in `owner/repo` format. Leave blank to use the current repository | `string` | - |
| **branch** | Target branch | `string` | main |
| **module** | Target module(s), comma-separated. Leave blank to auto-detect installable Application modules | `string` | app |
| **build_flavor** | Build flavor(s), comma-separated. Leave blank to accept all flavors | string | - |
| **build_type** | Build type | choice: `debug`, `release`, `aab`, `all` | debug |
| **build_options** | Extra Gradle arguments | `string` | - |
| **build_test** | Whether to run `./gradlew build` first | `boolean` | `false` |
| **upload_release** | Whether to publish a GitHub Release | `boolean` | `false` |
| **os_version** | Runner image | choice: `ubuntu-latest`, `ubuntu-22.04` | ubuntu-latest |
| **jdk_version** | JDK version | choice: `25`, `24`, `23`, `22`, `21`, `17`, `11`, `8` | 17 |
| **ndk_version** | NDK version | choice: `r29`, `r28c`, `r27d`, `r26d`, `r25c`, `r24`, `r23c`, `r22b`, `r21e`, `r20b` | r27d |

## `build_type` values

- `debug`
- `release`
- `aab`
- `all` — builds `debug`, `release`, and `aab`

## Behavior

### Modules

- If `module` is provided, the workflow validates that the module exists
- If `module` is blank, the workflow auto-detects installable Android Application modules
- Missing modules fail fast; nothing is guessed

### Flavors

- `build_flavor` accepts comma-separated values such as `free,paid`
- The workflow uses Gradle task introspection to match real variants
- Unknown flavors fail fast

### Build outputs

- `debug` / `release` produce APK files
- `aab` produces an AAB file
- Artifact names include repository name, module name, flavor name, build type, and timestamp
- Artifact paths are restricted to the matching module directory

### Release

- `upload_release=false` means no GitHub Release is created
- `upload_release=true` publishes the uploaded artifacts as GitHub Release assets

## Examples

### 1. Build the default module in the current repository

```yaml
repository: blank
branch: main
module: app
build_type: debug
```

### 2. Build a release AAB from another repository

```yaml
repository: some-owner/some-repo
branch: main
module: app
build_type: debug
upload_release: true
```

### 3. Build multiple modules and flavors

```yaml
module: app,store
build_flavor: free,paid
build_type: all
```

## Triggering from another CI

If you want to call this workflow from another CI system, the most reliable method is the GitHub `workflow_dispatch` API.

### Option A: GitHub Actions or any CI that can make HTTP requests

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
    "build_test": "true",
    "upload_release": "false",
    "os_version": "ubuntu-latest",
    "jdk_version": "17",
    "ndk_version": "r27d"
  }
}
```

Authentication can use:
- GitHub Personal Access Token
- GitHub App token
- Any token with `actions:write` permission

### Option B: GitHub CLI

```bash
gh workflow run android.yml \
  --repo owner/repo \
  -f repository=owner/repo \
  -f branch=main \
  -f module=app \
  -f build_flavor=free,paid \
  -f build_type=all \
  -f build_test=true \
  -f upload_release=false \
  -f os_version=ubuntu-latest \
  -f jdk_version=17 \
  -f ndk_version=r27d
```

## Common failure causes

- Repository not found or access denied
- Branch not found
- Module name typo
- Requested flavor does not exist
- No installable Android Application module exists in the target repository
- Invalid Gradle arguments in `build_options`

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
    