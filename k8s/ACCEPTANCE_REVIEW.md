# 云原生配置验收分析报告

- **项目**：llm-serving（FastAPI + Ollama，OpenAI-compatible LLM Serving）
- **架构**：Client → Ingress(nginx) → FastAPI(Deployment) → Ollama(Deployment) → Qwen2:0.5b
- **交付物**：`k8s/` Helm Chart（Chart.yaml + values.yaml + 12 个模板）
- **分析日期**：2026-10-10
- **范围说明**：按用户要求，**Metrics Server 与 HPA 的真实指标 / 扩缩容验证暂缓**，留到云环境迁移后执行。本报告的 HPA 项只校验模板与配置，不做实测。
- **方法**：静态审查全部 Helm 模板、values.yaml、Dockerfile、FastAPI 代码；手动核对 `.Values.*` 引用与 values 键的一致性。

---

## 一、总览结论

| 等级 | 数量 | 说明 |
|---|---|---|
| ✅ 通过（含应用型 N/A） | 15 | Namespace / Deployment / Service / ConfigMap / Secret(无需) / ServiceAccount / Resources / Startup / Readiness / Liveness / NetworkPolicy / PVC(无需) / RollingUpdate / FailureRecovery |
| ⚠️ 通过但需注意 | 3 | Helm / SecurityContext / Termination |
| ⏸️ 暂缓 / 用户不处理 | 3 | HPA（按用户要求）+ Ingress 云端 TLS/域名 + 镜像 registry 前缀/拉取密钥（用户明确不处理，云迁移阶段另行处理） |
| ❌ 硬性不通过 | 0 | 无 |

**总体判断**：所有「必须」项在配置层面均已具备，没有硬性阻断问题。本次已修复两处——`/health` 在 Ollama 不可用时返回 503（就绪探针现在能真正摘除流量）、`namespace.yaml` 改为参数化。剩余需补强集中在 3 类——（1）`helm lint/template` 未实际执行（本机未装 helm）；（2）安全上下文尚未加固；（3）终止宽限对长请求偏短。云迁移相关的 Ingress TLS/域名、镜像 registry 前缀/imagePullSecrets 由用户明确「不处理」，留到云迁移阶段另行处理。

---

## 二、逐条验收明细

