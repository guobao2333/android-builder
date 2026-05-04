# Android Build CI

此仓库包含一个手动触发的 GitHub Actions 工作流，用于从当前仓库或其他目标仓库构建 Android 可安装产物（APK / AAB）。

[English README](README.md)

---

## 工作流运行原理概览

`android.yml` 此工作流会：

- 通过 `workflow_dispatch` 手动输入触发。
- 拉取目标仓库，并递归拉取 submodules。
- 当 `branch` 为空时，使用目标仓库的默认分支。
- 支持通过 `CHECKOUT_TOKEN` secret 访问私有仓库或私有 submodules；未配置时回退到 `github.token`。
- 通过共享的 `.github/actions/android-ci-prepare` composite action 设置 Temurin JDK、Android NDK 和 Gradle 缓存；setup、test、build jobs 共用同一套准备流程。
- 校验请求的 NDK revision 是否完整安装；优先复用 `nttld/setup-ndk` 的本地缓存，只有确实缺失或不完整时才通过 `sdkmanager` 修复或安装。
- 将公共 CI 逻辑放在 `.github/actions/android-ci-prepare/` 和 `.github/scripts/android-ci/` 中，避免 NDK 校验、pre-build 解析、Gradle 参数解析、unsigned 参数处理和 summary 渲染在多个 job 中重复。
- 解析源码元信息：branch/ref、完整 SHA、短 SHA、仓库名和版本名。
- 从 `gradle.properties` 读取 `versionName`、`VERSION_NAME` 或 `version`；都不存在时使用 GitHub run number 作为 `version_name`。
- 通过 Gradle task introspection 识别 Android Application 模块和真实 build variants。
- 使用 matrix 并行构建匹配的 variants。
- 可选先运行一次完整的 `./gradlew build` 测试任务。
- 可选在 Gradle 构建前运行 pre-build 命令，包括适配 NekoBox 风格 `libcore` 构建的 auto 模式。
- 默认只对 release/AAB 或 `build`/`assemble`/`bundle` 这类聚合任务追加 `-Punsigned`；debug 保留 Android/Gradle 默认测试签名，只有失败且疑似签名问题时才重试兜底。
- 上传 APK / AAB 为 GitHub Actions artifacts。
- 可选在运行此 workflow 的仓库中发布 GitHub Release。

## 工作流文件

将工作流和 helper 脚本放在：

```text
.github/workflows/android.yml
.github/actions/android-ci-prepare/action.yml
.github/scripts/android-ci/ndk_versions.py
.github/scripts/android-ci/verify-ndk.sh
.github/scripts/android-ci/resolve-prebuild.py
.github/scripts/android-ci/run-prebuild.sh
.github/scripts/android-ci/parse-gradle-options.py
.github/scripts/android-ci/resolve-signing.py
.github/scripts/android-ci/unsigned_gradle_options.py
.github/scripts/android-ci/run-gradle.sh
.github/scripts/android-ci/print-workflow-inputs.py
```

workflow 会把运行 workflow 的仓库按 `github.sha` checkout 到单独的 helper 目录，然后再 checkout 目标仓库。这样即使 `repository` 指向其他仓库，composite action 和 helper 脚本也始终与当前 workflow 版本一致。

共享 helper 职责：

| 路径 | 职责 |
|---|---|
| `.github/actions/android-ci-prepare/action.yml` | 为 `setup-matrix`、`test`、`build` 共享 JDK/NDK 校验、可选 pre-build 解析、Go 安装、pre-build 缓存和 pre-build 执行。 |
| `.github/scripts/android-ci/ndk_versions.py` | 统一维护 NDK alias 到完整 revision 的映射。 |
| `.github/scripts/android-ci/verify-ndk.sh` | 校验或修复请求的 NDK，并导出 `ANDROID_NDK_HOME` / `ANDROID_NDK_ROOT`。 |
| `.github/scripts/android-ci/resolve-prebuild.py` 和 `run-prebuild.sh` | 解析并执行可选前置构建命令。 |
| `.github/scripts/android-ci/parse-gradle-options.py` | 将原始 `build_options` 统一规范化为 JSON 数组。 |
| `.github/scripts/android-ci/resolve-signing.py` | 判断是否保持签名构建，或回退到 unsigned 模式。 |
| `.github/scripts/android-ci/unsigned_gradle_options.py` | 统一实现有效 `-Punsigned` 的识别与追加。 |
| `.github/scripts/android-ci/run-gradle.sh` | 使用解析后的参数运行 Gradle，并处理签名失败重试。 |
| `.github/scripts/android-ci/print-workflow-inputs.py` | 从同一个 JSON 对象渲染 workflow step summary 和控制台输入报告。 |

