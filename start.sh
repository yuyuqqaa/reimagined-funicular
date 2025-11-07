#!/bin/bash
set -e

# 获取当前脚本所在目录
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$BASE_DIR/logs"
PID_DIR="$BASE_DIR/pids"

echo "=== 启动应用服务 ==="
echo "工作目录: $BASE_DIR"
echo "日志目录: $LOG_DIR"
echo "PID目录: $PID_DIR"

# 创建必要的目录
mkdir -p $LOG_DIR $PID_DIR

# 清理旧的PID文件（如果存在）
rm -f $PID_DIR/*.pid

# 启动 Gunicorn
echo "启动 Gunicorn Web服务..."
cd $BASE_DIR
nohup gunicorn -w 4 -b 0.0.0.0:5000 \
  --access-logfile $LOG_DIR/gunicorn_access.log \
  --error-logfile $LOG_DIR/gunicorn_error.log \
  --log-level info \
  --preload \
  --max-requests 1000 \
  --timeout 120 \
  app:app > $LOG_DIR/gunicorn_stdout.log 2>&1 &

GUNICORN_PID=$!
echo $GUNICORN_PID > $PID_DIR/gunicorn.pid
echo "✓ Gunicorn 启动成功 (PID: $GUNICORN_PID)"

# 等待Web服务启动
echo "等待Web服务启动..."
sleep 5

# 检查Gunicorn是否正常启动
if ! kill -0 $GUNICORN_PID 2>/dev/null; then
    echo "✗ Gunicorn 启动失败，请检查日志: $LOG_DIR/gunicorn_error.log"
    tail -20 $LOG_DIR/gunicorn_error.log
    exit 1
fi

# 启动 Frpc
echo "启动 Frpc 内网穿透..."
cd $BASE_DIR
nohup ./frpc -c frpc.ini > $LOG_DIR/frpc.log 2>&1 &

FRPC_PID=$!
echo $FRPC_PID > $PID_DIR/frpc.pid
echo "✓ Frpc 启动成功 (PID: $FRPC_PID)"

# 等待Frpc启动
sleep 2

# 检查Frpc是否正常启动
if ! kill -0 $FRPC_PID 2>/dev/null; then
    echo "✗ Frpc 启动失败，请检查日志: $LOG_DIR/frpc.log"
    tail -20 $LOG_DIR/frpc.log
    exit 1
fi

# 创建启动信息文件
cat > $BASE_DIR/startup.info << EOF
启动时间: $(date)
工作目录: $BASE_DIR
Gunicorn PID: $GUNICORN_PID
Frpc PID: $FRPC_PID
日志文件: $LOG_DIR/
EOF

echo ""
echo "=== 所有服务启动完成 ==="
echo "✓ Gunicorn Web服务: PID $GUNICORN_PID"
echo "✓ Frpc 内网穿透: PID $FRPC_PID"
echo "📊 查看日志: tail -f $LOG_DIR/gunicorn_access.log"
echo "🛑 停止服务: ./stop_app.sh"
echo "📈 检查状态: ./status_app.sh"
