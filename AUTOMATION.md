# Hyperliquid Daily Report Automation

## 已设置的自动化任务

每天中午 12:00 自动运行 `plot_macro_trend.py` 并生成 markdown 报告。

> ⏰ 运行时间从 9:30 调整为 12:00（北京时间）。原因：报告读取 DefiLlama 上「昨天」的协议收入，但 9:30（= UTC 01:30）时昨天的 UTC 日才刚结束约 90 分钟，DefiLlama 尚未结算完成，会读到不完整的偏小数值（例如 06-15 读到 $43,518，结算后实为约 $1.997M）。12:00（= UTC 04:00）有约 4 小时缓冲，确保昨天数据已结算。

## 文件说明

1. **run_daily_report.sh** - 执行脚本
   - 激活虚拟环境
   - 运行 plot_macro_trend.py
   - 解析输出数据
   - 生成 markdown 报告到 `logs/YYYY-MM-DD.md`

2. **com.hyperliquid.dailyreport.plist** - launchd 配置文件
   - 位置: `~/Library/LaunchAgents/`
   - 每天 12:00 自动触发
   - 日志输出到 `logs/launchd.out.log` 和 `logs/launchd.err.log`

## 时区说明

⚠️ **重要**: 当前设置为本地时间 12:00

- 如果你需要北京时间 12:00，请根据你的时区调整 plist 文件中的时间
- 北京时间 = UTC+8
- 例如：如果你在美国西海岸（PST = UTC-8），北京时间 9:30 = PST 前一天 17:30

## 管理命令

```bash
# 查看任务状态
launchctl list | grep hyperliquid

# 停止任务
launchctl unload ~/Library/LaunchAgents/com.hyperliquid.dailyreport.plist

# 启动任务
launchctl load ~/Library/LaunchAgents/com.hyperliquid.dailyreport.plist

# 手动运行测试
cd /Users/elaineye/agent/hyperliquid_stats
./run_daily_report.sh

# 查看日志
tail -f logs/launchd.out.log
tail -f logs/launchd.err.log
```

## 修改运行时间

编辑 plist 文件中的时间：

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>12</integer>  <!-- 修改这里 -->
    <key>Minute</key>
    <integer>0</integer>  <!-- 修改这里 -->
</dict>
```

修改后重新加载：
```bash
launchctl unload ~/Library/LaunchAgents/com.hyperliquid.dailyreport.plist
launchctl load ~/Library/LaunchAgents/com.hyperliquid.dailyreport.plist
```

## 输出文件

- **报告**: `logs/YYYY-MM-DD.md`
- **图表**: `hyperliquid_6m_macro_trend.png` (每次覆盖)
- **日志**: `logs/launchd.out.log` 和 `logs/launchd.err.log`
