from __future__ import annotations

import os
import asyncio
import importlib
import re
import subprocess
from core import AmiyaBotPluginInstance, log, send_to_console_channel, Chain
from amiyabot.util import temp_sys_path

# 获取当前文件所在的目录
curr_dir = os.path.dirname(__file__)

# 定义用于存储上一次Commit哈希值的文件路径
LAST_COMMIT_FILE = os.path.join(curr_dir, 'last_commit.txt')

# --- 插件实例定义 ---
bot = AmiyaBotPluginInstance(
    name='资源自动更新插件',
    version='1.1',
    plugin_id='royz-gitee-auto-updater',
    plugin_type='system',
    description='定时通过Git命令检查Gitee资源仓库，自动触发更新。',
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

async def get_latest_gitee_commit_hash(repo_page_url: str) -> str | None:
    """
    使用 'git ls-remote' 命令从远程仓库获取最新的Commit哈希值，无需克隆。
    """
    # 自动将仓库的 commits 页面 URL 转换为 .git URL
    # 例如: https://gitee.com/amiya-bot/amiya-bot-assets/commits/master -> https://gitee.com/amiya-bot/amiya-bot-assets.git
    git_url = re.sub(r'/commits/.*$', '.git', repo_page_url)
    log.info(f"转换后的Git仓库地址: {git_url}")

    try:
        # 构建 git ls-remote 命令，查询 'HEAD' 来获取默认分支的最新 commit
        command = ['git', 'ls-remote', git_url, 'HEAD']
        
        # 异步执行外部命令
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()

        # 检查命令是否成功执行
        if process.returncode != 0:
            error_message = stderr.decode('utf-8', errors='ignore').strip()
            log.error(f"执行 'git ls-remote' 失败 (返回码: {process.returncode}): {error_message}")
            if "git' is not recognized" in error_message or "不是内部或外部命令" in error_message or "not found" in error_message:
                await send_to_console_channel(Chain().text("【资源自动更新】错误：'git' 命令未找到。请确保 Git 已安装并配置在系统的 PATH 环境变量中。"))
            else:
                 await send_to_console_channel(Chain().text(f"【资源自动更新】错误：无法访问Git仓库: {error_message}"))
            return None

        # 解析命令输出，格式通常是: <commit_hash>\tHEAD
        output = stdout.decode('utf-8').strip()
        if not output:
            log.warning("'git ls-remote' 命令没有返回任何输出，请检查仓库URL是否正确。")
            return None
        
        commit_hash = output.split()[0]
        return commit_hash

    except FileNotFoundError:
        log.error("命令 'git' 未找到。请确保 Git 已被安装并且其路径已添加到系统的 PATH 环境变量中。")
        await send_to_console_channel(Chain().text("【资源自动更新】错误：'git' 命令未找到。请确保 Git 已安装并配置在系统的 PATH 环境变量中。"))
        return None
    except Exception as e:
        log.error(f"使用 'git ls-remote' 获取最新Commit时发生未知错误: {e}")
        await send_to_console_channel(Chain().text(f"【资源自动更新】检查更新时发生未知错误: {e}"))
        return None


# --- 核心后台任务 ---

async def background_checker():
    """
    这是一个在后台无限循环的任务，用于定时检查更新。
    它自管理循环和休眠时间，以支持动态配置。
    """
    await asyncio.sleep(15)
    log.info("Gitee资源自动更新插件已启动后台检查任务。")

    while True:
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
            # 调用基于Git的检查函数
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