## 输入参数

| 参数 | 说明 | 类型 | 默认值 |
|---|---|:---:|:---:|
| **repository** | 目标仓库，格式为 `owner/repo`。留空则使用运行此 workflow 的仓库。 | `string` | 空 |
| **branch** | 目标分支、tag 或 SHA。留空则使用目标仓库默认分支。 | `string` | 空 |
| **module** | 目标模块，支持逗号分隔。可写 `app` 或 `:app`。为空时自动探测可安装的 Android Application 模块。 | `string` | `app` |
| **build_flavor** | build flavor 过滤器，支持逗号分隔。留空表示接受所有 flavor。匹配逻辑会规范化后做子串匹配。 | `string` | 空 |
| **build_type** | 构建产物选择器。 | choice: `debug`, `release`, `aab`, `all` | `debug` |
| **build_options** | 附加到 `./gradlew build` 和具体构建任务后的额外 Gradle 参数。支持 shell 风格引号或字符串组成的 JSON 数组。 | `string` | 空 |
| **signing** | 是否允许 release 签名构建。默认关闭；release/AAB 任务在未检测到完整签名配置时会使用 `-Punsigned`。debug 保留 Android/Gradle 默认测试签名，只在疑似签名失败时重试兜底。 | `boolean` | `false` |
| **pre_build_command** | Gradle 前置构建命令。可用 `auto`、`none`、`skip` 或自定义 shell 命令。 | `string` | `auto` |
| **go_version** | 当前置构建需要 Go 时传给 `actions/setup-go` 的 Go 版本。 | `string` | `^1.25` |
| **build_test** | 是否在 build matrix 前单独运行 `./gradlew build`。 | `boolean` | `false` |
| **upload_release** | 构建成功后是否发布 GitHub Release。 | `boolean` | `false` |
| **os_version** | test/build job 使用的 runner 镜像。`setup-matrix` 和 `release` 固定使用 `ubuntu-latest`。 | choice: `ubuntu-latest`, `ubuntu-24.04`, `ubuntu-22.04`, `macos-latest`, `macos-26`, `macos-15`, `macos-26-intel`, `macos-15-intel` | `ubuntu-latest` |
| **jdk_version** | Temurin JDK 版本。 | choice: `26`, `25`, `24`, `23`, `22`, `21`, `17`, `11`, `8` | `21` |
| **ndk_version** | Android NDK alias。 | choice: `r29`, `r28c`, `r27d`, `r26d`, `r25c`, `r24`, `r23c`, `r22b`, `r21e`, `r20b` | `r27d` |

## Runner 行为

`os_version` 只控制 `test` 和 `build` jobs。轻量的 `setup-matrix` job 和最终的 `release` job 始终运行在 `ubuntu-latest`，以保持模块探测和发布流程稳定。

可选 runner label 包括 Linux x64 和 macOS runner：

| Runner label | 平台 / 架构 | 建议用途 |
|---|---|---|
| `ubuntu-latest` | Linux x64，GitHub 当前稳定 Ubuntu 镜像 | 默认 Android 构建。 |
| `ubuntu-24.04` | Linux x64，固定 Ubuntu 24.04 | 可复现的 Linux x64 构建。 |
| `ubuntu-22.04` | Linux x64，固定 Ubuntu 22.04 | 兼容较旧工具链。 |
| `macos-latest` | macOS arm64，GitHub 当前稳定 macOS 镜像 | 不固定版本的 macOS 构建验证。 |
| `macos-26` | macOS arm64，固定 macOS 26 | 可复现的 Apple Silicon 构建。 |
| `macos-15` | macOS arm64，固定 macOS 15 | 需要 macOS 15 的 Apple Silicon 构建。 |
| `macos-26-intel` | macOS Intel x86_64，固定 macOS 26 | x86_64 macOS 构建。 |
| `macos-15-intel` | macOS Intel x86_64，固定 macOS 15 | 使用较旧 macOS 15 镜像的 x86_64 macOS 构建。 |

