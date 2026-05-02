# Android Build CI

此仓库包含一个 GitHub Actions 工作流程，用于从目标存储库构建 Android 应用安装包 (APK / AAB)。

:star: 中文说明 | [English README](README.md)

---

### 工作流运行原理概览

- 拉取指定仓库与分支代码，默认是当前仓库与 `main`
- 自动通过 Gradle Task Introspection 识别可构建的 Android Application 模块
- 识别可用的 build variant（包含 flavor / build type）
- 并行构建匹配的任务
- 上传构建产物为 artifact
- 可选发布 GitHub Release（默认关闭）

### 工作流文件

通常位于：

```yaml
.github/workflows/android.yml
```

### 输入参数

| 参数 | 说明 | 类型 | 默认值 |
|---|---|:---:|:---:|
| **repository** | 目标仓库，格式为 `owner/repo`。留空则使用当前仓库 | `string` | - |
| **branch** | 目标分支 | `string` | main |
| **module** | 目标模块，支持逗号分隔多个模块。留空则自动探测可安装的 Application 模块 | `string` | app |
| **build_flavor** | 构建风味，支持逗号分隔多个值。留空表示不过滤风味 | `string` | - |
| **build_type** | 构建类型 | choice: `debug`, `release`, `aab`, `all` | debug |
| **build_options** | 额外 Gradle 参数 | `string` | - |
| **build_test** | 是否先执行一次 `./gradlew build` | `boolean` | `false` |
| **upload_release** | 是否上传 GitHub Release | `boolean` | `false` |
| **os_version** | Runner 系统 | choice: `ubuntu-latest`, `ubuntu-22.04` | ubuntu-latest |
| **jdk_version** | JDK 版本 | choice: `25`, `24`, `23`, `22`, `21`, `17`, `11`, `8` | 17 |
| **ndk_version** | NDK 版本 | choice: `r29`, `r28c`, `r27d`, `r26d`, `r25c`, `r24`, `r23c`, `r22b`, `r21e`, `r20b` | r27d |

### `build_type` 取值

- `debug`
- `release`
- `aab`
- `all`：同时构建 `debug`、`release`、`aab`

### 行为说明

#### 模块

- 如果显式填写 `module`，workflow 会先校验模块是否存在
- 如果留空，workflow 会自动探测当前仓库中可安装的 Android Application 模块
- 找不到模块会直接失败，不会猜测

#### 风味

- `build_flavor` 支持多个风味以逗号分隔，例如：`free,paid`
- workflow 会通过 Gradle 任务列表识别实际存在的 variant
- 如果指定的风味不存在，会直接失败

#### 构建与产物

- `debug` / `release` 生成 APK
- `aab` 生成 AAB
- artifact 名称会带上仓库名、模块名、风味名、构建类型和时间戳
- artifact 路径会限定到对应模块目录

#### Release

- `upload_release=false` 不发布 Release
- `upload_release=true` 会把上传的 artifact 作为 GitHub Release 附件发布

### 示例

#### 1. 构建当前仓库默认模块

```yaml
repository: 留空
branch: main
module: app
build_type: debug
```

#### 2. 构建指定仓库的 release APK

```yaml
repository: some-owner/some-repo
branch: main
module: app
build_type: debug
upload_release: true
```

#### 3. 构建多个模块与多个风味

```yaml
module: app,store
build_flavor: free,paid
build_type: all
```

### 从其他 CI 触发

如果你要从其他 CI 系统调用这个工作流，最稳妥的方式是使用 GitHub 的 `workflow_dispatch` API。

#### 方式 A：GitHub Actions / 其他支持 HTTP 的 CI

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
    "build_test": "true",
    "upload_release": "false",
    "os_version": "ubuntu-latest",
    "jdk_version": "17",
    "ndk_version": "r27d"
  }
}
```

认证方式可以使用：
- GitHub Personal Access Token
- GitHub App token
- 其他有 `actions:write` 权限的 token

#### 方式 B：GitHub CLI

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

### 常见失败原因

- 仓库不存在或无权限访问
- 分支不存在
- 模块名拼错
- 指定的风味不存在
- 当前仓库没有可安装的 Android Application 模块
- `build_options` 传入了不合法的 Gradle 参数

## 开源许可

[MIT License](./LICENSE)

    Copyright (c) 2026 shiguobaona
    
    特此授予任何获得本软件及相关文档文件（“软件”）副本的人，不受限制地使用、复制、修改、合并、发布、分发、再许可和/或销售本软件副本的权利，但须在软件的所有副本或实质部分中包含上述版权声明和本许可声明。
    
    本软件按“原样”提供，不提供任何形式的明示或默示保证，包括但不限于适销性、特定用途适用性和非侵权性保证。
