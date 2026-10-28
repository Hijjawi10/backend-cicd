pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        timeout(time: 15, unit: 'MINUTES')
    }

    environment {
        CONTAINER_NAME = 'fds-backend-persistent'
        DATA_VOLUME = 'fds-backend-test-data'
        HEALTH_URL = 'http://127.0.0.1:8003/health'
        DEPLOY_STARTED = 'false'
    }

    stages {
        stage('Prepare Python Environment') {
            steps {
                sh '''
                    set -eu

                    python3 -m venv .venv
                    .venv/bin/python -m pip install --upgrade pip
                    .venv/bin/python -m pip install -r requirements.txt
                '''
            }
        }

        stage('Run Tests') {
            steps {
                sh '''
                    set -eu
                    .venv/bin/python -m pytest -v
                '''
            }
        }

        stage('Check Docker') {
            steps {
                script {
                    env.IMAGE_TAG =
                        "fds-backend:jenkins-${env.BUILD_NUMBER}"

                    env.PREVIOUS_CONTAINER =
                        "${env.CONTAINER_NAME}-previous-${env.BUILD_NUMBER}"
                }

                sh '''
                    set -eu

                    docker info > /dev/null
                    test -f Dockerfile
                    test -f .dockerignore

                    docker volume inspect "$DATA_VOLUME" > /dev/null

                    docker inspect "$CONTAINER_NAME" > current-container.json

                    .venv/bin/python -c '
import json
import os

with open("current-container.json") as file:
    container = json.load(file)[0]

if not container["State"]["Running"]:
    raise SystemExit("Current container is not running")

valid_mount = any(
    mount.get("Type") == "volume"
    and mount.get("Name") == os.environ["DATA_VOLUME"]
    and mount.get("Destination") == "/data"
    and mount.get("RW") is True
    for mount in container["Mounts"]
)

if not valid_mount:
    raise SystemExit("Expected writable data volume is not mounted at /data")

if "DATABASE_PATH=/data/products.db" not in container["Config"]["Env"]:
    raise SystemExit("Current container has an unexpected database path")

print("Docker configuration verified")
'

                    if docker container inspect \
                        "$PREVIOUS_CONTAINER" > /dev/null 2>&1; then
                        echo "Backup container name already exists"
                        exit 1
                    fi
                '''
            }
        }

        stage('Build Docker Image') {
            steps {
                sh '''
                    set -eu

                    docker build -t "$IMAGE_TAG" .

                    docker run --rm \
                        --entrypoint python \
                        "$IMAGE_TAG" \
                        -c 'import json; from main import health; print(json.dumps(health()))' \
                        > expected-health.json
                '''
            }
        }

        stage('Check Current Release') {
            steps {
                sh '''
                    set -eu

                    curl --fail --silent --show-error \
                        --connect-timeout 5 \
                        --max-time 10 \
                        "$HEALTH_URL" \
                        --output previous-health.json

                    .venv/bin/python -c '
import json

with open("previous-health.json") as file:
    data = json.load(file)

if data.get("status") != "ok":
    raise SystemExit(f"Current release is unhealthy: {data}")

print("Previous release:", data)
'
                '''
            }
        }

        stage('Deploy Docker Container') {
            steps {
                script {
                    env.DEPLOY_STARTED = 'true'
                }

                sh '''
                    set -eu

                    docker stop --time 30 "$CONTAINER_NAME"

                    docker rename \
                        "$CONTAINER_NAME" \
                        "$PREVIOUS_CONTAINER"

                    docker run -d \
                        --name "$CONTAINER_NAME" \
                        --restart unless-stopped \
                        -p 8003:8000 \
                        -e DATABASE_PATH=/data/products.db \
                        --mount "type=volume,src=$DATA_VOLUME,dst=/data" \
                        "$IMAGE_TAG"
                '''
            }
        }

        stage('Health Check') {
            steps {
                retry(5) {
                    sleep(time: 3, unit: 'SECONDS')

                    sh '''
                        set -eu

                        curl --fail --silent --show-error \
                            --connect-timeout 5 \
                            --max-time 10 \
                            "$HEALTH_URL" \
                            --output actual-health.json

                        .venv/bin/python -c '
import json

with open("expected-health.json") as file:
    expected = json.load(file)

with open("actual-health.json") as file:
    actual = json.load(file)

if actual != expected:
    raise SystemExit(
        f"Unexpected response: {actual}; expected: {expected}"
    )

print("Docker deployment verified:", actual)
'
                    '''
                }
            }
        }
    }

    post {
        success {
            echo 'Docker deployment completed successfully on port 8003.'
            echo "Previous container retained: ${env.PREVIOUS_CONTAINER}"
        }

        unsuccessful {
            script {
                if (env.DEPLOY_STARTED == 'true') {
                    echo 'Deployment unsuccessful. Restoring previous container.'

                    timeout(time: 5, unit: 'MINUTES') {
                        sh '''
                            set -eu

                            if docker container inspect \
                                "$PREVIOUS_CONTAINER" > /dev/null 2>&1; then

                                if docker container inspect \
                                    "$CONTAINER_NAME" > /dev/null 2>&1; then

                                    docker logs "$CONTAINER_NAME" \
                                        > failed-container.log 2>&1 || true

                                    docker rm -f "$CONTAINER_NAME"
                                fi

                                docker rename \
                                    "$PREVIOUS_CONTAINER" \
                                    "$CONTAINER_NAME"
                            fi

                            docker start "$CONTAINER_NAME"
                        '''

                        retry(5) {
                            sleep(time: 3, unit: 'SECONDS')

                            sh '''
                                set -eu

                                curl --fail --silent --show-error \
                                    --connect-timeout 5 \
                                    --max-time 10 \
                                    "$HEALTH_URL" \
                                    --output rollback-health.json

                                .venv/bin/python -c '
import json

with open("previous-health.json") as file:
    expected = json.load(file)

with open("rollback-health.json") as file:
    actual = json.load(file)

if actual != expected:
    raise SystemExit(
        f"Rollback verification failed: {actual}; expected: {expected}"
    )

print("Rollback verified:", actual)
'
                            '''
                        }
                    }

                    echo 'Previous container restored. Build remains unsuccessful.'
                } else {
                    echo 'Deployment did not start.'
                }
            }
        }

        always {
            archiveArtifacts(
                artifacts: '*health.json,current-container.json,failed-container.log',
                allowEmptyArchive: true
            )
        }
    }
}