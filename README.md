# Pixiv Plus - AstrBot 插件

基于 Lolicon API v2 和 i.yuki.sh 与 i.pixiv.re 的 Pixiv 图片搜索插件

## 核心功能

- **随机图片**：`/pixiv` 无需参数，随机返回一张 Pixiv 作品。
- **标签搜索**：`/pixiv 标签1 标签2` 支持最多 3 个标签（AND 关系），精确匹配。
- **按 ID 获取**：`/pixiv_id 12345678` 根据作品 ID 获取指定图片。
- **每日一图**：每天 9:00 自动推送到所有群组，用户可通过 `/pixiv_today` 手动查看今日图片。
- **R-18 处理**：自动检测标签中的 `r-18` / `r18`，R-18 作品仅返回 `i.pixiv.re` 链接，不下载图片；非 R-18 作品通过 `i.yuki.sh` 加速下载并发送。
- **帮助命令**：`/pixiv_help` 显示所有支持的命令。

## 数据源

- 标签搜索 & 随机：Lolicon API v2（https://api.lolicon.app/setu/v2）
- 按 ID 获取：Pixiv 反代服务（https://pixiv.yuki.sh/api/illust）

## 依赖

- Python 3.8+
- aiohttp
- AstrBot v4.x

## 安装

将插件文件夹放入 AstrBot 的 `plugins` 目录，重启即可。