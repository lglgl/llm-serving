pipeline {
    agent any

    options {
        // 禁止并发构建，避免同时覆盖镜像标签
        disableConcurrentBuilds()
        // 整个流水线最多运行 60 分钟
        timeout(time: 60, unit: 'MINUTES')
    }

    environment {
        HARBOR = 'harbor.local:30080'
        HARBOR_PROJECT = 'library'
        APP_IMAGE = 'llm-serving'
        LLAMA_IMAGE = 'llm-serving-llama'
        HARBOR_IP = '127.0.0.1'

        // Docker Desktop Kubernetes 实验环境
        K8S_CONTEXT = 'docker-desktop'
        K8S_NAMESPACE = 'llm-serving'
        APP_DEPLOYMENT = 'llm-serving'
        APP_CONTAINER = 'llm-serving'
        LLAMA_DEPLOYMENT = 'llm-serving-llama'
        LLAMA_CONTAINER = 'llm-serving-llama'
    }

    stages {
        stage('Checkout') {
            steps {
                echo '========== 阶段 1：检出 GitHub 代码 =========='
                checkout scm
                sh '''
                    set -eu
                    echo "工作目录：$(pwd)"
                    echo "Git 提交：$(git rev-parse --short HEAD)"
                    echo "分支：$(git branch --show-current)"
                '''
            }
        }

        stage('Check Environment') {
            steps {
                echo '========== 阶段 2：检查构建环境 =========='
                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
                    echo "操作系统：$(uname -s)"
                    echo "CPU 架构：$(uname -m)"
                    echo "当前用户：$(whoami)"
                    command -v docker
                    docker version
                    command -v kubectl
                    kubectl version --client
                '''
            }
        }

        stage('Check Harbor') {
            steps {
                echo '========== 阶段 3：检查 Harbor =========='
                sh '''
                    set -eu
                    HARBOR_URL="http://$HARBOR"
                    echo "Harbor 地址：$HARBOR_URL"
                    echo "连接 IP：$HARBOR_IP"

                    portal_status=$(curl --silent --show-error \
                        --connect-timeout 5 --max-time 10 \
                        --resolve "harbor.local:30080:$HARBOR_IP" \
                        -o /dev/null -w '%{http_code}' "$HARBOR_URL/")
                    if [ "$portal_status" != "200" ]; then
                        echo "ERROR：Harbor Portal 检查失败，HTTP $portal_status"
                        exit 1
                    fi
                    echo "Harbor Portal 检查通过"

                    registry_status=$(curl --silent --show-error \
                        --connect-timeout 5 --max-time 10 \
                        --resolve "harbor.local:30080:$HARBOR_IP" \
                        -o /dev/null -w '%{http_code}' "$HARBOR_URL/v2/")
                    case "$registry_status" in
                        200|401) echo "Registry API 检查通过，HTTP $registry_status" ;;
                        *) echo "ERROR：Registry API 检查失败，HTTP $registry_status"; exit 1 ;;
                    esac
                '''
            }
        }

        stage('Validate Files') {
            steps {
                echo '========== 阶段 4：检查项目文件 =========='
                sh '''
                    set -eu
                    test -f Dockerfile
                    test -f requirements.txt
                    test -f llama/Dockerfile
                    echo "Dockerfile、requirements.txt 和 llama/Dockerfile 均存在"

                    MODEL_FILE="llama/models/qwen2-0_5b-instruct-q4_k_m.gguf"
                    if git ls-files --error-unmatch "$MODEL_FILE" >/dev/null 2>&1; then
                        echo "ERROR：GGUF 模型文件不应提交到 Git"
                        exit 1
                    fi
                    echo "GGUF 模型未被 Git 跟踪"
                '''
            }
        }

        stage('Build llm-serving') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                echo '========== 阶段 5：构建 FastAPI 镜像 =========='
                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
                    IMAGE="$HARBOR/$HARBOR_PROJECT/$APP_IMAGE"
                    docker build --progress=plain --pull \
                        -t "$IMAGE:$BUILD_NUMBER" \
                        -t "$IMAGE:latest" \
                        -f Dockerfile .
                    echo "构建成功：$IMAGE:$BUILD_NUMBER"
                '''
            }
        }

        stage('Build llama + Qwen') {
            options { timeout(time: 20, unit: 'MINUTES') }
            steps {
                echo '========== 阶段 6：构建 llama.cpp + Qwen 镜像 =========='
                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
                    IMAGE="$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE"
                    # 模型文件由 llama/Dockerfile 下载，不提交到 Git
                    docker build --progress=plain --pull \
                        -t "$IMAGE:$BUILD_NUMBER" \
                        -t "$IMAGE:latest" \
                        -f llama/Dockerfile llama
                    echo "构建成功：$IMAGE:$BUILD_NUMBER"
                '''
            }
        }

        stage('Verify Images') {
            steps {
                echo '========== 阶段 7：验证本地镜像 =========='
                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
                    docker image inspect "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER" >/dev/null
                    docker image inspect "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER" >/dev/null
                    echo "两个镜像均已成功生成"
                '''
            }
        }

        stage('Push to Harbor') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                echo '========== 阶段 8：推送镜像到 Harbor =========='
                withCredentials([
                    usernamePassword(
                        credentialsId: 'harbor-credentials',
                        usernameVariable: 'HARBOR_USER',
                        passwordVariable: 'HARBOR_PASSWORD'
                    )
                ]) {
                    sh '''
                        set -eu
                        set +x
                        export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
                        trap 'docker logout "$HARBOR" >/dev/null 2>&1 || true' EXIT

                        printf '%s' "$HARBOR_PASSWORD" |
                            docker login "$HARBOR" -u "$HARBOR_USER" --password-stdin

                        docker push "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER"
                        docker push "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:latest"
                        docker push "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER"
                        docker push "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:latest"
                        echo "两个镜像的版本标签和 latest 标签均已推送"
                    '''
                }
            }
        }

        stage('Deploy to Kubernetes') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                echo '========== 阶段 9：部署到 Docker Desktop Kubernetes =========='
                withCredentials([
                    usernamePassword(
                        credentialsId: 'harbor-credentials',
                        usernameVariable: 'HARBOR_USER',
                        passwordVariable: 'HARBOR_PASSWORD'
                    )
                ]) {
                    sh '''
                        set -eu
                        set +x
                        export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                        kubectl config use-context "$K8S_CONTEXT"
                        kubectl get nodes
                        kubectl create namespace "$K8S_NAMESPACE" \
                            --dry-run=client -o yaml | kubectl apply -f -

                        # 创建/更新 Kubernetes 拉取 Harbor 私有镜像的凭据
                        kubectl -n "$K8S_NAMESPACE" create secret docker-registry harbor-pull-secret \
                            --docker-server="$HARBOR" \
                            --docker-username="$HARBOR_USER" \
                            --docker-password="$HARBOR_PASSWORD" \
                            --dry-run=client -o yaml | kubectl apply -f -

                        # 本阶段更新已有 Deployment；首次部署前需要先创建 Deployment 和 Service
                        kubectl -n "$K8S_NAMESPACE" get deployment "$APP_DEPLOYMENT"
                        kubectl -n "$K8S_NAMESPACE" get deployment "$LLAMA_DEPLOYMENT"

                        # 为两个 Deployment 配置镜像拉取凭据
                        kubectl -n "$K8S_NAMESPACE" patch deployment "$APP_DEPLOYMENT" \
                            --type=merge -p '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"harbor-pull-secret"}]}}}}'
                        kubectl -n "$K8S_NAMESPACE" patch deployment "$LLAMA_DEPLOYMENT" \
                            --type=merge -p '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"harbor-pull-secret"}]}}}}'

                        # 更新到当前 Jenkins 构建号
                        kubectl -n "$K8S_NAMESPACE" set image \
                            "deployment/$APP_DEPLOYMENT" \
                            "$APP_CONTAINER=$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER"
                        kubectl -n "$K8S_NAMESPACE" set image \
                            "deployment/$LLAMA_DEPLOYMENT" \
                            "$LLAMA_CONTAINER=$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER"

                        kubectl -n "$K8S_NAMESPACE" rollout status \
                            "deployment/$APP_DEPLOYMENT" --timeout=180s
                        kubectl -n "$K8S_NAMESPACE" rollout status \
                            "deployment/$LLAMA_DEPLOYMENT" --timeout=180s
                        kubectl -n "$K8S_NAMESPACE" get deployments,pods,services
                    '''
                }
            }
        }

        stage('Smoke Tests') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                echo '========== 阶段 10：冒烟测试 =========='
                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                    echo "[1] 检查 Deployment rollout"
                    kubectl -n "$K8S_NAMESPACE" rollout status \
                        "deployment/$APP_DEPLOYMENT" --timeout=180s
                    kubectl -n "$K8S_NAMESPACE" rollout status \
                        "deployment/$LLAMA_DEPLOYMENT" --timeout=180s

                    echo "[2] 在集群内部测试 FastAPI、llama.cpp 和 Qwen 推理"
                    TEST_POD="llm-smoke-test"
                    kubectl -n "$K8S_NAMESPACE" delete pod "$TEST_POD" \
                        --ignore-not-found=true --wait=true

                    # 临时 curl Pod 通过 Kubernetes Service 访问应用
                    kubectl -n "$K8S_NAMESPACE" run "$TEST_POD" \
                        --image=curlimages/curl:8.12.1 \
                        --restart=Never --rm -i --attach \
                        --command -- sh -ec '
                            set -eu
                            FASTAPI="http://llm-serving:8000"
                            QWEN="http://llm-serving-llama:8080"

                            echo "[Test A] FastAPI OpenAPI"
                            curl -fsS --max-time 15 "$FASTAPI/openapi.json" -o /tmp/openapi.json
                            echo "PASS: FastAPI is reachable"

                            echo "[Test B] llama.cpp health"
                            curl -fsS --max-time 20 "$QWEN/health"
                            echo
                            echo "PASS: llama.cpp health endpoint"

                            echo "[Test C] Qwen models endpoint"
                            curl -fsS --max-time 20 "$QWEN/v1/models" -o /tmp/models.json
                            cat /tmp/models.json
                            grep -q "\"data\"" /tmp/models.json
                            echo
                            echo "PASS: Qwen models endpoint"

                            echo "[Test D] Direct Qwen inference"
                            curl -fsS --max-time 120 "$QWEN/v1/chat/completions" \
                                -H "Content-Type: application/json" \
                                -d "{\"model\":\"qwen2:0.5b\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK\"}],\"max_tokens\":16,\"stream\":false}" \
                                -o /tmp/qwen-response.json
                            cat /tmp/qwen-response.json
                            grep -q "\"choices\"" /tmp/qwen-response.json
                            echo
                            echo "PASS: Qwen generated a response"

                            echo "[Test E] FastAPI end-to-end inference"
                            curl -fsS --max-time 120 "$FASTAPI/v1/chat/completions" \
                                -H "Content-Type: application/json" \
                                -d "{\"model\":\"qwen2:0.5b\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK\"}],\"max_tokens\":16,\"stream\":false}" \
                                -o /tmp/fastapi-response.json
                            cat /tmp/fastapi-response.json
                            grep -q "\"choices\"" /tmp/fastapi-response.json
                            echo
                            echo "PASS: FastAPI returned a chat completion"
                            echo "ALL SMOKE TESTS PASSED"
                        '

                    echo "[3] 最终资源状态"
                    kubectl -n "$K8S_NAMESPACE" get deployments,pods,services
                '''
            }
        }
    }

    post {
        success {
            echo """
            ========================================
            CI/CD 成功
            构建号：${env.BUILD_NUMBER}
            FastAPI 镜像：${env.HARBOR}/${env.HARBOR_PROJECT}/${env.APP_IMAGE}:${env.BUILD_NUMBER}
            Qwen 镜像：${env.HARBOR}/${env.HARBOR_PROJECT}/${env.LLAMA_IMAGE}:${env.BUILD_NUMBER}
            Kubernetes 命名空间：${env.K8S_NAMESPACE}
            ========================================
            """
        }
        failure {
            echo """
            ========================================
            CI/CD 失败
            构建号：${env.BUILD_NUMBER}
            请查看最后一个失败阶段的日志。
            常见原因：Harbor 认证/DNS、Kubernetes 权限、
            Deployment/Service 不存在、镜像拉取失败或 API 路径不匹配。
            ========================================
            """
        }
        always {
            echo "Pipeline 结束时间：${new Date()}"
            echo "Jenkins Build Number：${env.BUILD_NUMBER}"
            echo "最终构建结果：${currentBuild.currentResult}"
        }
    }
}
