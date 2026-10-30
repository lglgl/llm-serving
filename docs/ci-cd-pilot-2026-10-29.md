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

### 步骤 3：完整本地 CI 重跑

- 将试点代码提交到本地 `dev`：`349c0f3cd326`，确保镜像标签与本次源码一致；未推送远端。
- 执行 `SEMGREP_BIN="$HOME/.local/helmsman-tools/bin/semgrep" bash scripts/ci-pilot.sh`，结果 `CI_PILOT_RESULT=passed`。
- 8 项 pytest 全部通过；Starlette/httpx 弃用警告仍存在。
- gitleaks 扫描应用、测试、pilot、chart、脚本、Jenkinsfile 和 README，无泄漏发现；Semgrep 对 `app/` 扫描无阻断发现。
- 网关与 mock 镜像均以 `349c0f3cd326` 构建成功；Trivy 两镜像的 CRITICAL 漏洞扫描均为 0。Trivy 提示部分漏洞严重级别采用其他厂商数据源，属于扫描器说明。
- 动态映射端口 smoke 通过：`/readyz` ready、`/health` healthy、模型别名 `qwen3:8b` 可见、聊天请求返回确定性 mock 回复。脚本退出时清理 CI 容器和网络。

状态：本地 CI 全部通过。Jenkins Job 未触发：API 403 且 Job 仍指向旧 `main`；此次未推送远端、未运行 Jenkins Credentials 的 Harbor push stage，因此不能视为 Jenkins 构建或 Harbor 发布成功。

### 步骤 4：Kubernetes CD 与回滚

- 使用 `docker-desktop` context，在新建隔离 namespace `llm-serving-pilot` 执行 `bash scripts/cd-pilot.sh 349c0f3cd326 349c0f3cd326`。Helm Chart lint 通过，网关与 mock Deployment 均 rollout 成功。
- 首轮部署 smoke 通过。随后脚本以无害的 Pod-template stamp 变更生成新 Helm revision，再执行 Helm rollback。
- 首次 CD 尝试回滚成功，但回滚替换了网关 Pod，使原 `kubectl port-forward` 随旧 Pod 终止；回滚后的 smoke 得到 Connection refused。日志确认新 Pod Running，服务可通过重新建立 port-forward 访问。故障归因为脚本生命周期处理不完整，不是应用回滚失败。
- 修复 CD 脚本：每次 smoke 前等待端口转发可用；回滚后停止旧转发并重新启动，检查转发进程退出并输出日志。
- 重跑 CD：初始 smoke 通过，试验升级成功，回滚到 revision 4 成功，回滚后的 readiness/model/chat smoke 再次通过；结果 `CD_PILOT_RESULT=passed`。最终 Helm release 保持 deployed，隔离 namespace 保留供检查。
- 本地 Docker Desktop 使用共享镜像缓存，Chart 配置 `imagePullPolicy: Never`。因此验证的是本机构建镜像到本地 Kubernetes 的发布/回滚链路；没有验证集群从 Harbor 拉取镜像。

状态：本地 Kubernetes CD 和 Helm 回滚通过；真实模型权重、GPU 推理、Harbor push/pull、Jenkins 执行均不在已验证范围。

### 结果与待办

- 已证明：网关代码测试、镜像构建与本地安全扫描、mock 推理链路、Kubernetes 沙箱部署和 Helm 回滚。
- 尚未证明：远程 Jenkins CI、Harbor 鉴权推送/集群拉取、真实 vLLM/权重发布、模型质量评测或生产入口。
- 后续若要接真实模型发布：先修复 Jenkins Job SCM/脚本分支配置并提供受控 Jenkins API 执行通道；验证 Harbor 凭据和节点拉取，再单独规划 GPU/权重存储、模型版本与质量门禁。不要把当前 mock CD 作为真实模型验收证据。

### 步骤 5：Harbor push/pull 与 Helmsman 应用发布模块接入（2026-10-30）

- 项目负责人要求 llm-serving 测试发布通过 Helmsman“应用发布”模块。该模块此前只接入 `hm-demo`；本次仅将 `llm-serving-pilot` 接入既有 Argo Rollouts 模块，不修改旧 `llm-serving` namespace。
- 复用本机已有 Docker 登录项，没有输出或复制凭据。先确认目标 tag 不存在，再推 app 与 mock 镜像：tag `afad3bf86756` 的 digest 分别为 app `sha256:3d0a30ae502b597bbafd501fb2433f33b166120f16f33d5fd6c78bc769b678c1`、mock `sha256:ace0cefb1f4a7c979164b15708eb522b04ac56ab05437f0ac29256a039aa3cc2`。
- 为强制 Kubernetes 从 Harbor 拉取，另推此前不存在的 `afad3bf86756-harbor-20261030` tag，并临时用 `imagePullPolicy: Always` 部署。Kubernetes Events 记录 app 与 mock 均成功拉取，Pod `imageID` 与 Harbor digest 一致；readiness、模型列表和 mock 聊天 smoke 通过。该临时 Helm 验证随后回滚；项目负责人要求经模块发布后，未再用 Helm 切换候选 tag。
- Helm Chart 增加可选 Rollout、canary Service 和 readiness AnalysisTemplate；默认关闭 Rollout，保持原 CD pilot 行为。Helm lint 与 `kubectl apply --dry-run=server` 通过。用稳定 tag `afad3bf86756` 安装 Rollout 基线（Helm revision 12），Argo Rollouts phase Healthy，基线 smoke 通过。
- Helmsman 增加跨仓库源码审计配置，模块通过本地 `llm-serving` Git 仓库的提交归档源码。应用发布单 #9 候选 tag `afad3bf86756-harbor-20261030` 的 gitleaks / Semgrep 通过；Trivy Critical=0、High=45（warning）；GLM 语义评审返回 HTTP 429（无可用额度，非阻断）。
- 通过 Helmsman 模块申请开始金丝雀，生成审批单 #21（风险 L2、需一位审批人）；随后负责人在 UI 批准，模块开始候选发布。

- 负责人随后在 Helmsman UI 批准 #21，发布单 #9 由模块完成 20%→50%→100%，最终 Healthy / 已全量；stable Service smoke 通过。
- 处理 Helm 漂移：Chart `values.yaml` 默认 tag 更新为 `afad3bf86756-harbor-20261030`，Rollout enabled、imagePullPolicy Always；与当前 release manifest 对比仅差 app image tag。普通 `helm upgrade` 沿用旧用户值，未同步；以 `--reset-values` 重跑后 Helm revision 14 与模块 live tag 一致，Rollout 未重启 Pod，发布后 smoke 通过。
- `scripts/cd-pilot.sh` 现在检测到现有 `llm-serving-pilot` Rollout 会拒绝直接 Helm CD；非 Rollout 的独立本地试点路径会显式关闭 Rollout，避免误把 Deployment 脚本用于模块管理的发布。
- Chart 变更尚未提交或纳入 Argo CD GitOps；Helm 本地 release 与当前工作区已一致，持久化/远端统一声明仍待 S04 补齐。

状态：Harbor push/pull、模块审计与批准后的应用模块发布通过。仍未验证 Jenkins Job、SBOM/cosign、Argo CD GitOps、Kyverno、真实 vLLM/GPU/权重和模型质量。
