# BabyTap 分享版

本仓库包含三个相邻目录：`babytap`（电脑端）、`babytap-server`（定制后端）和 `babytap-easy-input-maker`（固件）。这是去除历史和本机数据的源码快照，并非一键安装包。

请阅读各目录 README 及 `babytap-server/docs/setup.md`；需自行创建数据库、账号、儿童信息和 API 凭据。启动脚本需要设置 `BABYTAP_BABYBUDDY_CHILD_ID`。不得提交真实数据和密钥。

语音录音会发送至阿里云百炼 DashScope 服务，不是离线识别；使用前确认隐私政策和同意情况。设备音频通信仅适用于可信局域网。后端开发设置可能创建默认账号，请立即更改密码，勿直接暴露公网。

固件含非商业许可及第三方许可，详见固件目录 LICENSE 和 THIRD_PARTY_NOTICES.md；不得假设可商业使用。固件提示音不随仓库提供，编译前需自行添加：文字、文件名和格式见 `babytap-easy-input-maker/features/speaker_assets/assets/babytap/README.md`。

本快照尚未在全新环境完成端到端安装、构建或实机验证。
