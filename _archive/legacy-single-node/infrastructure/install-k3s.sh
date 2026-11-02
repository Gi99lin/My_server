#!/bin/bash

# Скрипт установки K3s для Element Server Suite
# Предназначен для Ubuntu Server 22.04+

set -e

echo "=== Установка K3s (Lightweight Kubernetes) ==="

# Проверка системных требований
echo "Проверка системы..."
FREE_MEM=$(free -m | awk '/^Mem:/{print $7}')
echo "Доступно RAM: ${FREE_MEM}MB"

if [ "$FREE_MEM" -lt 1024 ]; then
    echo "ВНИМАНИЕ: Мало свободной RAM (< 1GB). Рекомендуется остановить Docker сервисы перед установкой."
    read -p "Продолжить? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Установка K3s с отключением Traefik (используем NPM)
if command -v k3s &> /dev/null; then
    echo "K3s уже установлен, пропускаем скачивание..."
else
    echo "Устанавливаем K3s..."
    curl -fL https://rancher-mirror.rancher.cn/k3s/k3s-install.sh | INSTALL_K3S_MIRROR=cn INSTALL_K3S_EXEC="--disable=traefik" sh -
fi

# Ожидание запуска
echo "Ожидание запуска K3s..."
sleep 10

# Настройка kubeconfig для пользователя без sudo
if [ "$USER" != "root" ]; then
    echo "Настройка прав для пользователя $USER..."
    sudo mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown $USER:$USER ~/.kube/config
    export KUBECONFIG=~/.kube/config
    echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
fi

# Создание alias kubectl
if ! command -v kubectl &> /dev/null; then
    echo "Создание символической ссылки kubectl..."
    sudo ln -s /usr/local/bin/k3s /usr/local/bin/kubectl
fi

# Проверка установки
echo ""
echo "=== Проверка K3s ==="
kubectl version
kubectl get nodes

# Установка Helm
echo ""
echo "=== Установка Helm ==="
if ! command -v helm &> /dev/null; then
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
else
    echo "Helm уже установлен: $(helm version --short)"
fi

# Добавление Element Server Suite репозитория
echo ""
echo "=== Добавление Helm репозитория ESS ==="
# helm repo add ess https://element-hq.github.io/ess-helm 2>/dev/null || true
# helm repo update

echo ""
echo "=== Установка завершена! ==="
echo ""
echo "Проверьте статус:"
echo "  kubectl get nodes"
echo "  kubectl get pods --all-namespaces"
echo ""
echo "Следующие шаги:"
echo "  1. Создайте namespace: kubectl create namespace matrix"
echo "  2. Настройте values.yaml для ESS Helm chart"
echo "  3. Установите ESS: helm install matrix-stack ess/element-server-suite -n matrix"
