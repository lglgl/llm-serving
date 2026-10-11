pipeline {
    agent any

    options {
        // 禁止同一个任务并发执行，避免同时构建和覆盖镜像标签
        disableConcurrentBuilds()

        // 整个 Pipeline 最长运行 30 分钟，防止任务无限等待
        timeout(time: 30, unit: 'MINUTES')
    }

    environment {
        // Harbor 镜像仓库地址，当前使用 HTTP
        HARBOR = 'harbor.local:30080'

        // Harbor 项目名称
        HARBOR_PROJECT = 'library'

        // FastAPI 服务镜像名称
        APP_IMAGE = 'llm-serving'

        // llama.cpp + Qwen 模型服务镜像名称
        LLAMA_IMAGE = 'llm-serving-llama'
    }

    stages {
        stage('Checkout') {
            steps {
                echo '========== 阶段 1：检出 GitHub 代码 =========='

                // 从 Jenkins SCM 配置的 GitHub 仓库检出代码
                checkout scm

                sh '''
                    set -eu
                    echo "当前工作目录：$(pwd)"
                    echo "当前 Git 提交：$(git rev-parse --short HEAD)"
                '''
            }
        }

        stage('Check Environment') {
            steps {
                echo '========== 阶段 2：检查构建环境 =========='

                sh '''
                    set -eu

                    # macOS Homebrew 的常见路径。
                    # Jenkins 服务可能没有继承终端中的 PATH。
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                    echo "操作系统：$(uname -s)"
                    echo "CPU 架构：$(uname -m)"
                    echo "当前用户：$(whoami)"
                    echo "PATH=$PATH"

                    # 检查 Docker CLI 是否存在
                    if ! command -v docker >/dev/null 2>&1; then
                        echo "ERROR: 找不到 Docker CLI"
                        echo "请检查 Docker Desktop 是否安装，以及 Jenkins 节点 PATH 配置"
                        exit 1
                    fi

                    echo "Docker CLI 路径：$(command -v docker)"

                    # 同时检查 Docker Client 和 Server。
                    # 只有两者都正常，才能开始构建镜像。
                    docker version

                    echo "Docker 环境检查通过"
                '''
            }
        }

        stage('Check Harbor') {
            steps {
                echo '========== 阶段 3：检查 Harbor =========='

                sh '''
                    set -eu

                    # 检查 Harbor HTTP 入口是否可访问
                    echo "检查地址：http://$HARBOR"

                    curl -sS \
                      --connect-timeout 5 \
                      --max-time 10 \
                      -o /dev/null \
                      -w 'Harbor HTTP 状态码：%{http_code}\\n' \
                      "http://$HARBOR/"

                    # 检查 Docker Registry API。
                    # 未认证时返回 401 通常是正常的，说明 Registry 可访问。
                    curl -sS \
                      --connect-timeout 5 \
                      --max-time 10 \
                      -o /dev/null \
                      -w 'Registry API 状态码：%{http_code}\\n' \
                      "http://$HARBOR/v2/" || {
                        echo "ERROR: Registry API 访问失败"
                        exit 1
                      }

                    echo "Harbor 连通性检查完成"
                '''
            }
        }

        stage('Validate Files') {
            steps {
                echo '========== 阶段 4：检查项目文件 =========='

                sh '''
                    set -eu

                    # 检查两个镜像的构建文件是否存在
                    test -f Dockerfile
                    test -f requirements.txt
                    test -f llama/Dockerfile

                    echo "项目文件检查通过"

                    # 防止大型 GGUF 模型文件被提交到 Git
                    if git ls-files --error-unmatch \
                      llama/models/qwen2-0_5b-instruct-q4_k_m.gguf \
                      >/dev/null 2>&1; then
                        echo "ERROR: GGUF 模型文件不能提交到 Git"
                        exit 1
                    fi

                    echo "GGUF 模型未被 Git 跟踪"
                '''
            }
        }

        stage('Build llm-serving') {
            options {
                // 单个镜像构建最多等待 10 分钟
                timeout(time: 10, unit: 'MINUTES')
            }

            steps {
                echo '========== 阶段 5：构建 llm-serving 镜像 =========='

                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                    # 使用 Jenkins 构建编号生成不可混淆的版本标签
                    IMAGE="$HARBOR/$HARBOR_PROJECT/$APP_IMAGE"

                    echo "目标镜像：$IMAGE:$BUILD_NUMBER"
                    echo "开始时间：$(date)"

                    # --progress=plain 输出 Docker 每一步的详细日志
                    # --pull 尝试检查并拉取更新的基础镜像
                    docker build --progress=plain --pull \
                      -t "$IMAGE:$BUILD_NUMBER" \
                      -t "$IMAGE:latest" \
                      -f Dockerfile .

                    echo "llm-serving 镜像构建成功"
                    echo "结束时间：$(date)"
                '''
            }
        }

        stage('Build llama + Qwen') {
            options {
                // 模型下载可能较慢，单独给出 20 分钟
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

                    # 使用 llama/Dockerfile 构建模型服务。
                    # 构建日志会显示基础镜像拉取、模型下载等步骤。
                    docker build --progress=plain --pull \
                      -t "$IMAGE:$BUILD_NUMBER" \
                      -t "$IMAGE:latest" \
                      -f llama/Dockerfile llama

                    echo "llama + Qwen 镜像构建成功"
                    echo "结束时间：$(date)"
                '''
            }
        }

        stage('Verify Images') {
            steps {
                echo '========== 阶段 7：验证本地镜像 =========='

                sh '''
                    set -eu
                    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                    # 检查两个版本标签的镜像是否已成功生成
                    docker image inspect \
                      "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER"

                    docker image inspect \
                      "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER"

                    echo "两个镜像均已成功生成"
                '''
            }
        }

        stage('Push to Harbor') {
            options {
                // 推送阶段最多等待 10 分钟
                timeout(time: 10, unit: 'MINUTES')
            }

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

                        # 通过 Jenkins Credentials 获取凭据，不在日志中打印密码
                        echo "登录 Harbor：$HARBOR"

                        printf '%s' "$HARBOR_PASSWORD" |
                          docker login "$HARBOR" \
                            -u "$HARBOR_USER" \
                            --password-stdin

                        # 推送 FastAPI 镜像的版本标签和 latest 标签
                        echo "推送 llm-serving:$BUILD_NUMBER"
                        docker push \
                          "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER"

                        echo "推送 llm-serving:latest"
                        docker push \
                          "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:latest"

                        # 推送 llama + Qwen 镜像的版本标签和 latest 标签
                        echo "推送 llm-serving-llama:$BUILD_NUMBER"
                        docker push \
                          "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER"

                        echo "推送 llm-serving-llama:latest"
                        docker push \
                          "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:latest"

                        # 注销当前 Docker CLI 的 Harbor 登录
                        docker logout "$HARBOR"

                        echo "所有镜像已推送到 Harbor"
                    '''
                }
            }
        }
    }

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
            请根据最后一个成功阶段定位问题。
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