# Turtleneck

<p align="center">
  <img src="assets/turtleneck.png" width="180" alt="Turtleneck mascot">
</p>

<p align="center">
  <strong>Collect course materials, study in focused pieces, and practice like an exam.</strong><br>
  A local-first university study skill for Codex, Claude Code, and Gemini.
</p>

<p align="center">
  <a href="README.md">한국어</a> ·
  English ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

## What it does

Turtleneck organizes assignments, announcements, lectures, course files, schedules, and study records on the computer where it runs. It extracts readable material in small pieces for the current AI host and opens a local web exam instead of turning the chat into an exam screen.

- Sync KKU TLS courses, activities, announcements, assignments, lectures, and downloadable files.
- Connect Everytime for timetable, course reviews, boards, and classroom information.
- Build study material and question candidates from course files.
- Open local exams, save attempts, grade answers, and review weak areas.
- Keep passwords in macOS Keychain or Windows protected storage; do not put passwords, cookies, or original course files in the repository.

## Quick start

Requirements: a local Codex, Claude Code, or Gemini environment on macOS or Windows, plus Python 3.10 or newer for source installs. On a Python-free desktop, use the signed `turtleneck-macos-arm64` or `turtleneck-windows-x64` no-install bundle from GitHub Releases; the launcher does not pipe a remote installer into a shell.

To use a no-install bundle, extract it and run `turtleneck` on macOS or `turtleneck.exe` on Windows. Register the plugin with the host's normal install command; the bundle supplies the local runner and Python runtime. See the [release policy](RELEASE.md) and [change log](CHANGELOG.md).

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

### Gemini

Connect this repository or register `skills/university-agent` as the `turtleneck` skill. See the [Gemini execution guide](skills/university-agent/references/gemini.md) for local sandbox and network rules.

On first use, a local connection form opens. Enter TLS and Everytime credentials only in the official browser login flow. Passwords are not sent through chat or stored in logs.

## Local-first and privacy

This project is designed for local desktop use on macOS and Windows. It does not provide device-to-device synchronization. The optional ChatGPT Actions gateway is a one-computer helper, not a school-wide service. Account passwords, session cookies, OAuth secrets, personal course IDs, original files, databases, and learning packs are excluded from the repository. Use it only with accounts and materials you are authorized to access, and respect school and Everytime policies.

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
