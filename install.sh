#!/bin/bash

# 设置脚本在任何命令出错时立即退出
set -e

# --- 配置 ---
# 您的GitHub仓库地址
GIT_REPO_URL="https://github.com/SIJULY/azure.git"
# 应用安装目录
APP_DIR="/root/azure-web-app"
# systemd服务名称
SERVICE_NAME="azureapp"

# --- 脚本开始 ---
echo "================================================="
echo "  Azure VM Management Panel 一键部署脚本 (Caddy版)  "
echo "================================================="

# 1. 更新系统并安装基础依赖
echo ">>> [1/7] 正在更新系统并安装基础依赖..."
apt-get update
apt-get install -y python3-pip python3-venv git curl debian-keyring debian-archive-keyring apt-transport-https

# 2. 安装 Caddy Web 服务器
echo ">>> [2/7] 正在通过官方源安装 Caddy..."
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# 3. 从GitHub克隆项目代码
echo ">>> [3/7] 正在从GitHub克隆您的项目..."
if [ -d "$APP_DIR" ]; then
    echo "警告：目录 $APP_DIR 已存在，将跳过克隆。"
else
    git clone "$GIT_REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# 4. 设置Python虚拟环境并安装依赖
echo ">>> [4/7] 正在设置Python虚拟环境并安装依赖包..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# 5. 创建 systemd 服务文件，让Gunicorn在后台运行
echo ">>> [5/7] 正在创建 systemd 服务以实现后台运行..."
cat <<EOF > /etc/systemd/system/${SERVICE_NAME}.service
[Unit]
Description=Gunicorn instance for Azure Web App
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5002 --log-level=info app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 6. 配置 Caddy 作为反向代理
echo ">>> [6/7] 正在配置 Caddy..."
# 自动获取服务器的公网IP地址
SERVER_IP=$(curl -s -4 ifconfig.me)
# 写入 Caddy 的主配置文件 Caddyfile
cat <<EOF > /etc/caddy/Caddyfile
# Caddyfile for ${SERVICE_NAME}

http://${SERVER_IP} {
    reverse_proxy 127.0.0.1:5002
}
EOF

# 7. 启动并启用服务
echo ">>> [7/7] 正在启动并设置服务开机自启..."
systemctl daemon-reload
systemctl start "${SERVICE_NAME}"
systemctl enable "${SERVICE_NAME}"
# 重新加载 Caddy 配置使其生效
systemctl reload caddy

# --- 结束语 ---
echo "================================================="
echo "🎉 部署完成！"
echo "您的应用现在应该可以通过以下地址访问："
echo "http://${SERVER_IP}"
echo "================================================="
