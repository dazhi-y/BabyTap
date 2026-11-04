# BabyTap 固定提示音（需自行添加）

仓库不提供以下音频。编译固件前，请自行录制或用有权使用的语音服务生成对应内容，将音频转换为 **EIAD v1、48 kHz、单声道、分帧 IMA-ADPCM**，以所列文件名放入本目录。缺少文件时固件无法编译。

| 文件名 | 需要朗读的文字 |
| --- | --- |
| `01_timer_started.eiad` | 计时已开始 |
| `02_side_switched.eiad` | 已切换另一侧 |
| `03_bottle_prompt.eiad` | 请说奶瓶奶量 |
| `04_solid_food_prompt.eiad` | 请说辅食内容 |
| `05_diaper_recorded.eiad` | 换尿布已记录 |
| `06_sleep_started.eiad` | 睡眠计时已开始 |
| `07_record_saved.eiad` | 记录成功 |
| `08_cancelled.eiad` | 已取消 |
| `09_undone.eiad` | 已撤销 |
| `10_status_idle.eiad` | 当前没有进行中的记录 |
| `11_status_breastfeeding.eiad` | 正在母乳计时 |
| `12_status_sleep.eiad` | 正在睡眠计时 |
| `13_status_waiting.eiad` | 正在等待语音输入 |
| `14_failed.eiad` | 操作失败 |
| `15_nothing_to_undo.eiad` | 没有可以撤销的记录 |

`scripts/generate_babytap_cues.py` 包含文字、EIAD 编码和 macOS 生成示例。使用前请自行核实所选声音的许可；生成后不要将无权分发的音频上传。该步骤不会由 ESP-IDF 自动运行。
