# Turtleneck

<p align="center">
  <img src="assets/turtleneck.png" width="180" alt="Turtleneck mascot">
</p>

<p align="center">
  <strong>Collect course materials, study in focused pieces, and practice like an exam.</strong><br>
  A local-first university study skill for Codex, Claude Code, and Gemini.
</p>

<p align="center"><small>Search: Turtleneck AI Skill · 터틀넥 스킬 · Codex Skill · Claude Code Skill · Gemini Skill · Moodle study assistant</small></p>

<p align="center">
  <a href="README.md">한국어</a> ·
  English ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

## Support the developer

If Turtleneck helped you, you can [support the developer on GitHub Sponsors](https://github.com/sponsors/K-Lunatic).
Choose a tier that feels right—physical therapy, coffee, or beer are all appreciated. Support is optional and does not unlock or restrict features.

## What it does

Turtleneck organizes assignments, announcements, lectures, course files, schedules, and study records on the computer where it runs. It extracts readable material in small pieces for the current AI host and opens a local web exam instead of turning the chat into an exam screen.

- Sync KKU TLS courses, activities, announcements, assignments, lectures, and downloadable files.
- Connect Everytime for timetable, course reviews, boards, and classroom information.
- Build study material and question candidates from course files.
- Open local exams, save attempts, grade answers, and review weak areas.
- Keep passwords in macOS Keychain or Windows protected storage; do not put passwords, cookies, or original course files in the repository.

## Quick start

Search GitHub for `Turtleneck AI Skill` or `터틀넥 스킬`. The same package is exposed through the
Codex and Claude Code marketplace files and the Gemini skill path. Detect the local environment first;
add `--apply` only after reviewing the official commands:

```bash
python3 skills/university-agent/scripts/install_turtleneck.py
python3 skills/university-agent/scripts/install_turtleneck.py --apply
```

After a successful explicit installation, Turtleneck may show one non-blocking request to star the repository. Starring is optional and never changes access or support.

Requirements: a local Codex, Claude Code, or Gemini environment on macOS or Windows, plus Python 3.10 or newer for source installs. On a Python-free desktop, use the unsigned `turtleneck-macos-x64-unsigned` or `turtleneck-windows-x64-unsigned` no-install bundle from GitHub Releases. Verify its checksum before running; the operating system may show a security warning.

To use a no-install bundle, extract it and run `turtleneck` on macOS or `turtleneck.exe` on Windows. Register the plugin with the host's normal install command; the bundle supplies the local runner and Python runtime. See the [release policy](RELEASE.md) and [change log](CHANGELOG.md).

### Why a security warning appears

Public bundles are currently **unsigned** because they are not packaged with an Apple Developer certificate or a Windows code-signing certificate. macOS Gatekeeper may report an unverified developer, and Windows SmartScreen may block the first launch. This is not a missing-Python error; it means the operating system cannot verify the publisher signature.

Before opening the bundle, confirm that it came from the official GitHub Release and that its `.sha256` checksum matches the published checksum. Stop if the checksum differs or the source is unclear. An unsigned bundle is not automatically safe.

### Codex

```bash
codex plugin marketplace add K-Lunatic/Turtleneck --ref turtleneck
codex plugin add university-agent@turtleneck
```

Start a new Codex chat and call:

```text
$turtleneck
```

There is no second setup command or manual folder copy on first use. Turtleneck checks this computer's local state first and opens a one-use local connection form only for a missing service; existing school and Everytime caches are reused.

### Claude Code

```bash
claude plugin marketplace add K-Lunatic/Turtleneck
claude plugin install university-agent@turtleneck
```

Call `/university-agent:turtleneck` in a new Claude Code chat.

### Gemini CLI

Install the skill path explicitly instead of connecting the whole repository:

```bash
gemini skills install https://github.com/K-Lunatic/Turtleneck.git \
  --path skills/university-agent --scope user
gemini skills list --all
```

For a local checkout, run `gemini skills link "$PWD/skills/university-agent" --scope workspace` from the repository root. A web-only Gemini session without local file and command access cannot use school login, sync, or the local exam. See the [Gemini execution guide](skills/university-agent/references/gemini.md).

On first use, a local connection form opens. Enter TLS and Everytime credentials only in the official browser login flow. Passwords are not sent through chat or stored in logs.

## Local-first and privacy

This project runs primarily on a local macOS or Windows desktop. Mobile is also a supported optional path through the ChatGPT Actions gateway running on the user's computer; it is not a standalone mobile app and does not provide device-to-device database synchronization. The gateway is a one-computer helper, not a school-wide service. Account passwords, session cookies, OAuth secrets, personal course IDs, original files, databases, and learning packs are excluded from the repository. Use it only with accounts and materials you are authorized to access, and respect school and Everytime policies.

### Mobile Actions

Mobile Actions supports course, assignment, lecture, notice and todo lookup, sync status, connection removal, assignment progress, and `.tpack`-based web exams. The desktop gateway and its HTTPS tunnel must remain online. Mobile does not expose original-file downloads, course-material body reading, Everytime, or local Codex study sessions, and it never receives passwords, cookies, or original files. Configure the Custom GPT OAuth/Actions connection once and verify the round trip with the target account before relying on it.

See [SECURITY.md](SECURITY.md) for private security reports.

## XERJ Corpus Hub

Turtleneck is listed as a public corpus on the [XERJ Corpus Hub](https://hub.xerj.org/contributors/K-Lunatic). The selected reference is [`49615b7`](https://github.com/K-Lunatic/Turtleneck/commit/49615b7700f66ccfeef1546c181845528943eacf), `feat: add lecture media and activity support`, included under the repository's MIT license.

## Other Coursemos/Moodle schools

For a standard Moodle site, Turtleneck first discovers the signed-in user's courses from `/my/` or `/course/index.php`, then reads visible topics and `/mod/.../view.php?id=...` activities. Unknown activity types are kept in the local catalog instead of being discarded. School-specific SSO, video viewers, downloads, submission status, autonomous-course management, and write paths stay behind an observed school profile; Turtleneck never guesses KKU-only `/local/ubion`, `/local/ubeclass`, or `/local/ubdoc` paths on another school.

## Documentation

- [Skill instructions](skills/university-agent/SKILL.md)
- [Study, exam, and grading contract](skills/university-agent/references/study.md)
- [Common data model](skills/university-agent/references/data-model.md)
- [TLS provider contract](skills/university-agent/references/provider-contract.md)
- [Claude Code guide](skills/university-agent/references/claude-code.md)

## License

MIT. See [LICENSE](LICENSE).
