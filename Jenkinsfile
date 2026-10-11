pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
    }

    environment {
        HARBOR = 'harbor.local:30080'
        HARBOR_PROJECT = 'library'
        APP_IMAGE = 'llm-serving'
        LLAMA_IMAGE = 'llm-serving-llama'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Validate Files') {
            steps {
                sh '''
                    set -eu

                    test -f Dockerfile
                    test -f requirements.txt
                    test -f llama/Dockerfile

                    if git ls-files --error-unmatch \
                      llama/models/qwen2-0_5b-instruct-q4_k_m.gguf \
                      >/dev/null 2>&1; then
                        echo "ERROR: GGUF model must not be committed"
                        exit 1
                    fi
                '''
            }
        }

        stage('Build Images') {
            steps {
                sh '''
                    set -eu

                    docker build --pull \
                      -t "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER" \
                      -t "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:latest" \
                      -f Dockerfile .

                    docker build --pull \
                      -t "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER" \
                      -t "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:latest" \
                      -f llama/Dockerfile llama
                '''
            }
        }

        stage('Verify Images') {
            steps {
                sh '''
                    set -eu

                    docker image inspect \
                      "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER"

                    docker image inspect \
                      "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER"
                '''
            }
        }

        stage('Push to Harbor') {
            steps {
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

                        printf '%s' "$HARBOR_PASSWORD" |
                          docker login "$HARBOR" \
                            -u "$HARBOR_USER" \
                            --password-stdin

                        docker push \
                          "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:$BUILD_NUMBER"

                        docker push \
                          "$HARBOR/$HARBOR_PROJECT/$APP_IMAGE:latest"

                        docker push \
                          "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:$BUILD_NUMBER"

                        docker push \
                          "$HARBOR/$HARBOR_PROJECT/$LLAMA_IMAGE:latest"

                        docker logout "$HARBOR"
                    '''
                }
            }
        }
    }

    post {
        success {
            echo 'Both images have been pushed to Harbor.'
        }

        failure {
            echo 'CI failed. Check the failed stage and Jenkins console log.'
        }
    }
}