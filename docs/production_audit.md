# StockStream V3.0 生产环境审计报告

> 审计日期: 2026-06-24
> 审计范围: 全量 Python 源码 (src/ + stockstream/)
> 审计维度: 内存泄漏 | CPU异常 | GPU异常 | 死循环 | 阻塞IO | 数据库锁 | WebSocket | TTS阻塞 | 视频阻塞 | 推流中断

---

## 一、总体评分

| 维度 | 评分 | 说明 |
|------|------|------|
| **内存安全** | ⭐⭐⭐⭐ | 大多数模块有容量限制，3个MEDIUM问题待修复 |
| **CPU/事件循环** | ⭐⭐⭐ | 部分同步操作阻塞事件循环，2个HIGH |
| **GPU/推理** | ⭐⭐⭐⭐ | 当前CPU模式安全，需为TensorRT模式做准备 |
| **WebSocket** | ⭐⭐⭐ | 断线重试不足，1个HIGH |
| **TTS稳定性** | ⭐⭐⭐ | 队列反压可能导致阻塞，1个HIGH |
| **视频稳定性** | ⭐⭐ | 同步Popen阻塞 + 双实例冲突，3个HIGH |
| **推流稳定性** | ⭐⭐ | 无端到端看门狗 + 运行时崩溃风险，3个HIGH |
| **数据库安全** | ⭐⭐⭐⭐ | 无死锁风险，缺少WAL模式配置 |

---

## 二、高风险 (HIGH) — 必须立即修复

### H-1: TTS `speak()` 队列满时阻塞事件循环
- **文件**: `stockstream/tts/service.py:133`
- **问题**: `await self._task_queue.put(task)` 在队列满(200条)时会无限等待，高频行情播报下形成反压链
- **影响**: 阻塞整个事件循环，WebSocket/行情更新全部卡死
- **修复**: 使用 `put_nowait()` + 队列满时丢弃最旧任务

### H-2: `LiveCompositor._start_ffmpeg_pipe()` 同步 Popen + 同步 stdin.write
- **文件**: `stockstream/video/compositor.py:334,361`
- **问题**: `subprocess.Popen` 和 `self._process.stdin.write()` 都是同步操作，stdin write 可能阻塞事件循环
- **影响**: FFmpeg 消费慢时，整个异步事件循环被阻塞
- **修复**: 改用 `asyncio.create_subprocess_exec` + `run_in_executor` 写管道

### H-3: 双 FFmpeg 实例冲突
- **文件**: `stockstream/video/compositor.py` + `stockstream/stream/ffmpeg_streamer.py`
- **问题**: 两个独立的 FFmpeg 启动逻辑无互斥，可能同时推流到同一 RTMP URL
- **影响**: RTMP 拒绝连接，推流失败
- **修复**: 统一 FFmpeg 管理到 stream_guard，互斥控制

### H-4: `AntiSilenceAgent._action_history_max` 未定义 → 运行时崩溃
- **文件**: `stockstream/anti_silence_agent/engine.py:151`
- **问题**: 引用 `self._action_history_max` 但 `__init__` 中从未定义
- **影响**: 反静默逻辑触发时 AttributeError 崩溃
- **修复**: 在 `__init__` 中添加 `self._action_history_max = 50`

### H-5: 缺少端到端推流看门狗
- **文件**: 全局
- **问题**: 没有检测 "FFmpeg 进程运行但 RTMP 已断开" 或 "视频帧停止写入"
- **影响**: 画面冻结后无人发现，直播静默中断
- **修复**: 开发 `stream_guard` 模块，定期检查帧率/推流状态

### H-6: `FFmpegStreamer` 重连时 task 引用丢失
- **文件**: `stockstream/stream/ffmpeg_streamer.py:390-440`
- **问题**: `_watch_process_exit()` 重连时覆盖 `_watch_task` 引用，旧 task 丢失追踪
- **影响**: 僵尸 task 累积
- **修复**: 在重连前 cancel 并 await 旧 task

### H-7: WebSocket `send_json` 无重试机制
- **文件**: `stockstream/web/api.py:2520`
- **问题**: `await websocket.send_json(...)` 异常后静默 break
- **影响**: 客户端断连后事件丢失，无日志
- **修复**: 添加重试逻辑 + 错误日志

---

## 三、中风险 (MEDIUM) — 重要性高

### M-1: FanGrowthTracker 无界列表
- **文件**: `stockstream/fan_growth_tracker/engine.py:124-125`
- **问题**: `_new_follows` 和 `_unfollows` 只 append 不清理
- **修复**: 添加定时清理或 deque(maxlen=10000)

### M-2: FanTracker (src版) 无界列表
- **文件**: `src/live/fan_tracker.py:59`
- **问题**: `_data` 只 append 不清理
- **修复**: 添加 maxlen 限制