| # | 检查项 | 状态 | 证据 | 验收结论 |
|---|---|---|---|---|
| 1 | Namespace | ✅ | `k8s/templates/namespace.yaml`（name: llm-serving）；deployment/service/ingress 等用 `{{ .Values.namespace }}`=llm-serving | 应用资源均位于 llm-serving |
| 2 | Deployment | ✅ | `deployment.yaml`（replicas:1，RollingUpdate maxUnavailable:0/maxSurge:1）、`ollama-deployment.yaml`（replicas:1） | Pod 定义完整可用；Ollama 用默认滚动策略（见 #17 备注） |
| 3 | Service | ✅ | `service.yaml`（llm-serving:8000→8000，ClusterIP）、`ollama-service.yaml`（llm-serving-ollama:11434→11434） | selector 与 Pod label 精确匹配，端口正确 |
| 4 | ConfigMap | ✅ | `configmap.yaml` 注入 OLLAMA_BASE_URL / DEFAULT_MODEL；`deployment.yaml` 用 `envFrom: configMapRef` | 修改 values 后 `helm upgrade` 即可更新 |
| 5 | Secret | ✅(N/A) | 仓库内无 Secret 模板；当前敏感信息为空 | 当前无密钥明文写入 ConfigMap/镜像，满足"条件必需"。建议为未来凭证（镜像拉取、Ollama Key）预留 Secret 模板 |
| 6 | ServiceAccount | ✅ | `serviceaccount.yaml`、`ollama-serviceaccount.yaml` 均为专用 SA，且 `automountServiceAccountToken: false`；Pod spec 中也显式关闭 | 独立 SA + 禁用 Token 挂载，符合最小权限 |
| 7 | Resources | ✅ | values.yaml：fastapi 100m/128Mi–500m/512Mi；ollama 250m/512Mi–2/2Gi；两 Deployment 均以 `toYaml` 注入 | 两 Deployment 均设 requests/limits |
| 8 | Startup Probe | ✅ | FastAPI tcpSocket 端口，failureThreshold 30×5s=150s；Ollama httpGet /api/tags，60×5s=300s | 模型加载期不会被过早判失败 |
| 9 | Readiness Probe | ✅ | `deployment.yaml` 用 `httpGet /health`；`app/main.py` 的 `/health` 在 Ollama 不可用时 `raise HTTPException(503)` | **已修复（2026-10-10）**：`/health` 在 Ollama 不可用时返回 503，就绪探针将 Pod 移出 Service 端点（fail-closed）；存活探针为 TCP 端口检测，Ollama 抖动不会误重启。新增 `tests/test_api.py::test_health_endpoint_degraded` 锁定该行为 |
| 10 | Liveness Probe | ✅ | FastAPI 用 tcpSocket（不依赖 Ollama）；Ollama 用 httpGet /api/tags | 设计合理：避免 Ollama 抖动引发 FastAPI 无谓重启 |
| 11 | Ingress | ⏸️ | `ingress.yaml`：host llm-serving.local，path /，backend llm-serving:8000，ingressClassName nginx | 本地可用。**用户明确不处理（2026-10-10）**：云迁移期的 TLS、真实域名、cert-manager 注解留待云迁移阶段处理；当前保持本地可用 |
| 12 | PVC | ✅(N/A) | 无 PVC；Ollama 镜像 `COPY models/ /models/`，`OLLAMA_MODELS=/models` | 模型已打进镜像，无需持久化，符合"按需"。权衡：换模型需重建镜像、镜像偏大 |
| 13 | NetworkPolicy | ✅ | `app-networkpolicy.yaml`：仅放通 ingress-nginx 命名空间→8000；`ollama-networkpolicy.yaml`：仅放通 label app=llm-serving 的 Pod→11434（仅 Ingress 类型，出口默认放行） | 边界合理。**前提**：集群 CNI 需支持策略执行（Calico/Cilium）；Docker Desktop 默认网络可能不生效，迁移云后需验证 |
| 14 | HPA | ⏸️ | `hpa.yaml`：目标 llm-serving Deployment，CPU 70%，min1/max3 | 模板有效，**实测暂缓**。注意：仅扩 FastAPI，Ollama 固定 1 副本，3 副本时可能成为瓶颈 |
| 15 | Helm | ⚠️ | Chart.yaml(v2)、values.yaml、12 模板；已手工核对全部 `.Values.*` 引用均能在 values 中找到 | **未执行 `helm lint`/`helm template`**（本机未安装 helm）。建议安装后跑 `helm lint k8s` 与 `helm template k8s --dry-run`。`namespace.yaml` 已改为 `name: {{ .Values.namespace }}`（2026-10-10 修复） |
| 16 | 镜像管理 | ⏸️(部分) | FastAPI tag 0.2.1、Ollama 0.1.0，均显式版本 + IfNotPresent | README 构建标签 0.1.0 与 values 0.2.1 不一致的文档漂移已在 2026-10-10 随模型统一一并修正。**registry 前缀、Ollama 基础镜像 `:latest` 浮动标签、imagePullSecrets 由用户明确不处理**，留待云迁移阶段处理 |
| 17 | 滚动更新 | ✅ | FastAPI 显式 RollingUpdate（maxUnavailable:0/maxSurge:1，零中断能力） | Ollama 用默认策略（1 副本下实际可 1 个 surge），建议显式化以对齐。回滚支持 `kubectl rollout undo` / `helm rollback` |
| 18 | 安全上下文 | ⚠️ | 两 Deployment 均未设 securityContext | 建议评估：Ollama 基础镜像常以 root 运行，non-root 较难；至少可加 `allowPrivilegeEscalation:false`、`readOnlyRootFilesystem:true`（模型已打镜像，RO 可行）、`seccompProfile` |
| 19 | 终止处理 | ⚠️ | FastAPI terminationGracePeriodSeconds:30，Ollama:60；无 preStop | 风险：长耗时非流式请求 `request_timeout=300s` 在 30s 宽限内可能被杀。建议适当抬高宽限或加 preStop 排水 |
| 20 | 故障恢复 | ✅ | 探针检测 + Deployment 修订历史 + Helm 回滚 | 镜像拉取失败→ImagePullBackOff；配置错误→env 缺失→健康失败/CrashLoop；均可定位并 `helm rollback` 恢复。建议补充一份 runbook 并在集群实测 |

---

## 三、跨项风险与待办（按优先级）