共享准备 action 会在每个需要 Android 工具链的 job 中执行 JDK 设置、`nttld/setup-ndk` 和 NDK 校验。`setup-matrix` 调用时使用 `run_prebuild=false`；`test` 和 `build` 调用时使用 `run_prebuild=true`，因此还会解析、缓存并执行 pre-build 步骤。

NDK 校验 helper 会探测宿主 OS，并检查对应的 NDK 工具链目录：Linux 使用 `linux-x86_64`，macOS 使用 `darwin-x86_64`。NDK alias 由 `.github/scripts/android-ci/ndk_versions.py` 解析。校验时会搜索 canonical SDK 目录、`ANDROID_NDK_HOME` / `ANDROID_NDK_ROOT`、`~/.setup-ndk/<alias>`、`~/.setup-ndk/<revision>`、整个 `~/.setup-ndk` 缓存和 `$ANDROID_SDK_ROOT/ndk`。候选目录必须同时满足 `source.properties` 中的 `Pkg.Revision` 等于请求的完整 revision，并且存在对应宿主平台的 LLVM 工具链二进制。如果在 canonical SDK 目录外找到完整缓存，helper 会将其 symlink 到 `$ANDROID_SDK_ROOT/ndk/<full-revision>`，方便 Gradle `ndkVersion` 解析。只有找不到完整候选时，才回退执行 `sdkmanager --install ndk;<full-revision>`。

pre-build 缓存 key 包含 `runner.os`、`runner.arch`、仓库名、源码 SHA、请求的 NDK、Go 版本，以及运行时对 `run`、`buildScript`、`libcore` 目录计算出的 SHA256。这样不会在 composite action 中使用 `hashFiles(...)`，也避免 macOS Intel、macOS arm64 和 Linux 运行复用不兼容缓存。


## build_type 行为

| `build_type` | 匹配的 Gradle tasks | 产物 |
|---|---|---|
| `debug` | `assemble*Debug` | APK |
| `release` | `assemble*Release` | APK |
| `aab` | `bundle*Release` | AAB |
| `all` | `assemble*Debug`、`assemble*Release`、`bundle*Release` | APK 和 AAB |

说明：

- AAB 只构建 release AAB。
- `install*` task 只用于辅助判断模块是否为可安装 Application 模块，不会被直接构建。
- 多维 flavor 会体现在 Gradle task 的 flavor 部分，例如 `assembleFreeGoogleRelease` 的 flavor 是 `FreeGoogle`。

## 模块与 flavor 行为

### 模块

- 模块名会规范化为 Gradle path 格式，例如 `app` 会变成 `:app`。
- 如果填写了 `module`，每个请求的模块都必须存在于 `./gradlew projects` 输出中。
- 如果 `module` 为空，workflow 会扫描全部 Gradle subprojects，并保留暴露 app 风格 install 或 bundle task 的模块。
- 如果请求的模块存在，但不是可安装 Android Application 模块，workflow 会快速失败。

### Flavors

- `build_flavor` 支持逗号分隔，例如 `free,paid`。
- flavor 匹配会先转小写并移除非字母数字字符。
- 当过滤词出现在规范化后的 Gradle flavor 名中时即认为匹配。
- 如果没有任何 variant 同时匹配 module、flavor 和 build type，workflow 会快速失败并打印可用 tasks。


## build_options 行为

`build_options` 会在 `setup-matrix` 中统一规范化一次，并以 JSON 数组形式传给 test/build jobs。这样可以在 matrix 开始前暴露引号错误，也避免每个 job 重新用不同方式解析原始输入。同一个规范化后的 JSON 数组也会传给签名和 unsigned 参数 helper，保证所有 job 基于同一份解析结果做决策。

支持两种格式：

```text
--info --scan '-Pchannel=free beta'
["--info", "--scan", "-Pchannel=free beta"]
```

shell 风格格式使用 POSIX shell-like 解析，因此带空格的 quoted value 会被保留。空参数和包含换行的参数会被拒绝。

## 签名行为

`signing` 默认是 `false`。workflow 不再在 `setup-matrix` 阶段把 `-Punsigned` 全局塞进所有 Gradle 参数，而是在真正执行 Gradle 时只对 release/AAB 或 `build`、`assemble`、`bundle` 这类可能包含 release 的聚合任务追加。debug 任务默认继续使用 Android/Gradle 自带的 debug keystore 测试签名。有效 unsigned 处理集中在 `.github/scripts/android-ci/unsigned_gradle_options.py`，因此 `resolve-signing.py` 和 `run-gradle.sh` 对显式 `-Punsigned`、`-Punsigned=true`、`-Punsigned=false` 使用同一套规则。

