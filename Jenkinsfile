
pipeline {
    agent any

    options {
        // 禁止并发构建，避免同时覆盖镜像标签
        disableConcurrentBuilds()

        // 整个流水线最多运行 60 分钟
        timeout(time: 60, unit: 'MINUTES')
    }

    environment {
        // Harbor 镜像仓库地址，当前使用 HTTP
        HARBOR = 'harbor.local:30080'

        // Harbor 项目名称
        HARBOR_PROJECT = 'library'

        // FastAPI 服务镜像
        APP_IMAGE = 'llm-serving'

        // llama.cpp + Qwen 服务镜像
        LLAMA_IMAGE = 'llm-serving-llama'

        // Docker Desktop Kubernetes 的本机入口
        HARBOR_IP = '127.0.0.1'
    }

    stages {
        // ============================================================
        // 阶段 1：检出 GitHub 代码
        // ============================================================
        stage('Checkout') {
            steps {
                echo '========== 阶段 1：检出 GitHub 代码 =========='

                // 使用 Jenkins 任务中配置的 SCM
                checkout scm

                sh '''
                    set -eu

                    echo "当前工作目录：$(pwd)"
                    echo "当前 Git 提交：$(git rev-parse --short HEAD)"
                    echo "当前分支：$(git branch --show-current)"
                '''
            }
        }

        // ============================================================
        // 阶段 2：检查构建环境
        // ============================================================
        stage('Check Environment') {
            steps {
                echo '========== 阶段 2：检查构建环境 =========='

                sh '''
                    set -eu

                    # Jenkins 在 macOS 上运行时，补充 Homebrew 路径
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                    echo "操作系统：$(uname -s)"
                    echo "CPU 架构：$(uname -m)"
                    echo "当前用户：$(whoami)"
                    echo "PATH=$PATH"

                    # 检查 Docker CLI 是否存在
                    if ! command -v docker >/dev/null 2>&1; then
                        echo "ERROR：找不到 Docker CLI"
                        exit 1
                    fi

                    echo "Docker CLI 路径：$(command -v docker)"

                    # 同时检查 Docker Client 和 Docker Server
                    docker version

                    echo "Docker 环境检查通过"
                '''
            }
        }

        // ============================================================
        // 阶段 3：检查 Harbor
        // ============================================================
        stage('Check Harbor') {
            steps {
                echo '========== 阶段 3：检查 Harbor =========='

                sh '''
                    set -eu

                    HARBOR_URL="http://$HARBOR"

                    echo "Harbor 地址：$HARBOR_URL"
                    echo "连接 IP：$HARBOR_IP"

                    # 使用 --resolve 绕过系统 DNS 查询。
                    # HTTP Host 仍然是 harbor.local:30080，
                    # 因此 NGINX Ingress 可以匹配 Harbor 路由。

                    echo "检查 Harbor Portal..."

                    portal_status=$(curl --silent --show-error \
                        --connect-timeout 5 \
                        --max-time 10 \
                        --resolve "harbor.local:30080:$HARBOR_IP" \
                        -o /dev/null \
                        -w '%{http_code}' \
                        "$HARBOR_URL/")

                    if [ "$portal_status" != "200" ]; then
                        echo "ERROR：Harbor Portal 检查失败"
                        echo "HTTP 状态码：$portal_status"
                        echo "请检查 Ingress Host 和 Harbor Portal 后端"
                        exit 1
                    fi

                    echo "Harbor Portal 检查通过"

                    # 检查 Docker Registry API
                    echo "检查 Harbor Registry API..."

                    registry_status=$(curl --silent --show-error \
                        --connect-timeout 5 \
                        --max-time 10 \
                        --resolve "harbor.local:30080:$HARBOR_IP" \
                        -o /dev/null \
                        -w '%{http_code}' \
                        "$HARBOR_URL/v2/")

                    # 未登录时，401 通常表示 Registry 已响应认证挑战
                    case "$registry_status" in
                        200|401)
                            echo "Registry API 检查通过"
                            echo "HTTP 状态码：$registry_status"
                            ;;
                        *)
                            echo "ERROR：Registry API 检查失败"
                            echo "HTTP 状态码：$registry_status"
                            exit 1
                            ;;
                    esac

                    echo "Harbor 连通性检查通过"
                '''
            }
        }

        // ============================================================
        // 阶段 4：检查项目文件
        // ============================================================
        stage('Validate Files') {
            steps {
                echo '========== 阶段 4：检查项目文件 =========='

                sh '''
                    set -eu

                    # 检查 FastAPI 和 llama.cpp 镜像的构建文件
                    test -f Dockerfile
                    test -f requirements.txt
                    test -f llama/Dockerfile

                    echo "构建文件检查通过"

                    # 确保大型 GGUF 模型没有被提交到 Git
                    MODEL_FILE="llama/models/qwen2-0_5b-instruct-q4_k_m.gguf"

                    if git ls-files --error-unmatch "$MODEL_FILE" \
                        >/dev/null 2>&1; then
                        echo "ERROR：GGUF 模型文件不能提交到 Git"
                        exit 1
                    fi

                    echo "GGUF 模型未被 Git 跟踪"
                '''
            }
        }

        // ============================================================
        // 阶段 5：构建 FastAPI 镜像
        // ============================================================
        stage('Build llm-serving') {
            options {
                timeout(time: 10, unit: 'MINUTES')
            }

            steps {
                echo '========== 阶段 5：构建 llm-serving 镜像 =========='

                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                    IMAGE="$HARBOR/$HARBOR_PROJECT/$APP_IMAGE"

                    echo "目标镜像：$IMAGE:$BUILD_NUMBER"
                    echo "开始时间：$(date)"

                    # 构建 FastAPI 服务镜像
                    docker build --progress=plain --pull \
                        -t "$IMAGE:$BUILD_NUMBER" \
                        -t "$IMAGE:latest" \
                        -f Dockerfile .

                    echo "llm-serving 镜像构建成功"
                    echo "结束时间：$(date)"
                '''
            }
        }

        // ============================================================
        // 阶段 6：构建 llama.cpp + Qwen 镜像
        // ============================================================
        stage('Build llama + Qwen') {
            options {
                // 模型下载可能耗时较长
                timeout(time: 20, unit: 'MINUTES')
            }

            steps {
                echo '========== 阶段 6：构建 llama + Qwen 镜像 =========='

                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                    IMAGE="$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE"

                    echo "目标镜像：$IMAGE:$BUILD_NUMBER"
                    echo "开始时间：$(date)"

                    # 模型文件不提交到 Git，由 llama/Dockerfile 在构建时下载
                    docker build --progress=plain --pull \
                        -t "$IMAGE:$BUILD_NUMBER" \
                        -t "$IMAGE:latest" \
                        -f llama/Dockerfile llama

                    echo "llama + Qwen 镜像构建成功"
                    echo "结束时间：$(date)"
                '''
            }
        }

        // ============================================================
        // 阶段 7：验证本地镜像
        // ============================================================
        stage('Verify Images') {
            steps {
                echo '========== 阶段 7：验证本地镜像 =========='

                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                    # 检查两个镜像的版本标签是否存在
                    docker image inspect \
                        "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER" \
                        >/dev/null

                    docker image inspect \
                        "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER" \
                        >/dev/null

                    echo "两个镜像均已成功生成"
                '''
            }
        }

        // ============================================================
        // 阶段 8：推送镜像到 Harbor
        // ============================================================
        stage('Push to Harbor') {
            options {
                timeout(time: 10, unit: 'MINUTES')
            }

            steps {
                echo '========== 阶段 8：推送镜像到 Harbor =========='

                // 从 Jenkins Credentials 获取 Harbor 账号和密码
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

                        # 推送结束后尝试清理 Docker 登录状态
                        trap 'docker logout "$HARBOR" >/dev/null 2>&1 || true' EXIT

                        echo "登录 Harbor：$HARBOR"

                        # 使用标准输入传递密码，避免将密码写入命令参数
                        printf '%s' "$HARBOR_PASSWORD" |
                            docker login "$HARBOR" \
                                -u "$HARBOR_USER" \
                                --password-stdin

                        # 推送 FastAPI 镜像的版本标签
                        echo "推送 $APP_IMAGE:$BUILD_NUMBER"

                        docker push \
                            "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER"

                        # 推送 FastAPI 镜像的 latest 标签
                        echo "推送 $APP_IMAGE:latest"

                        docker push \
                            "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:latest"

                        # 推送 llama.cpp + Qwen 镜像的版本标签
                        echo "推送 $LLAMA_IMAGE:$BUILD_NUMBER"

                        docker push \
                            "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER"

                        # 推送 llama.cpp + Qwen 镜像的 latest 标签
                        echo "推送 $LLAMA_IMAGE:latest"

                        docker push \
                            "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:latest"

                        echo "所有镜像已推送到 Harbor"
                    '''
                }
            }
        }
    }

    // ================================================================
    // 流水线结束处理
    // ================================================================
    post {
        success {
            echo '''
            ========================================
            CI 成功
            llm-serving 和 llama + Qwen 镜像已推送。
            请在 Harbor 中检查镜像版本。
            ========================================
            '''
        }

        failure {
            echo '''
            ========================================
            CI 失败
            请根据最后一个失败阶段定位问题。
            优先检查 Docker、网络、模型下载和 Harbor 认证。
            ========================================
            '''
        }

        always {
            echo "Pipeline 结束时间：${new Date()}"
            echo "Jenkins Build Number：${env.BUILD_NUMBER}"
            echo "最终构建结果：${currentBuild.currentResult}"
        }
    }
}
