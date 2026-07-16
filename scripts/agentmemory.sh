#!/bin/bash
# AgentMemory 启动/停止脚本
# 启动:  ./scripts/agentmemory.sh start
# 停止:  ./scripts/agentmemory.sh stop
# 状态:  ./scripts/agentmemory.sh status

CMD="npx @agentmemory/agentmemory"
PID_FILE="/tmp/agentmemory.pid"
LOG_FILE="/tmp/agentmemory.log"

case "${1:-status}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "AgentMemory 已在运行 (PID: $(cat "$PID_FILE"))"
      exit 0
    fi
    echo "启动 AgentMemory..."
    nohup $CMD > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 3
    if curl -sf http://localhost:3111/agentmemory/health > /dev/null 2>&1; then
      echo "✅ 启动成功 (PID: $(cat "$PID_FILE"))"
    else
      echo "⚠️ 启动中，请稍后检查状态"
    fi
    ;;
  stop)
    if [ ! -f "$PID_FILE" ]; then
      echo "未找到 PID 文件"
      pkill -f "agentmemory" 2>/dev/null && echo "已停止所有 agentmemory 进程" || echo "无运行中的 agentmemory 进程"
      exit 0
    fi
    PID=$(cat "$PID_FILE")
    kill "$PID" 2>/dev/null && echo "已停止 AgentMemory (PID: $PID)" || echo "进程 $PID 不存在"
    rm -f "$PID_FILE"
    ;;
  status)
    if curl -sf http://localhost:3111/agentmemory/health > /dev/null 2>&1; then
      VER=$(curl -s http://localhost:3111/agentmemory/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))")
      echo "✅ AgentMemory 运行中 (v$VER)"
    else
      echo "❌ AgentMemory 未运行"
    fi
    ;;
  *)
    echo "用法: $0 {start|stop|status}"
    exit 1
    ;;
esac