**P0 — 上云前必须解决**
1. 安装 helm，执行 `helm lint k8s` 与 `helm template k8s --dry-run`，确保模板可渲染、lint 通过（当前为环境工具缺口）。

**⏸️ 用户明确不处理（云迁移阶段另行处理）**
- 镜像仓库策略：registry 前缀、Ollama 基础镜像固定版本（去 `:latest`）、`imagePullSecrets`（私有仓库场景）。
- Ingress 上云配置：真实域名 + TLS（cert-manager 或平台证书），替换 `llm-serving.local`。

**P1 — 强烈建议**
5. 固定 Ollama 基础镜像版本（去掉 `:latest`）——注：此项已归入上面「用户不处理」清单，待云迁移阶段处理。
7. 安全上下文加固（#18）。

**P1 — 已修复（2026-10-10）**
- ~~4. `/health` 与就绪探针一致性~~：已在 `app/main.py` 让 `/health` 在 Ollama 不可用时返回 503，并加测试 `test_health_endpoint_degraded` 锁定行为（见 #9）。
- ~~6. `namespace.yaml` 硬编码~~：已改为 `name: {{ .Values.namespace }}`，与 values 联动。

**P2 — 文档 / 一致性**
8. ~~对齐模型表述：代码默认 `qwen3:8b`、README 用 `qwen3:8b`，但部署实际由 ConfigMap 注入 `qwen2:0.5b`（已打进镜像）。运行态以 ConfigMap 为准，但代码/文档默认会误导，建议统一。~~ **已修复（2026-10-10）**：已将 `app/config.py` 默认模型、`README.md`、`scripts/client.py`、`scripts/benchmark.py`、`tests/test_api.py` 全部统一为 `qwen2:0.5b`，与 ConfigMap/values（`ollama.model`）及镜像内打包模型一致，消除模型表述不一致。
9. README 构建标签 0.1.0 与 values 0.2.1 不一致，更新文档。
10. 单副本无 HA：两 Deployment 均为 1 副本，节点故障即中断；如需要可用性，考虑副本数 / PodDisruptionBudget。

---

## 四、HPA 暂缓项说明

按用户要求，HPA 仅做模板与配置校验（已通过），真实指标与扩缩容验证在云环境（部署 Metrics Server）后再进行。届时需验证：Metrics Server 已装、`kubectl get hpa` 能取到 CPU 指标、压测下副本能在 1–3 之间伸缩、伸缩后不影响 Ollama（Ollama 固定 1 副本）的吞吐。

---

## 五、更新记录

- **2026-10-10**：统一模型表述为 `qwen2:0.5b`。
  - `app/config.py`：`default_model` 默认由 `qwen3:8b` → `qwen2:0.5b`。
  - `README.md`：本地 Ollama 拉取/运行与示例请求中的 `qwen3:8b` → `qwen2:0.5b`。
  - `scripts/client.py`、`scripts/benchmark.py`：`MODEL` 常量 `qwen3:8b` → `qwen2:0.5b`。
  - `tests/test_api.py`：测试用模型名 `qwen3:8b` → `qwen2:0.5b`。
  - 至此代码、测试、脚本、文档、Helm ConfigMap/values、镜像内打包模型六处模型标识完全一致，均为 `qwen2:0.5b`。本报告中 P2 第 8 条「模型表述不一致」标记已修复。

- **2026-10-10（第二轮）**：修复探针与命名空间参数化，云迁移缺口按用户要求「不处理」。
  - `app/main.py`：`/health` 在 Ollama 不可用时由返回 200(degraded) 改为 `raise HTTPException(503)`，使就绪探针真正将 Pod 移出 Service 端点（fail-closed）；存活探针为 TCP 端口检测，Ollama 抖动不再误重启。关键逻辑均加中文注释。
  - `k8s/templates/namespace.yaml`：`name` 由硬编码 `llm-serving` 改为 `{{ .Values.namespace }}`，与 values 联动。
  - `k8s/templates/deployment.yaml`：就绪探针注释更新为说明「`/health` 在 Ollama 不可用时返回 503」。
  - `tests/test_api.py`：新增 `test_health_endpoint_degraded`，断言 Ollama 不可用时 `/health` 返回 503。测试由 3 passed → 4 passed。
  - 报告同步更新：#9 Readiness 由 ⚠️ 改为 ✅；#11 Ingress、#16 镜像管理（云相关部分）标记为 ⏸️ 用户不处理；#15 namespace 模板化小瑕疵已修复。
