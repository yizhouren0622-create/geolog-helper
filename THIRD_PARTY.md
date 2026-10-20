# 开源来源与改动

## 使用的实现

- c:geo — https://github.com/cgeo/cgeo
  - 版本：`d23e863148ca64cb1d51bee6e10d776c657a6a94`（2026-10-18）
  - Apache License 2.0。项目原许可保留在 LICENSE。
  - 依据 `main/src/main/java/cgeo/geocaching/connector/gc/GCAuthAPI.java` 和 `GCLogAPI.java` 中的认证、CSRF、tRPC 日志创建、multipart 图片上传与标题更新方法，改写为 Python 的 GCClient；原 Java 源码保留在 `upstream/`。
  - 改动：独立火狐浏览器登录，Python/Playwright 请求，本地 SQLite 草稿，照片压缩去元数据，发布前预览，已确认 ID 持久化，未知结果需用户核对后再试。未移植 c:geo Android 界面、Trackable 或删除功能。
- Playwright Python — https://github.com/microsoft/playwright-python （Apache-2.0），版本 1.64.0。
- Firefox — https://www.mozilla.org/firefox/ ，使用 Playwright 官方分发的兼容构建 Firefox 157.0 / revision 1555，安装在本项目 `.browsers/` 中，未替换系统浏览器。Firefox 的许可信息可在其 `about:license` 页面查看；Playwright 兼容性说明：https://playwright.dev/python/docs/browsers#firefox 。独立配置位于 `data/firefox-profile/`。
- Pillow — https://github.com/python-pillow/Pillow （MIT-CMU），版本 13.0.0，生成去 EXIF 的 JPEG 上传副本。依赖本身的许可随安装包保留。

## 查找过的现成工具

- GC little helper II — https://github.com/2Abendsegler/GClh ，master `0272b65427c8d2637ef183f92966f53bd5436871`，发布版脚本 0.18.15，GPL-2.0。支持日志模板和签名，适用于浏览器脚本管理器；没有直接满足本项目的选照片后统一发布工作流。本助手未包含或执行该脚本，未复制它的源码；仅参考功能方向。
- btittelbach/gctools — https://github.com/btittelbach/gctools ，有 field notes 批量日志脚本，但日志功能依赖 Python 2/旧网页，不作为当前 Windows 部署方案。
- OpenSAK — https://github.com/OpenSAK-Org/OpenSAK ，跨平台缓存管理工具，当前 README 写明没有 Geocaching Live API 集成，不满足本次上传目标。
- pycaching — https://github.com/tomasbedrich/pycaching ，检查过 post_log 实现，未采用，未复制源码。

截至本次检索，未找到覆盖这套 Windows 选照片、点选描述、一键发布流程的现成 Geocaching 专用 AI skill。本助手是为本次需求适配的本地程序，不是 c:geo 官方 Windows 版本，也不是 Geocaching 官方产品。
