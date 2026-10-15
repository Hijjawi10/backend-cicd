pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        timeout(time: 10, unit: 'MINUTES')
    }

    stages {
        stage('Prepare Python Environment') {
            steps {
                sh '''
                    python3 -m venv .venv
                    .venv/bin/python -m pip install --upgrade pip
                    .venv/bin/python -m pip install -r requirements.txt
                '''
            }
        }

        stage('Run Tests') {
            steps {
                sh '.venv/bin/python -m pytest -v'
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    set -eu
                    cp main.py requirements.txt /opt/backend-cicd/
                    /opt/backend-cicd/.venv/bin/python -m pip install -r /opt/backend-cicd/requirements.txt
                    sudo -n /usr/bin/systemctl restart backend-cicd.service
                '''
            }
        }

        stage('Health Check') {
            steps {
                retry(5) {
                    sleep(time: 2, unit: 'SECONDS')
                    sh '''
                        .venv/bin/python -c 'import json, urllib.request; from main import health; response = urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=5); data = json.load(response); assert data == health(), f"Unexpected health response: {data}"; print("Deployment verified:", data)'
                    '''
                }
            }
        }
    }
}