### M-3: TTS 队列满时丢弃事件
- **文件**: `stockstream/tts/service.py:251-255`
- **问题**: `_play_events` 满时丢弃最旧事件
- **修复**: 添加事件丢失告警

### M-4: DualVoiceTTS 串行合成耗时长
- **文件**: `stockstream/dual_host/dual_voice_tts.py:150-175`
- **问题**: 长脚本合成可能数分钟才返回
- **修复**: 流式返回，边合成边播放

### M-5: 平台重连触发不及时
- **文件**: `stockstream/platform_gateway/common/interface.py:89`
- **问题**: 轮询失败后 `_connected` 未及时置 False
- **修复**: 异常时立即设置 `_connected = False`

### M-6: Douyin WS 声明但未实现
- **文件**: `stockstream/platform_gateway/douyin/connector.py:93`
- **问题**: `self._ws` 声明但从未使用
- **修复**: 标记为 TODO 或移除

### M-7: ONNX Session 无显式释放
- **文件**: `stockstream/avatar/wav2lip_onnx.py:87`, `stockstream/avatar/face_detector.py:60`
- **问题**: 无 `close()` 方法释放 ONNX 资源
- **修复**: 添加 `close()` / `__del__` 方法

### M-8: live_page.py goroutine 重复创建
- **文件**: `stockstream/web/live_page.py`
- **问题**: WebSocket 事件流在每次页面加载时创建新 goroutine
- **修复**: 改为全局单例事件广播器

---

## 四、低风险 (LOW) — 改善项

| # | 文件 | 问题 | 建议 |
|---|------|------|------|
| L-1 | `src/core/config_center.py:202` | 回调无取消注册 API | 添加 `remove_change()` |
| L-2 | `src/core/event_bus.py:146` | 嵌套函数订阅无法取消 | 文档说明 + 提供包装方法 |
| L-3 | `stockstream/platform_gateway/douyin/connector.py:235` | set clear() 全量清空去重 | 使用带 TTL 的 LRU |
| L-4 | `stockstream/danmu_center/engine.py:170` | OrderedDict 清理依赖新消息 | 添加定时清理 |
| L-5 | `stockstream/video/compositor.py:342` | daemon 线程无 join | 保存引用并超时 join |
| L-6 | `stockstream/stream/ffmpeg_streamer.py:308` | stderr readline 无超时 | 添加超时机制 |
| L-7 | `stockstream/video/compositor.py:232` | cap.read() 异常处理不足 | 添加 cv2 异常捕获 |

---

## 五、正面发现 — 已验证安全的模块

| 模块 | 保护机制 |
|------|---------|
| `EventBus` | `_history` max=1000, `_pending_tasks` max=200, 背压控制 |
| `DanmuCenter (src)` | `deque(maxlen=2000)`, set 定期清理 |
| `DualHostService` | `_script_history` 上限 200, task 在 finally pop |
| `ResourceScheduler` | `_state_history` max=300 |
| `FanGrowthTracker._snapshots` | `deque(maxlen=3600)` |
| `TTSService._play_events` | Queue maxsize=256 |
| `TTSEngine._synthesize_python` | `run_in_executor` 正确使用线程池 |
| `TTSEngine.synthesize_stream` | `asyncio.wait_for` 超时保护 |
| `PlatformGateway.events()` | drain tasks 在 finally 中 cancel + await |
| `ContentScheduler` | `stop()` 中 unsubscribe |
| `DirectorAgent` | `stop()` 中 cancel 所有 `_fire_tasks` |

---

## 六、修复优先级

| 优先级 | 数量 | 预计耗时 |
|--------|------|---------|
| **P0: 立即修复 (HIGH)** | 7 | 2h |
| **P1: 尽快修复 (MEDIUM)** | 8 | 1h |
| **P2: 后续改善 (LOW)** | 7 | 0.5h |

---

## 七、修复计划

### 第一阶段修复 (V3.0 P0)
1. ✅ TTS speak() 队列阻塞 → `put_nowait` + 背压
2. ✅ LiveCompositor 同步 Popen → 异步子进程
3. ✅ AntiSilenceAgent 属性缺失 → 添加定义
4. ✅ 端到端流看门狗 → `stream_guard` 模块
5. ✅ FFmpegStreamer 重连 task 管理
6. ✅ WebSocket send_json 重试
7. ✅ 双 FFmpeg 互斥管理 → 统一 stream_guard

### 第二阶段修复 (V3.0 P1)
1. FanGrowthTracker/FanTracker 无界列表
2. TTS 事件丢弃告警
3. DualVoiceTTS 流式返回
4. 平台重连立即触发
5. ONNX Session close()
6. live_page.py 事件广播器优化

---

*本报告由 StockStream V3.0 生产环境审计自动生成。*
