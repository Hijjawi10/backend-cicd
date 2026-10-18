pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        timeout(time: 10, unit: 'MINUTES')
    }

    environment {
        DEPLOY_DIR = '/opt/backend-cicd'
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
                sh '.venv/bin/python -m pytest -v'
            }
        }

        stage('Backup Current Release') {
            steps {
                script {
                    env.ROLLBACK_DIR = "${env.WORKSPACE}/rollback-${env.BUILD_NUMBER}"
                }

                sh '''
                    set -eu

                    mkdir -p "$ROLLBACK_DIR"

                    test -f "$DEPLOY_DIR/main.py"
                    test -f "$DEPLOY_DIR/requirements.txt"
                    test -d "$DEPLOY_DIR/.venv"

                    cp -p "$DEPLOY_DIR/main.py" "$ROLLBACK_DIR/"
                    cp -p "$DEPLOY_DIR/requirements.txt" "$ROLLBACK_DIR/"
                    cp -a "$DEPLOY_DIR/.venv" "$ROLLBACK_DIR/.venv"
                '''

                sh '''
                    python3 - <<'PY'
                    import json
                    import os
                    import urllib.request
                    from pathlib import Path

                    with urllib.request.urlopen(
                        "http://127.0.0.1:8001/health",
                        timeout=5,
                    ) as response:
                        health = json.load(response)

                    if health.get("status") != "ok":
                        raise RuntimeError(
                            f"Current release is unhealthy: {health}"
                        )

                    target = Path(os.environ["ROLLBACK_DIR"]) / "health.json"
                    target.write_text(json.dumps(health), encoding="utf-8")

                    print("Previous release backed up:", health)
                    PY
                    '''.stripIndent()
            }
        }

        stage('Deploy') {
            steps {
                script {
                    env.DEPLOY_STARTED = 'true'
                }

                sh '''
                    set -eu

                    cp main.py requirements.txt "$DEPLOY_DIR/"

                    "$DEPLOY_DIR/.venv/bin/python" -m pip install \
                        -r "$DEPLOY_DIR/requirements.txt"

                    sudo -n /usr/bin/systemctl restart backend-cicd.service
                '''
            }
        }

        stage('Health Check') {
            steps {
                retry(5) {
                    sleep(time: 2, unit: 'SECONDS')

                    sh '''
                        python3 - <<'PY'
                        import json
                        import urllib.request
                        from main import health

                        with urllib.request.urlopen(
                            "http://127.0.0.1:8001/health",
                            timeout=5,
                        ) as response:
                            actual = json.load(response)

                        expected = health()

                        if actual != expected:
                            raise RuntimeError(
                                f"Unexpected health response: {actual}; "
                                f"expected: {expected}"
                            )

                        print("Deployment verified:", actual)
                        PY
                        '''.stripIndent()
                }
            }
        }
    }

    post {
        success {
            echo 'Deployment completed successfully.'
        }

        unsuccessful {
            script {
                if (env.DEPLOY_STARTED == 'true') {
                    echo 'Deployment unsuccessful. Starting rollback.'

                    timeout(time: 5, unit: 'MINUTES') {
                        sh '''
                            set -eu

                            test -f "$ROLLBACK_DIR/main.py"
                            test -f "$ROLLBACK_DIR/requirements.txt"
                            test -d "$ROLLBACK_DIR/.venv"

                            # Prepare the environment before restoring it.
                            RESTORE_DIR="$DEPLOY_DIR/.venv-restore-$BUILD_NUMBER"

                            test ! -e "$RESTORE_DIR"
                            cp -a "$ROLLBACK_DIR/.venv" "$RESTORE_DIR"

                            # Restore the previous application files.
                            cp -p "$ROLLBACK_DIR/main.py" "$DEPLOY_DIR/"
                            cp -p "$ROLLBACK_DIR/requirements.txt" "$DEPLOY_DIR/"

                            # Keep the failed environment for investigation.
                            if [ -e "$DEPLOY_DIR/.venv" ]; then
                                mv "$DEPLOY_DIR/.venv" \
                                    "$ROLLBACK_DIR/failed-venv"
                            fi

                            mv "$RESTORE_DIR" "$DEPLOY_DIR/.venv"

                            sudo -n /usr/bin/systemctl restart backend-cicd.service
                        '''

                        retry(5) {
                            sleep(time: 2, unit: 'SECONDS')

                            sh '''
                                python3 - <<'PY'
                                import json
                                import os
                                import urllib.request
                                from pathlib import Path

                                source = (
                                    Path(os.environ["ROLLBACK_DIR"])
                                    / "health.json"
                                )
                                expected = json.loads(
                                    source.read_text(encoding="utf-8")
                                )

                                with urllib.request.urlopen(
                                    "http://127.0.0.1:8001/health",
                                    timeout=5,
                                ) as response:
                                    actual = json.load(response)

                                if actual != expected:
                                    raise RuntimeError(
                                        f"Rollback verification failed: {actual}; "
                                        f"expected: {expected}"
                                    )

                                print("Rollback verified:", actual)
                                PY
                                '''.stripIndent()
                        }
                    }

                    echo 'Previous release restored. Build remains unsuccessful.'
                } else {
                    echo 'Deployment did not start. No rollback required.'
                }
            }
        }
    }
}