# BabyTap

BabyTap 使用 EasyInput 实体按键、麦克风、扬声器和 RGB 灯，为 Baby Buddy 提供无屏育儿记录入口。

当前版本已完成八键业务状态机、SQLite 恢复、BabyTap Server 原子同步／幂等重试／整组撤销、EasyInput 板载麦克风语音、语音转写、板载中文播报、动态灯效、旋钮音量和操作时间线。未配置服务端时记录会明确标为“仅本地”，不会冒充远端成功。

## 模块

- `app/`：Python 本地服务与 Web UI
- `../babytap-server/`：基于固定 Baby Buddy 源码定制的独立后端
- `../babytap-easy-input-maker/`：从官方仓库固定提交克隆的独立 ESP-IDF 固件工程
- `experiments/key-probe/`：早期最小按键探针，仅保留为历史实验，不作为正式固件
- `infra/`：从本仓启动相邻定制后端的 Compose 包装
- `docs/`：产品、架构与跨模块协议
- `flow/`：计划、进展、决策与踩坑记录

## 第一版范围

- 左右母乳任意侧开始、换边和结束
- 奶瓶语音录入奶量
- 辅食语音录入内容
- 换尿布一按即记
- 睡眠开始／结束
- 撤销最近一次 BabyTap 操作
- 状态播报
- 灯光与声音反馈

不包含喂养间隔提醒、手机端和 Wi-Fi 独立运行。旋钮仅用于板载扬声器音量，不承担育儿记录动作。

## 本地运行

```bash
app/.venv/bin/pip install -e 'app[dev]'
scripts/run-local.sh
```

一条 `scripts/run-local.sh` 会启动或复用相邻的 Baby Buddy（`8000`）和 BabyTap（`8765`），完成健康检查后即可打开 <http://127.0.0.1:8765>；按键说明位于 <http://127.0.0.1:8765/device>。第一次按 K3／K4 时，键盘先播报“请说奶量”／“请说辅食内容”，随后采集板载麦克风 PCM；说完再按同一个键会立即停止录音并转写。识别到有效奶量或辅食内容后自动保存；音频丢包、明确低置信度或识别失败时保留弹窗供确认、修改或取消。

`scripts/run-local.sh` 可从相邻本机数据库读取 Token；运行前需设置 `BABYTAP_BABYBUDDY_CHILD_ID`。参照 `app/.env.example` 配置，真实密钥不得写入 Git。服务启动后可访问 `/api/babybuddy/check` 验证连接。

日常启动默认监听 UDP `17333`，由 BabyTap 接收 EasyInput 板载麦克风；官方 EasyInput App 不参与日常语音链路，也不能与 BabyTap 同时占用该端口。语音转写需要在本机私有配置中提供华北 2（北京）的 DashScope API Key。板载扬声器播放固定场景提示，旋钮按 `0% / 20% / 40% / 60% / 80% / 100%` 六档调节，五颗灯显示非静音档位，设置持久化到设备。
