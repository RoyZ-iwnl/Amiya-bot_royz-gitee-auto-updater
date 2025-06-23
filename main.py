from __future__ import annotations

import os
import asyncio
import importlib
import httpx
from bs4 import BeautifulSoup
from core import AmiyaBotPluginInstance, log, send_to_console_channel, Chain
from amiyabot.util import temp_sys_path

# 获取当前文件所在的目录
curr_dir = os.path.dirname(__file__)

# 定义用于存储上一次Commit哈希值的文件路径
LAST_COMMIT_FILE = os.path.join(curr_dir, 'last_commit.txt')

# --- 插件实例定义 ---
# 定义一个插件实例，用于承载插件的元数据和配置
bot = AmiyaBotPluginInstance(
    name='资源自动更新插件',
    version='1.0',
    plugin_id='royz-gitee-auto-updater',
    plugin_type='system',
    description='定时检查Gitee资源仓库，自动触发更新。',
    document=f'{curr_dir}/README.md',
    global_config_default=f'{curr_dir}/config_default.json',
    global_config_schema=f'{curr_dir}/config_schema.json'
)

# --- 辅助函数 ---

def read_last_commit():
    """从文件中读取上一次记录的Commit哈希值"""
    if not os.path.exists(LAST_COMMIT_FILE):
        return None
    try:
        with open(LAST_COMMIT_FILE, 'r') as f:
            return f.read().strip()
    except Exception as e:
        log.error(f"读取 last_commit.txt 文件失败: {e}")
        return None

def save_last_commit(commit_hash: str):
    """将最新的Commit哈希值写入文件"""
    try:
        with open(LAST_COMMIT_FILE, 'w') as f:
            f.write(commit_hash)
    except Exception as e:
        log.error(f"写入 last_commit.txt 文件失败: {e}")

def import_plugin_lib(module_name):
    """动态导入指定前缀的插件模块"""
    plugin_dir = f'{curr_dir}/../'
    if os.path.exists(plugin_dir):
        folders = os.listdir(plugin_dir)
        for dir_name in folders:
            dir_path =  f'{plugin_dir}{dir_name}'
            if os.path.isdir(dir_path) and dir_name.startswith(module_name):
                with temp_sys_path(os.path.dirname(os.path.abspath(dir_path))):
                    try:
                        module = importlib.import_module(os.path.basename(dir_path))
                        return module
                    except Exception as e:
                        log.error(f"动态导入模块 {dir_name} 失败: {e}")
    return None

async def get_latest_gitee_commit_hash(commit_page_url: str) -> str | None:
    """
    爬取Gitee Commit页面，获取最新的Commit哈希值。
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(commit_page_url, headers=headers, timeout=20)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        latest_commit_div = soup.select_one('div.commit')

        if latest_commit_div and 'data-full-sha' in latest_commit_div.attrs:
            commit_hash = latest_commit_div['data-full-sha']
            return commit_hash
        else:
            log.warning("在Gitee页面上未找到Commit信息，可能是页面结构已改变或URL不正确。")
            await send_to_console_channel(Chain().text("【资源自动更新】错误：无法在Gitee页面上找到Commit信息。"))
            return None
            
    except httpx.RequestError as e:
        log.error(f"请求Gitee页面 '{commit_page_url}' 失败: {e}")
        await send_to_console_channel(Chain().text(f"【资源自动更新】请求Gitee页面失败: {e}"))
        return None
    except Exception as e:
        log.error(f"解析Gitee页面或提取Commit时发生未知错误: {e}")
        await send_to_console_channel(Chain().text(f"【资源自动更新】解析Gitee页面时发生未知错误: {e}"))
        return None


# --- 核心后台任务 ---

async def background_checker():
    """
    这是一个在后台无限循环的任务，用于定时检查更新。
    它自管理循环和休眠时间，以支持动态配置。
    """
    # 初始等待，确保AmiyaBot框架完全启动
    await asyncio.sleep(15)
    log.info("Gitee资源自动更新插件已启动后台检查任务。")

    while True:
        # 在每次循环开始时获取配置，以支持动态调整
        if not bot.get_config('plugin_enabled'):
            await asyncio.sleep(60)
            continue
        
        interval_minutes = bot.get_config('check_interval_minutes')
        interval_seconds = max(interval_minutes, 1) * 60

        try:
            repo_url = bot.get_config('repo_url')
            if not repo_url or not repo_url.startswith('http'):
                log.warning("未在配置中找到有效的目标仓库URL，跳过本次检查。请前往控制台配置。")
                await asyncio.sleep(interval_seconds)
                continue

            log.info(f"开始检查Gitee资源更新: {repo_url}")
            
            last_commit_hash = read_last_commit()
            latest_commit_hash = await get_latest_gitee_commit_hash(repo_url)

            if latest_commit_hash and latest_commit_hash != last_commit_hash:
                log.info(f"检测到新Commit: {latest_commit_hash[:7]} (旧: {last_commit_hash[:7] if last_commit_hash else '无'})，准备更新。")
                await send_to_console_channel(
                    Chain().text(f"【资源自动更新】检测到新版本: {latest_commit_hash[:7]}，开始更新流程。")
                )
                
                gamedata_module = import_plugin_lib('amiyabot-arknights-gamedata')
                
                if gamedata_module:
                    try:
                        log.info("开始下载资源...")
                        await send_to_console_channel(Chain().text("【资源自动更新】开始下载新资源..."))
                        
                        # 统一处理同步和异步函数
                        download_func = getattr(gamedata_module, 'download_gamedata', None)
                        if asyncio.iscoroutinefunction(download_func):
                            await download_func()
                        elif callable(download_func):
                            download_func()
                        
                        log.info("资源下载完成。开始解析资源...")
                        await send_to_console_channel(Chain().text("【资源自动更新】资源下载完成，开始解析..."))
                        
                        init_func = getattr(gamedata_module, 'initialize_data', None)
                        if asyncio.iscoroutinefunction(init_func):
                            await init_func()
                        elif callable(init_func):
                            init_func()

                        log.info("资源解析完成。")
                        save_last_commit(latest_commit_hash)
                        log.info("成功更新本地Commit记录。")
                        await send_to_console_channel(
                            Chain().text(f"【资源自动更新】资源更新并解析成功！当前版本: {latest_commit_hash[:7]}")
                        )
                    except AttributeError:
                        log.error("amiyabot-arknights-gamedata 插件中未找到 download_gamedata 或 initialize_data 函数。")
                        await send_to_console_channel(Chain().text("【资源自动更新】错误：目标插件缺少所需函数。"))
                    except Exception as e:
                        log.error(f"调用gamedata插件函数时发生错误: {e}")
                        await send_to_console_channel(Chain().text(f"【资源自动更新】在执行更新时发生错误: {e}"))
                else:
                    log.error("未找到或无法加载 'amiyabot-arknights-gamedata' 插件。")
                    await send_to_console_channel(Chain().text("【资源自动更新】错误：无法加载gamedata插件。"))
            elif latest_commit_hash:
                log.info("资源已是最新，无需更新。")

        except Exception as e:
            log.error(f"检查更新任务发生意外错误: {e}")
            await send_to_console_channel(Chain().text(f"【资源自动更新】检查任务发生意外错误: {e}"))

        log.info(f"下一次检查将在 {interval_minutes} 分钟后进行。")
        await asyncio.sleep(interval_seconds)

# --- 插件初始化 ---
asyncio.create_task(background_checker())