当 `signing=true` 时，workflow 会在 `setup-matrix` 阶段检查目标仓库和当前 workflow 仓库的 GitHub Secrets/Variables 是否存在完整签名配置。只有检测到完整配置时才保持签名模式；如果没有检测到完整配置，即使目标仓库的 `build.gradle` / `build.gradle.kts` 声明了 `signingConfig`，release/AAB 和聚合任务也会回退并追加 `-Punsigned`，避免因缺少 keystore、alias 或密码而失败。非 release 任务不会一开始就被覆盖；如果执行失败且日志疑似签名问题，会自动带 `-Punsigned` 重试一次作为兜底。

检测来源包括：

- 目标仓库中的 `keystore.properties`、`key.properties`、`signing.properties`、`release.properties`、`gradle.properties`、keystore 文件，以及 Gradle 文件中的签名声明。
- `build_options` 中完整的 `-Pandroid.injected.signing.*` 或常见 signing 属性。
- workflow 仓库的 Secrets/Variables，支持常见组合，例如 `SIGNING_KEYSTORE_BASE64` + `SIGNING_STORE_PASSWORD` + `SIGNING_KEY_ALIAS` + `SIGNING_KEY_PASSWORD`、`KEYSTORE_BASE64` + `KEYSTORE_PASSWORD` + `KEY_ALIAS` + `KEY_PASSWORD`、`RELEASE_KEYSTORE_BASE64` + `RELEASE_STORE_PASSWORD` + `RELEASE_KEY_ALIAS` + `RELEASE_KEY_PASSWORD`、`ANDROID_INJECTED_SIGNING_*` 等。

检测日志和 step summary 只输出变量名/来源，不输出 secret 值。

## 前置构建命令

`pre_build_command` 会由共享的 `.github/scripts/android-ci/resolve-prebuild.py` helper 在 test job 和每个 build matrix job 中分别解析。

| 值 | 行为 |
|---|---|
| 空 / `none` / `skip` | 不运行前置构建命令。 |
| `auto` | 如果同时存在 `./run` 和 `libcore/build.sh`，执行 `./run lib core`；否则不做任何事。 |
| 其他值 | 使用 `bash -eo pipefail -c` 执行该 shell 命令。 |

当 auto 模式检测到 NekoBox 风格 `libcore` 构建时：

- 使用请求的 `go_version` 安装 Go。
- 将 `app/libs/libcore.aar` 作为预期输出和缓存路径。
- 如果存在 `./run`、`libcore/*.sh`、`buildScript/*.sh`，会尝试加可执行权限。
- 如果缓存产物已存在，会跳过前置构建命令。
- 如果命令执行完成但预期产物不存在，job 会失败。

对于自定义命令，当命令文本包含 `go`、`gomobile` 或 `./run lib core` 时，会安装 Go。pre-build 缓存 key 由 composite action 在运行时基于 `run`、`buildScript`、`libcore` 下的实际文件计算，不再依赖 workflow 层的 `hashFiles(...)` 表达式。

> 安全提示：自定义 `pre_build_command` 是任意 shell 命令。只应允许可信维护者使用自定义命令触发此 workflow。

## 测试 job

当 `build_test=true` 时，workflow 会在 build matrix 前运行独立的 `test` job：

```bash
./gradlew build --no-daemon --stacktrace <按任务解析后的 Gradle options>
```

测试 job 会 checkout `setup-matrix` 已解析出的精确源码 SHA，设置 JDK/NDK，可选运行同样的前置构建流程，然后运行完整 Gradle build。

## 构建产物

每个 build matrix entry 会运行一个 Gradle task：

```bash
./gradlew <module>:<gradle_task> --no-daemon --stacktrace <按任务解析后的 Gradle options>
```

产物从对应模块目录上传：

```text
<module_dir>/build/outputs/**/*.apk
<module_dir>/build/outputs/**/*.aab
```

artifact 名称包含：

```text
<repository-name>-<module>-<flavor>-<debug|release|aab>-<UTC timestamp>
```

如果 variant 没有 flavor，名称中会省略 flavor 部分。

## Release 行为

`upload_release=false` 时只上传 workflow artifacts。

`upload_release=true` 时，会在全部 build matrix job 成功后创建或更新 GitHub Release：

