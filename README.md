# Gitee 资源自动更新插件

本插件会使用`git ls-remotet`定时检查 Amiya-Bot 官方资源仓库的更新。

当检测到有新的 Commit 时，会自动调用 `明日方舟数据解析` 插件的资源下载和数据解析功能。

## 配置
请在 Amiyabot 控制台的插件管理页面进行配置：
- **启用自动更新检查**: 插件的总开关。
- **检查频率（分钟）**: 设置检查更新的时间间隔。
- **目标仓库URL**: 需要监控的Gitee或GitHub仓库地址。支持标准的 .git 格式地址，或 Gitee/GitHub 的 commits 页面URL，插件会自动进行转换。

#### [仓库地址](https://github.com/RoyZ-iwnl/Amiya-bot_royz-gitee-auto-updater)