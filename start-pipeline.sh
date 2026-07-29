#!/usr/bin/env bash
set -euo pipefail

echo "Starting DevSecOps pipeline setup..."

if ! command -v docker &> /dev/null; then
    echo "Docker not found. Please install Docker and try again."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JENKINS_HOST_PORT="${JENKINS_HOST_PORT:-8081}"
JENKINS_IMAGE="${JENKINS_IMAGE:-jenkins/jenkins:lts-jdk21}"
REPO_URL="$(git -C "$SCRIPT_DIR" config --get remote.origin.url 2>/dev/null || true)"
if [ -z "$REPO_URL" ]; then
    echo "Warning: Could not determine git remote URL. Using default."
    REPO_URL="https://github.com/ishallpass/devopspipeline.git"
fi

TMP_DIR="$SCRIPT_DIR/.start-pipeline-tmp"
mkdir -p "$TMP_DIR"
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

docker stop jenkins 2>/dev/null || true
docker rm jenkins 2>/dev/null || true
docker volume create jenkins_home 2>/dev/null || true

cat > "$TMP_DIR/plugins.txt" <<'EOF'
docker-plugin
docker-workflow
git
pipeline-github-lib
blueocean
workflow-job
workflow-cps
EOF

echo "Pre-installing Jenkins plugins..."
docker run --rm \
  -u root \
  -v jenkins_home:/var/jenkins_home \
  -v "$TMP_DIR/plugins.txt":/tmp/plugins.txt \
  "$JENKINS_IMAGE" \
  jenkins-plugin-cli -f /tmp/plugins.txt

mkdir -p "$TMP_DIR/init.groovy.d"
cat > "$TMP_DIR/init.groovy.d/01-create-pipeline-job.groovy" <<EOF
import jenkins.model.Jenkins
import org.jenkinsci.plugins.workflow.job.WorkflowJob
import org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition
import hudson.plugins.git.GitSCM
import hudson.plugins.git.UserRemoteConfig
import hudson.plugins.git.BranchSpec

def jenkins = Jenkins.get()
def jobName = 'DevSecOps-Pipeline'
def repoUrl = System.getenv('REPO_URL') ?: '${REPO_URL}'

if (jenkins.getItem(jobName) == null) {
    def remoteConfig = new UserRemoteConfig(repoUrl, null, null, null)
    def branchSpec = new BranchSpec('*/main')
    def gitSCM = new GitSCM([remoteConfig], [branchSpec], false, [], [])
    def flowDefinition = new CpsScmFlowDefinition(gitSCM, 'Jenkinsfile')
    def job = jenkins.createProject(WorkflowJob.class, jobName)
    job.setDefinition(flowDefinition)
    job.save()
    println "Created pipeline job: \${jobName}"
    job.scheduleBuild2(0)
} else {
    println "Job already exists: \${jobName}"
}
EOF

echo "Starting Jenkins container on http://localhost:${JENKINS_HOST_PORT}..."
docker run -d \
  --name jenkins \
  -p "${JENKINS_HOST_PORT}:8080" \
  -p 50000:50000 \
  -e JAVA_OPTS="-Djenkins.install.runSetupWizard=false" \
  -e REPO_URL="$REPO_URL" \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$SCRIPT_DIR":/workspace \
  -v "$TMP_DIR/init.groovy.d":/var/jenkins_home/init.groovy.d:ro \
  -u root \
  "$JENKINS_IMAGE"

echo "Waiting for Jenkins to become ready..."
until docker logs jenkins 2>&1 | grep -q "Jenkins is fully up and running"; do
    sleep 2
done

echo "Installing Docker CLI inside Jenkins..."
docker exec -u root jenkins apt-get update -qq
docker exec -u root jenkins apt-get install -y docker.io -qq
docker exec -u root jenkins chmod 666 /var/run/docker.sock

echo "Waiting for the pipeline job to appear..."
until docker exec jenkins test -f /var/jenkins_home/jobs/DevSecOps-Pipeline/config.xml >/dev/null 2>&1; do
    sleep 2
done

echo "Setup completed."
echo "Jenkins is running at http://localhost:${JENKINS_HOST_PORT}"
echo "Pipeline job: DevSecOps-Pipeline"
echo "Build console: http://localhost:${JENKINS_HOST_PORT}/job/DevSecOps-Pipeline/lastBuild/console"