- Release 仓库：运行此 workflow 的仓库。
- Tag：`v<version_name>`。
- Release 名称：`<repository_name> v<version_name>`。
- Release 文件：匹配 `<repository_name>-*` 的已下载构建 artifacts。

release job 使用 `contents: write`；其他 job 使用只读 contents 权限。

## Workflow summary

workflow 会把解析后的输入汇总成一个 `WORKFLOW_INPUTS_JSON` 对象传给 `.github/scripts/android-ci/print-workflow-inputs.py`。脚本用这一份对象同时渲染 GitHub step summary 和控制台报告，并追加解析出的 NDK revision、`ANDROID_NDK_HOME` 等动态字段。这样不需要分别维护 env 字段列表、Markdown 表格和 console print 字段列表。

summary 包含：

- 解析后的 repository 和 repository name。
- branch 输入值和解析后的 branch/ref。
- Source SHA。
- module、flavor、build type、原始 build options、基础 Gradle options、按任务签名决策、unsigned scope、pre-build command 和 Go 版本。
- build/test/release 选项。
- Runner label、JDK、请求的 NDK、解析出的 NDK revision 和 `ANDROID_NDK_HOME`。
- version name。
- 最终 build matrix：module、flavor、build type、artifact type、Gradle task 和 artifact name。

## 示例

### 1. 构建当前仓库默认模块

```yaml
repository: ""
branch: ""
module: app
build_type: debug
signing: false
```

### 2. 构建其他仓库的 release AAB

```yaml
repository: some-owner/some-repo
branch: main
module: app
build_type: aab
signing: true
upload_release: true
```

### 3. 构建多个模块与多个 flavor

```yaml
module: app,store
build_flavor: free,paid
build_type: all
```

### 4. 自动运行 NekoBox 风格前置构建

```yaml
module: app
build_type: release
pre_build_command: auto
go_version: ^1.25
```

### 5. 运行自定义前置构建命令

```yaml
module: app
build_type: release
pre_build_command: ./scripts/prepare-native-libs.sh
```

## 从其他 CI 触发

使用 GitHub 的 `workflow_dispatch` API。

请求：

```bash
POST /repos/{owner}/{repo}/actions/workflows/android.yml/dispatches
```

请求体示例：

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
    "signing": "false",
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

认证方式可以使用：

- GitHub Personal Access Token
- GitHub App token
- 其他有权限在 workflow 仓库中 dispatch workflow 的 token

如果目标仓库或递归 submodules 是私有的，请添加名为 `CHECKOUT_TOKEN` 的 repository secret，并赋予其读取目标仓库和 submodules 的权限。

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
  -f signing=false \
  -f pre_build_command=auto \
  -f go_version='^1.25' \
  -f build_test=true \
  -f upload_release=false \
  -f os_version=ubuntu-latest \
  -f jdk_version=21 \
  -f ndk_version=r27d
```

## 常见失败原因

- 目标仓库不存在或无权限访问。
- 目标分支、tag 或 SHA 不存在。
- 私有仓库或 submodule 需要 `CHECKOUT_TOKEN`。
- 模块名拼写错误，或模块不存在于 `./gradlew projects` 输出中。
- 请求的模块不是可安装 Android Application 模块。
- 请求的 flavor/build type 组合不存在。
- `build_options` 引号 / JSON 语法无效，或包含 Gradle 无法识别的参数。
- 勾选 `signing=true` 但签名变量/仓库配置不完整；workflow 会对 release/AAB/聚合任务自动回退到 `-Punsigned`，但目标项目本身也需要支持该 unsigned 属性。
- 自定义 `pre_build_command` 执行失败。
- auto 前置构建模式执行后未生成 `app/libs/libcore.aar`。
- 请求的 NDK 版本无法安装，找不到完整缓存，宿主系统对应的 NDK 工具链缺失，或修复后仍不完整。

## 开源许可

[MIT License](./LICENSE)

    Copyright (c) 2026 shiguobaona

    特此授予任何获得本软件及相关文档文件（“软件”）副本的人，不受限制地使用、复制、修改、合并、发布、分发、再许可和/或销售本软件副本的权利，但须在软件的所有副本或实质部分中包含上述版权声明和本许可声明。

    本软件按“原样”提供，不提供任何形式的明示或默示保证，包括但不限于适销性、特定用途适用性和非侵权性保证。
