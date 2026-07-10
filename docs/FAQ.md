# StockStream V4.0 — FAQ

---

## 部署相关

**Q: 如何选择部署版本？**
A: 开发用 dev-desktop, 客户演示用 demo, 生产直播桌面 GPU 用 production-desktop, Jetson 边缘设备用 production-jetson。

**Q: Demo 版和 Production 版代码一样吗？**
A: 完全一样。通过 `STOCKSTREAM_PLATFORM=demo|desktop|jetson` 环境变量 + 平台适配器动态切换。

**Q: Jetson 必须用 Python 3.8 吗？**
A: 是。Jetson Xavier NX + JetPack 5.x 系统原生 Python 3.8。项目已做完整兼容性审计和修复。

**Q: 模型文件在哪里下载？**
A: 运行 `python -m src.tools.download_models`，或从内部模型仓库下载。

---

## 性能相关

**Q: Jetson 上内存不够怎么办？**
A: 
1. 确认 `jetson.yaml` 中 `max_ram_mb: 6144`
2. 启用 FP16 + TensorRT
3. 关闭非必要模块 (互动/新闻等)
4. `sudo jetson_clocks` 安定时钟

**Q: GPU 推理延迟高？**
A:
1. 确认 TensorRT 引擎已缓存 (`models/*.engine`)
2. 检查 `onnx_providers` 顺序: `Tensorrt → CUDA → CPU`
3. 启用 FP16 模式

**Q: 30 天连续运行会内存泄漏吗？**
A: 已内置防护：每个推理周期 `gc.collect()`，ONNX session 24h 重建，WebSocket 连接池上限。

---

## 故障排查

**Q: 启动后立即退出？**
A: 检查 `logs/app.log` 最后 50 行，常见原因：
- 模型文件缺失
- 端口 8080 被占用
- `.env` 未配置 API_TOKEN

**Q: 字幕显示乱码？**
A: 确认字体文件存在: `assets/fonts/NotoSansSC-Regular.otf`，或安装系统中文字体。

**Q: WebSocket 频繁断开？**
A: 
1. 检查网络延迟
2. 确认心跳间隔 <30s
3. 查看 `src/core/stream_guard.py` 日志

**Q: ONNX 加载失败 "unknown provider"？**
A: Jetson 需安装 `onnxruntime-gpu==1.16.3`，Desktop 需 `onnxruntime-gpu>=1.17`。

---

## 安全相关

**Q: 如何生成 API Token？**
A: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

**Q: 日志会泄露敏感信息吗？**
A: 已内置脱敏：API Key 显示前4位、手机号脱敏、IP 脱敏。

**Q: 如何限制管理接口访问？**
A: `.env` 中设置 `ADMIN_IPS=127.0.0.1,192.168.1.0/24`

---

## 升级相关

**Q: 如何从小版本升级？**
A: `git pull && pip install -r requirements/common.txt --upgrade && sudo systemctl restart ai-live`

**Q: 升级后模型需要重下载吗？**
A: 一般不需要。如 release notes 注明模型变更，运行 `python -m src.tools.download_models --update`。

**Q: 如何回滚？**
A: 
```bash
git checkout v3.0.0
pip install -r requirements/common.txt
sudo systemctl restart ai-live
```
数据库 schema 向后兼容，无需回滚。

---

## 开发相关

**Q: 如何添加新平台支持？**
A: 继承 `src/platform/base.py` 的 `PlatformAdapter`，实现抽象方法，注册到 `__init__.py`。

**Q: 如何添加新的行情源？**
A: 实现 `src/market/` 下新 Provider，注册到 `MarketRouter`。

**Q: 代码必须 Python 3.8 兼容吗？**
A: Jetson 平台的代码路径必须 3.8 兼容。Desktop/Demo 平台可用 3.10+ 新语法。平台适配器负责隔离差异。
