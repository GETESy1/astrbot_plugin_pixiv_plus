import aiohttp
import asyncio
import tempfile
import os
import json
import re
import datetime
import random

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class PixivSearchPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.api_url = "https://api.lolicon.app/setu/v2"
        self.illust_api_url = "https://pixiv.yuki.sh/api/illust"
        self.recommend_api_url = "https://pixiv.yuki.sh/api/recommend"

        # 每日图片缓存
        self.daily_info = None
        self.daily_img_url = None
        self.daily_is_r18 = False
        self.daily_date = None

        self._daily_task = None
        self._running = True
        self._daily_task = asyncio.create_task(self._daily_scheduler())

    # ---------- 定时任务 ----------
    async def _daily_scheduler(self):
        while self._running:
            now = datetime.datetime.now()
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= target:
                target += datetime.timedelta(days=1)
            delay = (target - now).total_seconds()
            logger.info(f"距离下次每日一图还有 {delay//3600:.0f}h {(delay%3600)//60:.0f}m")
            await asyncio.sleep(delay)
            if not self._running:
                break
            await self._generate_and_send_daily_image()

    async def _generate_and_send_daily_image(self):
        logger.info("正在生成每日一图...")
        # 每日一图依然使用 Lolicon（可保持稳定）
        setu = await self._fetch_random_setu_lolicon()
        if not setu:
            logger.error("获取随机图片失败")
            return
        info, img_url, is_r18 = self._extract_setu_info(setu)
        self.daily_info = info
        self.daily_img_url = img_url
        self.daily_is_r18 = is_r18
        self.daily_date = datetime.date.today()
        await self._broadcast_daily_image(info, img_url, is_r18)

    # ---------- 数据源：Lolicon ----------
    async def _fetch_random_setu_lolicon(self):
        payload = {
            "r18": 2,
            "num": 1,
            "proxy": "i.yuki.sh",
            "size": ["original"],
            "dsc": True
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.api_url, json=payload, timeout=30) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if data.get("error") or not data.get("data"):
                        return None
                    return data["data"][0]
            except:
                return None

    # ---------- 数据源：pixiv.yuki.sh 推荐 ----------
    async def _fetch_random_setu_yuki(self):
        """从 pixiv.yuki.sh 推荐接口获取随机图片"""
        async with aiohttp.ClientSession() as session:
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                async with session.get(self.recommend_api_url, headers=headers, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(f"推荐接口 HTTP {resp.status}")
                        return None
                    data = await resp.json()
                    # 响应结构: { success: true, data: [ ... ] }
                    if not data.get("success", False):
                        logger.warning(f"推荐接口返回失败: {data.get('message')}")
                        return None
                    items = data.get("data", [])
                    if not items:
                        logger.warning("推荐接口返回空列表")
                        return None
                    # 取第一个作品
                    item = items[0]
                    # 转换为与 Lolicon 兼容的格式
                    # 需要提取 pid, title, author, urls.original, tags
                    return self._convert_yuki_item_to_lolicon(item)
            except Exception as e:
                logger.error(f"推荐接口异常: {e}")
                return None

    def _convert_yuki_item_to_lolicon(self, item):
        """将 pixiv.yuki.sh 的推荐项转换为类似 Lolicon 的格式"""
        # 推荐接口返回的数据结构与 /api/illust 的 data 相同
        # 但我们只需要保留必要的字段
        return {
            "pid": item.get("id"),
            "p": 0,  # 推荐只返回单页
            "title": item.get("title", "无标题"),
            "author": item.get("user", {}).get("name", "未知作者"),
            "urls": item.get("urls", {}),
            "tags": item.get("tags", [])
        }

    # ---------- 统一随机获取（随机选择数据源） ----------
    async def _fetch_random_setu(self):
        """随机选择 Lolicon 或 Yuki 推荐"""
        if random.choice([True, False]):
            logger.info("随机数据源: Lolicon API")
            return await self._fetch_random_setu_lolicon()
        else:
            logger.info("随机数据源: Yuki Recommend")
            return await self._fetch_random_setu_yuki()

    # ---------- 信息提取 ----------
    def _extract_setu_info(self, setu):
        pid = setu.get("pid")
        p = setu.get("p", 0)
        title = setu.get("title", "无标题")
        author = setu.get("author", "未知作者")
        urls = setu.get("urls", {})
        img_url = urls.get("original")
        tags = setu.get("tags", [])
        is_r18 = any(re.search(r'r-?18', tag, re.IGNORECASE) for tag in tags)
        info = f"📖 标题：{title}\n👤 作者：{author}\n🆔 PID：{pid}\n📄 页码：{p}\n"
        info += f"🏷️ 全部标签：{', '.join(tags)}\n"
        return info, img_url, is_r18

    async def _fetch_setu_by_id(self, pid):
        async with aiohttp.ClientSession() as session:
            try:
                url = f"{self.illust_api_url}?id={pid}"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                async with session.get(url, headers=headers, timeout=30) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if not data.get("success", False):
                        return None
                    illust_data = data.get("data")
                    if not illust_data or not illust_data.get("id"):
                        return None
                    return illust_data
            except:
                return None

    def _extract_info_from_illust(self, data):
        pid = data.get("id")
        title = data.get("title", "无标题")
        user = data.get("user", {})
        author = user.get("name", "未知作者")
        urls = data.get("urls", {})
        img_url = urls.get("original")
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        elif not isinstance(tags, list):
            tags = []
        is_r18 = any(re.search(r'r-?18', tag, re.IGNORECASE) for tag in tags)
        info = f"📖 标题：{title}\n👤 作者：{author}\n🆔 PID：{pid}\n"
        info += f"🏷️ 全部标签：{', '.join(tags)}\n"
        return info, img_url, is_r18

    async def _broadcast_daily_image(self, info, img_url, is_r18):
        try:
            if is_r18:
                link = img_url.replace("https://pixiv.yuki.sh/image", "https://i.pixiv.re")
                await self.context.broadcast_message(info + f"🔞 R-18 作品，请自行访问原图：{link}")
            else:
                await self.context.broadcast_message(info)
                async with aiohttp.ClientSession() as session:
                    async with session.get(img_url, timeout=30) as resp:
                        if resp.status != 200:
                            await self.context.broadcast_message(f"⚠️ 图片下载失败，请访问原图：{img_url}")
                            return
                        img_data = await resp.read()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_data)
                    tmp_path = tmp.name
                from astrbot.api.message import MessageChain, Image
                chain = MessageChain()
                chain.append(Image.from_file(tmp_path))
                await self.context.broadcast_message(chain)
                try:
                    os.unlink(tmp_path)
                except:
                    pass
        except Exception as e:
            logger.error(f"广播每日图片失败: {e}")

    # ---------- 命令：帮助 ----------
    @filter.command("pixiv_help")
    async def pixiv_help(self, event: AstrMessageEvent):
        help_text = (
            "📌 Pixiv Plus 插件帮助\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🔹 /pixiv                    获取一张随机图片（双源随机）\n"
            "🔹 /pixiv <标签1> <标签2>    按标签搜索（最多3个，AND关系）\n"
            "🔹 /pixiv_id <pid>           根据作品ID获取图片\n"
            "🔹 /pixiv_today              查看今日每日一图（若未生成则生成）\n"
            "🔹 /pixiv_help               显示此帮助\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💡 标签支持中文、英文、日文\n"
            "💡 R-18 作品仅返回链接，不下载图片\n"
            "💡 每日一图于每天 9:00 自动发送"
        )
        yield event.plain_result(help_text)

    # ---------- 命令：通过ID获取图片 ----------
    @filter.command("pixiv_id")
    async def pixiv_id(self, event: AstrMessageEvent):
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result("请提供作品ID，例如：/pixiv_id 12345678")
            return
        pid = parts[1]
        if not pid.isdigit():
            yield event.plain_result("ID 必须为数字")
            return

        yield event.plain_result(f"正在获取作品 {pid} ...")
        data = await self._fetch_setu_by_id(pid)
        if not data:
            yield event.plain_result(f"未找到作品 {pid}，请检查ID是否正确或作品已删除")
            return

        info, img_url, is_r18 = self._extract_info_from_illust(data)
        if not img_url:
            yield event.plain_result("无法获取图片地址，可能作品不支持")
            return

        if is_r18:
            link = img_url.replace("https://pixiv.yuki.sh/image", "https://i.pixiv.re")
            info += f"🔞 R-18 作品，请自行访问原图：{link}"
            yield event.plain_result(info)
            return

        yield event.plain_result(info)
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(img_url, timeout=30) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"⚠️ 图片下载失败，请访问原图：{img_url}")
                        return
                    img_data = await resp.read()
            except:
                yield event.plain_result(f"⚠️ 图片下载失败，请访问原图：{img_url}")
                return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(img_data)
            tmp_path = tmp.name
        yield event.image_result(tmp_path)
        try:
            os.unlink(tmp_path)
        except:
            pass

    # ---------- 命令：查看今日图片 ----------
    @filter.command("pixiv_today")
    async def pixiv_today(self, event: AstrMessageEvent):
        today = datetime.date.today()
        if self.daily_date == today and self.daily_info is not None:
            info = self.daily_info
            img_url = self.daily_img_url
            is_r18 = self.daily_is_r18
        else:
            yield event.plain_result("今日每日一图尚未生成，正在生成...")
            setu = await self._fetch_random_setu_lolicon()
            if not setu:
                yield event.plain_result("生成失败，请稍后重试")
                return
            info, img_url, is_r18 = self._extract_setu_info(setu)
            self.daily_info = info
            self.daily_img_url = img_url
            self.daily_is_r18 = is_r18
            self.daily_date = today

        if is_r18:
            link = img_url.replace("https://i.yuki.sh", "https://i.pixiv.re")
            yield event.plain_result(info + f"🔞 R-18 作品，请自行访问原图：{link}")
        else:
            yield event.plain_result(info)
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(img_url, timeout=30) as resp:
                        if resp.status != 200:
                            yield event.plain_result(f"⚠️ 图片下载失败，请访问原图：{img_url}")
                            return
                        img_data = await resp.read()
                except:
                    yield event.plain_result(f"⚠️ 图片下载失败，请访问原图：{img_url}")
                    return
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(img_data)
                tmp_path = tmp.name
            yield event.image_result(tmp_path)
            try:
                os.unlink(tmp_path)
            except:
                pass

    # ---------- 主搜索命令（随机模式现已双源） ----------
    @filter.command("pixiv")
    async def pixiv_search(self, event: AstrMessageEvent):
        parts = event.message_str.strip().split()
        raw_tags = [t for t in parts[1:] if not t.startswith("-")]
        is_random = len(raw_tags) == 0

        if not is_random and len(raw_tags) > 3:
            yield event.plain_result("标签数量不能超过 3 个（AND 限制）")
            return

        if is_random:
            # 随机模式：从两个数据源中随机选一个
            logger.info("随机模式，双源随机选择")
            setu = await self._fetch_random_setu()
            if not setu:
                # 如果随机选择的源失败，尝试另一个
                logger.warning("首选随机源失败，尝试备用源")
                # 如果之前选的是 Lolicon，则试 Yuki，反之亦然
                # 简单起见，直接再调用一次但强制使用另一个源（由于我们没有记录选择，这里重新调用 _fetch_random_setu 会再次随机，可能又选同一个）
                # 更稳妥：先尝试 Lolicon，如果失败再 Yuki
                setu = await self._fetch_random_setu_lolicon()
                if not setu:
                    setu = await self._fetch_random_setu_yuki()
            if not setu:
                yield event.plain_result("所有数据源均未返回图片，请稍后重试")
                return
            info, img_url, is_r18 = self._extract_setu_info(setu)
            info = "🎲 随机图片\n" + info
        else:
            # 标签搜索：使用 Lolicon（因为 Yuki 推荐不支持标签）
            payload = {
                "r18": 2,
                "num": 1,
                "proxy": "i.yuki.sh",
                "size": ["original"],
                "dsc": True,
                "tag": [[tag] for tag in raw_tags]
            }
            logger.info(f"搜索 Pixiv 标签: {raw_tags}")
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(self.api_url, json=payload, timeout=30) as resp:
                        if resp.status != 200:
                            yield event.plain_result(f"API 请求失败（HTTP {resp.status}）")
                            return
                        data = await resp.json()
                        if data.get("error"):
                            yield event.plain_result(f"API 错误：{data['error']}")
                            return
                        setu_list = data.get("data", [])
                        if not setu_list:
                            yield event.plain_result("没有找到任何图片")
                            return
                        setu = setu_list[0]
                        info, img_url, is_r18 = self._extract_setu_info(setu)
                        # 匹配检查
                        tags = setu.get("tags", [])
                        matched_all = all(any(req.lower() in tag.lower() for tag in tags) for req in raw_tags)
                        unmatched = [req for req in raw_tags if not any(req.lower() in tag.lower() for tag in tags)]
                        if matched_all:
                            info += f"✅ 匹配成功！包含所有请求标签：{', '.join(raw_tags)}\n"
                        else:
                            info += f"❌ 未匹配标签：{', '.join(unmatched)}\n"
                            info += "💡 提示：未完全匹配所有标签，可能过于具体。\n"
                except asyncio.TimeoutError:
                    yield event.plain_result("API 请求超时，请稍后重试")
                    return
                except Exception as e:
                    logger.error(f"Pixiv 搜索出错: {e}")
                    yield event.plain_result(f"发生异常：{str(e)}")
                    return

        # 统一处理结果（R-18 检查）
        if is_r18:
            # 将链接替换为 i.pixiv.re（兼容两种域名）
            if "pixiv.yuki.sh/image" in img_url:
                link = img_url.replace("https://pixiv.yuki.sh/image", "https://i.pixiv.re")
            else:
                link = img_url.replace("https://i.yuki.sh", "https://i.pixiv.re")
            info += f"🔞 R-18 作品，请自行访问原图：{link}"
            yield event.plain_result(info)
            return

        # 非 R-18：下载并发送
        yield event.plain_result(info)
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(img_url, timeout=30) as img_resp:
                    if img_resp.status != 200:
                        raise Exception(f"HTTP {img_resp.status}")
                    img_data = await img_resp.read()
            except:
                # 下载失败，提供链接（同样替换为 i.pixiv.re）
                if "pixiv.yuki.sh/image" in img_url:
                    fallback = img_url.replace("https://pixiv.yuki.sh/image", "https://i.pixiv.re")
                else:
                    fallback = img_url.replace("https://i.yuki.sh", "https://i.pixiv.re")
                yield event.plain_result(f"⚠️ 图片下载失败，请访问原图：{fallback}")
                return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(img_data)
            tmp_path = tmp.name
        yield event.image_result(tmp_path)
        try:
            os.unlink(tmp_path)
        except:
            pass

    async def terminate(self):
        self._running = False
        if self._daily_task:
            self._daily_task.cancel()
            try:
                await self._daily_task
            except asyncio.CancelledError:
                pass
        logger.info("每日一图定时任务已终止")