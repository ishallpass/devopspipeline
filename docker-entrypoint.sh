#!/bin/bash
set -e
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo "1001")
if getent group $DOCKER_GID > /dev/null 2>&1; then
    GROUP_NAME=$(getent group $DOCKER_GID | cut -d: -f1)
else
    GROUP_NAME="docker-host"
    groupadd -g $DOCKER_GID $GROUP_NAME
fi

usermod -aG $DOCKER_GID jenkins

chown -R jenkins:jenkins /var/jenkins_home

exec su -c "/usr/local/bin/jenkins.sh $*" jenkins