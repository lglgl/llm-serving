# CI/CD 小范围试点过程记录

日期：2026-10-29（Asia/Shanghai）  
仓库：`llm-serving`，分支 `dev`  
范围：FastAPI + LiteLLM 网关；本轮先验证应用镜像 CI，再验证 Kubernetes CD。模型权重和 vLLM GPU 后端不纳入首轮部署。

> 每一步记录实际动作、结果和故障。`.env` 不读取、不复制、不写入 Git；密钥只使用现有 Jenkins Credentials 或 Kubernetes Secret。

## 测试目标与通过条件

1. CI：单测、镜像构建、容器健康检查、文本请求端到端转发、镜像安全扫描通过；镜像用 Git SHA 标识并推送 Harbor。
2. CD：使用 Harbor 镜像部署网关，Deployment/Service Ready；检查 `/health`、`/v1/models` 和聊天请求；回滚到前一镜像后服务恢复。
3. 后端：首轮优先使用确定性测试后端验证链路，不把模拟推理记作真实模型质量或模型权重发布。

## 过程记录

### 步骤 0：执行前环境检查

- 仓库工作区干净；当前分支 `dev`，HEAD `8ac0367`（2026-10-29 的 LiteLLM + vLLM 改造）。
- Jenkins 登录页返回 HTTP 200，但 `/api/json` 返回 HTTP 403；当前尚无可用 API 认证来触发已有 Job。
- 本机 `llm-serving-ci` / `llm-serving-cd` 的 Job 配置均指向 GitHub `main`，脚本路径分别为 `Jenkinsfile.ci` / `Jenkinsfile.cd`；当前仓库 `dev` 分支没有这两个文件。GitHub `dev` 当前是 `8ac0367`，`main` 仍为旧提交 `2ade197`。
- Docker CLI 无法连接 `~/.docker/run/docker.sock`，提示 Docker daemon 未运行。
- `kubectl config current-context` 为 `docker-desktop`，但 Kubernetes API `127.0.0.1:6443` 拒绝连接；Helm 也报告集群不可达。
- 启动 Docker Desktop 后，Docker Engine `28.4.0` 和 Kubernetes API 恢复；`llm-serving` namespace 中没有 Pod，旧 Helm release `llm-serving` 仍显示 `deployed`，存在 Helm 记录与运行工作负载不一致的情况。cert-manager cainjector 在重启后短暂为 Error，待后续复查。
- 基线测试故障：直接运行 `.venv/bin/pytest -q` 因 `ModuleNotFoundError: app` 无法收集；加 `PYTHONPATH=.` 后因该旧虚拟环境缺少 `litellm` 仍无法收集。处理：新建隔离 `.venv-ci` 并安装仓库声明的 requirements，不覆盖 `.venv`。
- 处理：先按 `dev` 当前代码准备仓库内 Jenkinsfile 和部署试点；Jenkins API 若仍 403，则用本地同阶段脚本验证，不绕过 Jenkins 授权，也不把本地结果冒充 Jenkins 构建。

状态：进行中。

### 步骤 1：基线依赖与现有测试

- 初次 `./.venv/bin/pytest -q` 失败：pytest 找不到仓库根目录中的 `app` 包。
- 加 `PYTHONPATH=.` 后再次失败：原 `.venv` 缺少 `litellm`，证明旧虚拟环境与当前提交依赖不一致。
- 在 `/tmp/llm-serving-ci-venv` 创建隔离环境并安装 `requirements.txt`；没有覆盖或读取 `.env`。
- 用 `PYTHONPATH=. /tmp/llm-serving-ci-venv/bin/python -m pytest -q` 通过：3 passed。出现 1 条 Starlette/httpx 弃用警告；依赖按范围安装、没有锁文件，构建可重复性仍需后续改善。
- 依赖安装后 Docker Engine 为 28.4.0，Kubernetes API `/readyz` 返回 `ok`，节点 Ready；`llm-serving` namespace 无运行 Pod，旧 Helm release 仍显示 `deployed`。cert-manager 三个 Deployment 已恢复 Ready，但有重启与短暂探针失败事件。
- 扫描工具：本机有 gitleaks 和 Trivy；PATH 中没有 semgrep，后续检查可用的既有隔离安装路径。Jenkins `/job/llm-serving-ci/api/json` 仍返回 403。

状态：基线测试通过；待补端到端测试与流水线配置。

### 步骤 2：流水线、镜像与首次 CI 执行

- 新增 `/readyz`、8 条 API 测试、确定性 OpenAI-compatible mock backend、`llm-serving-pilot` Helm Chart、CI/CD shell 脚本及 Jenkinsfile；Chart lint 和 `kubectl --dry-run=client` 通过。
- 完整 CI 首次运行：依赖安装成功，8 个测试通过；gitleaks 对源码/脚本/构建定义检查未发现泄漏；Semgrep 使用本机隔离安装版，对 `app/` 扫描无阻断项；网关与 mock 镜像均构建成功，Trivy CRITICAL 扫描通过。
- 首次 CI 失败在容器 smoke：临时 API 容器端口已分配，但应用刚启动时连接被远端关闭；smoke 重试未捕获该连接异常。脚本陷阱已清理临时容器和 Docker 网络，未留下 CI 容器。
- 诊断：手工启动同一组网关/mock 镜像，Uvicorn 启动正常；等待 8 秒后 smoke 全部通过。故障是进程启动时序竞争，不是应用或后端响应问题。诊断容器和 Docker 网络已清理。
- 修复：smoke 重试现在捕获 `RemoteDisconnected` 所属的连接/HTTP 异常；后续再跑完整 CI。

状态：CI 扫描和构建通过；容器 smoke 待重跑。
