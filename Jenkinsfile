pipeline {
    agent any

    environment {
        APP_REPO = 'https://github.com/ishallpass/juice-shop.git'
        APP_DIR = 'juice-shop'
        APP_PORT = '3000'
        IMAGE_NAME = 'vulnerable-app'
        IMAGE_TAG = "${env.BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                echo 'Cloning pipeline repository...'
                checkout scm

                echo 'Cloning vulnerable application...'
                sh '''
                    if [ -d "${APP_DIR}" ]; then
                        cd ${APP_DIR} && git pull
                    else
                        git clone ${APP_REPO} ${APP_DIR}
                    fi
                '''
            }
        }

        stage('Setup Environment') {
            steps {
                echo 'Setting up environment...'
                // Config and target files are consumed directly from their
                // repo locations (configs/, targets/, .git-hooks/), so we only
                // need a writable reports directory here.
                sh '''
                    mkdir -p reports
                    chmod 777 reports
                '''
            }
        }

        stage('Static Analysis') {
            parallel {
                stage('Secret Scanning') {
                    steps {                        
                        echo '=================================='
                        echo 'Running Gitleaks...'
                        echo '=================================='
                        script {
                            try {
                                sh """
                                    docker run --rm \\
                                        -v ${env.WORKSPACE}:/workspace \\
                                        zricethezav/gitleaks:latest \\
                                        detect --source="/workspace/${APP_DIR}" \\
                                               --report-path="/workspace/reports/gitleaks.json" \\
                                                --no-git \\
                                               --verbose
                                """
                            } catch (Exception e) {
                                echo 'Gitleaks scan failed.'
                                currentBuild.result = 'UNSTABLE'
                            }
                        }
                    }
                }

                stage('SAST with Semgrep') {
                    steps {
                        echo '=================================='
                        echo 'Running Semgrep (JS/TS rule packs + custom rules)...'
                        echo '=================================='
                        script {
                            try {
                                // Registry packs give broad JavaScript/Node/OWASP
                                // coverage; the local config adds our custom
                                // JS-focused rules for the injected vulnerabilities.
                                sh """
                                    docker run --rm \\
                                        -v ${env.WORKSPACE}:/workspace \\
                                        semgrep/semgrep:latest \\
                                        semgrep --config "p/javascript" \\
                                                --config "p/nodejs" \\
                                                --config "p/owasp-top-ten" \\
                                                --config "/workspace/configs/semgrep.yml" \\
                                                /workspace/${APP_DIR} --json \\
                                        > reports/semgrep.json
                                """
                            } catch (Exception e) {
                                echo 'Semgrep scan failed.'
                                currentBuild.result = 'UNSTABLE'
                            }
                        }
                    }
                }

                stage('Dependency Scanning') {
                    steps {
                        echo '=================================='
                        echo 'Running Trivy (filesystem)...'
                        echo '=================================='
                        script {
                            try {
                                sh """
                                    docker run --rm \\
                                        -v ${env.WORKSPACE}:/workspace \\
                                        aquasec/trivy:latest \\
                                        fs /workspace/${APP_DIR} --format json --timeout 10m \\
                                        > reports/trivy-fs.json
                                """
                            } catch (Exception e) {
                                echo 'Trivy filesystem scan failed.'
                                currentBuild.result = 'UNSTABLE'
                            }
                        }
                    }
                }

                stage('Node SAST with njsscan') {
                    steps {
                        echo '=================================='
                        echo 'Running njsscan (Node.js SAST)...'
                        echo '=================================='
                        script {
                            try {
                                // njsscan is Node/JS specific, replacing Bandit
                                // (Python-only) which produced no findings on
                                // the Juice Shop (TypeScript/Node) codebase.
                                sh """
                                    docker run --rm \\
                                        -v ${env.WORKSPACE}:/workspace \\
                                        python:3.11-slim \\
                                        bash -c "
                                            pip install --quiet njsscan
                                            njsscan --json \\
                                                    -o /workspace/reports/njsscan.json \\
                                                    /workspace/${APP_DIR}
                                        "
                                """
                            } catch (Exception e) {
                                echo 'njsscan scan failed.'
                                currentBuild.result = 'UNSTABLE'
                            }
                        }
                    }
                }
            }
        }

        stage('Build & Deploy') {
            steps {
                echo '=================================='
                echo 'Building Docker image...'
                echo '=================================='
                sh """
                    cd ${APP_DIR}
                    docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
                    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
                """
                echo '=================================='
                echo 'Starting application container...'
                echo '=================================='
                sh """
                    docker stop ${IMAGE_NAME} || true
                    docker rm ${IMAGE_NAME} || true
                    docker run -d --name ${IMAGE_NAME} -p ${APP_PORT}:${APP_PORT} ${IMAGE_NAME}:${IMAGE_TAG}
                """

                echo '=================================='
                echo 'Waiting up to 5 minutes for app to start...'
                echo '=================================='
                sh '''
                    TIMEOUT=600
                    INTERVAL=30
                    ELAPSED=0
                    while [ $ELAPSED -lt $TIMEOUT ]; do
                        if curl -s http://host.docker.internal:3000 > /dev/null 2>&1; then
                            echo "App ready after ${ELAPSED}s"
                            break
                        fi
                        echo "   Attempt $((ELAPSED/INTERVAL + 1)) - waiting ${INTERVAL}s..."
                        sleep $INTERVAL
                        ELAPSED=$((ELAPSED + INTERVAL))
                    done
                    if [ $ELAPSED -ge $TIMEOUT ]; then
                        echo "Timeout reached: App not responding within 5 minutes."
                    fi
                '''
            }
        }

        stage('Dynamic Analysis') {
            parallel {
                stage('Container Scan') {
                    steps {
                        echo 'Scanning container with Trivy...'
                        script {
                            try {
                                sh """
                                    docker run --rm \\
                                        -v /var/run/docker.sock:/var/run/docker.sock \\
                                        -v ${env.WORKSPACE}:/workspace \\
                                        aquasec/trivy:latest \\
                                        image ${IMAGE_NAME}:${IMAGE_TAG} --format json --timeout 10m \\
                                        > reports/trivy-container.json
                                """
                            } catch (Exception e) {
                                echo 'Container scan failed.'
                                currentBuild.result = 'UNSTABLE'
                            }
                        }
                    }
                }

                stage('DAST with ZAP') {
                    steps {
                        echo '=================================='
                        echo 'Running OWASP ZAP baseline scan...'
                        echo '=================================='
                        script {
                            try {
                                // zaproxy/zap-stable is the current official image
                                // (owasp/zap2docker-* is deprecated/unmaintained).
                                sh """
                                    if docker pull zaproxy/zap-stable > /dev/null 2>&1; then
                                        docker run --rm \\
                                            -v \$(pwd)/reports:/zap/wrk:rw \\
                                            --user root \\
                                            zaproxy/zap-stable \\
                                            zap-baseline.py \\
                                            -t http://host.docker.internal:${APP_PORT} \\
                                            -r zap-report.html \\
                                            -J zap-report.json
                                    else
                                        echo 'ZAP image not available – skipping scan.'
                                        echo 'ZAP scan skipped due to image pull failure.' > reports/zap-report.txt
                                    fi
                                """
                            } catch (Exception e) {
                                echo 'ZAP scan failed.'
                                currentBuild.result = 'UNSTABLE'
                            }
                        }
                    }
                }

                stage('Port Scanning') {
                    steps {
                        echo '=================================='
                        echo 'Scanning open ports with nmap...'
                        echo '=================================='
                        sh """
                            docker run --rm \\
                                --network host \\
                                -v ${env.WORKSPACE}:/workspace \\
                                instrumentisto/nmap \\
                                -p ${APP_PORT} localhost \\
                                -oN /workspace/reports/nmap.txt
                        """
                    }
                }

                stage('Endpoint Security Testing') {
                    steps {
                        echo '=================================='
                        echo 'Testing endpoints...'
                        echo '=================================='
                        sh """
                            echo "# API Endpoint Test" > reports/endpoint-test.txt
                            echo "Generated: \$(date)" >> reports/endpoint-test.txt
                            if [ -f targets/endpoints.txt ]; then
                                while IFS= read -r endpoint; do
                                    case "\$endpoint" in
                                        ""|"#"*) continue ;;
                                    esac
                                    # Replace localhost with host.docker.internal
                                    endpoint=\$(echo "\$endpoint" | sed 's/localhost/host.docker.internal/g')
                                    echo "Testing: \$endpoint" >> reports/endpoint-test.txt
                                    curl -s -o /dev/null -w "Status: %{http_code}\\n" "\$endpoint" >> reports/endpoint-test.txt 2>&1 || echo "Connection failed" >> reports/endpoint-test.txt
                                    curl -s -I "\$endpoint" >> reports/endpoint-test.txt 2>&1 || true
                                    echo "" >> reports/endpoint-test.txt
                                done < targets/endpoints.txt
                            else
                                echo "targets/endpoints.txt not found!" >> reports/endpoint-test.txt
                            fi
                        """
                    }
                }
            }
        }
    }

    post {
        always {
            echo 'Generating consolidated report...'
            // Run the aggregator inside a container so the agent needs no local
            // Python; it parses reports/*.json|txt into reports/final_report.md.
            sh """
                docker run --rm \\
                    --volumes-from \$HOSTNAME \\
                    -w ${env.WORKSPACE} \\
                    python:3.11-slim \\
                    sh -c "ls -la scripts/generate-report.py && python3 scripts/generate-report.py"
            """
            archiveArtifacts artifacts: 'reports/*', allowEmptyArchive: true
            sh '''
                docker stop ${IMAGE_NAME} || true
                docker rm ${IMAGE_NAME} || true
                docker image rm ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest || true
            '''
            echo 'Pipeline finished.'
        }
        failure {
            echo 'Pipeline failed – check logs.'
        }
        unstable {
            echo 'Pipeline completed with warnings.'
        }
    }
}