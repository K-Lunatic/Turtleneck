# Turtleneck ·  터틀넥

<p align="center">
  <img src="assets/turtleneck.png" width="180" alt="Turtleneck 吉祥物">
</p>

<p align="center">
  <strong>收集课程资料，分段学习，像考试一样练习。</strong><br>
  面向 Codex、Claude Code 和 Gemini 的本地优先大学学习技能。
</p>

<p align="center">
  <a href="README.md">한국어</a> ·
  <a href="README.en.md">English</a> ·
  简体中文
</p>

## 功能

Turtleneck 会在运行它的电脑上整理作业、通知、课程视频、课程文件、课表和学习记录。它会把可读取的资料拆成小段交给当前 AI，并打开本地网页试卷，而不是把聊天窗口当作考试页面。

- 同步 KKU TLS 的课程、活动、通知、作业、讲座和可下载文件。
- 连接 Everytime，读取课表、课程评价、论坛和考场信息。
- 根据课程文件制作学习资料和题目候选。
- 打开本地考试页面，保存答题记录，评分并复习薄弱部分。
- 密码只保存到 macOS Keychain 或 Windows 受保护存储中；密码、Cookie 和原始课程文件不会放入仓库。

## 快速开始

要求：macOS 或 Windows 上的本地 Codex、Claude Code 或 Gemini 环境；源码安装需要 Python 3.10 或更高版本。没有 Python 的电脑可以从 GitHub Releases 下载带签名的 `turtleneck-macos-arm64` 或 `turtleneck-windows-x64` 免安装包；启动器不会把远程安装脚本直接通过管道交给 Shell 执行。

使用免安装包时，解压后运行 macOS 的 `turtleneck` 或 Windows 的 `turtleneck.exe`。插件仍按 Codex、Claude Code 等宿主的正常安装命令注册；免安装包只提供本地运行器和 Python 运行时。请参阅[发布策略](RELEASE.md)和[变更记录](CHANGELOG.md)。

### Codex

```bash
codex plugin marketplace add K-Lunatic/Turtleneck --ref turtleneck
codex plugin add university-agent@turtleneck
```

新建 Codex 对话后调用：

```text
$turtleneck
```

首次使用不需要再输入 setup 命令，也不需要手动复制技能文件夹。Turtleneck 会先读取本机状态，只有缺少某项连接时才打开一次性的本地连接表单；已有的学校和 Everytime 缓存会继续复用。

### Claude Code

```bash
claude plugin marketplace add K-Lunatic/Turtleneck
claude plugin install university-agent@turtleneck
```

在新的 Claude Code 对话中调用 `/university-agent:turtleneck`。

### Gemini

连接此仓库，或将 `skills/university-agent` 注册为 `turtleneck` 技能。关于本地沙箱和网络权限，请参阅 [Gemini 执行指南](skills/university-agent/references/gemini.md)。

首次使用时会打开本地连接表单。TLS 和 Everytime 的账号信息只应在官方浏览器登录流程中输入，不要通过聊天发送密码。

## 本地优先与隐私

本项目面向 macOS 和 Windows 桌面本地使用，不提供设备之间的自动同步。可选的 ChatGPT Actions 网关只是单台电脑的辅助功能，不是面向全校的公共服务。账号密码、会话 Cookie、OAuth 密钥、个人课程 ID、原始文件、数据库和学习包不会提交到仓库。请仅使用自己有权访问的账号和资料，并遵守学校及 Everytime 的使用政策。

安全问题请按照 [SECURITY.md](SECURITY.md) 进行私下报告，不要发布到公开 Issue。

## XERJ Corpus Hub

Turtleneck 已被收录为 [XERJ Corpus Hub](https://hub.xerj.org/contributors/K-Lunatic) 的公开语料库。被选中的参考版本是 [`49615b7`](https://github.com/K-Lunatic/Turtleneck/commit/49615b7700f66ccfeef1546c181845528943eacf)，提交说明为 `feat: add lecture media and activity support`，遵循本仓库的 MIT 许可证。

## 其他 Coursemos/Moodle 学校

对于标准 Moodle 站点，Turtleneck 会先从 `/my/` 或 `/course/index.php` 读取当前账号的课程，再读取可见的主题和 `/mod/.../view.php?id=...` 活动。未知活动类型也会保留在本地目录中。SSO、视频播放器、下载、提交状态、自主课程管理和写入操作因学校而异，只在确认过的学校配置中启用；不会在其他学校猜测 KKU 专用的 `/local/ubion`、`/local/ubeclass` 或 `/local/ubdoc` 路径。

## 文档

- [技能说明](skills/university-agent/SKILL.md)
- [学习、考试与评分契约](skills/university-agent/references/study.md)
- [通用数据模型](skills/university-agent/references/data-model.md)
- [TLS 提供者契约](skills/university-agent/references/provider-contract.md)
- [Claude Code 指南](skills/university-agent/references/claude-code.md)

## 许可证

MIT，详见 [LICENSE](LICENSE)。
