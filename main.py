from __future__ import annotations

import os
import asyncio
import importlib
import re
import subprocess
from core import AmiyaBotPluginInstance, log, send_to_console_channel, Chain
from amiyabot.util import temp_sys_path
from typing import Optional, Any

# 获取当前文件所在的目录
curr_dir = os.path.dirname(__file__)

# 定义用于存储上一次Commit哈希值的文件路径
LAST_COMMIT_FILE = os.path.join(curr_dir, 'last_commit.txt')

class GiteeAutoUpdater(AmiyaBotPluginInstance):
    # 用于存储后台任务的引用，以便在插件卸载时可以取消它
    background_task: Optional[asyncio.Task] = None

    def install(self):
        """
        插件安装（或重载）时调用。
        在这里启动后台检查任务，确保任务不会重复创建。
        """
        if self.background_task:
            # 如果已有任务存在，先取消它
            self.background_task.cancel()
        
        # 创建新的后台任务
        self.background_task = asyncio.create_task(background_checker())
        log.info("Gitee资源自动更新插件已启动后台检查任务。")

    def uninstall(self):
        """
        插件卸载（或重载）时调用。
        在这里取消后台任务，防止任务泄露。
        """
        if self.background_task:
            self.background_task.cancel()
            self.background_task = None
            log.info("Gitee资源自动更新插件已停止后台检查任务。")

# --- 插件实例定义 ---
bot = GiteeAutoUpdater(
    name='资源自动更新插件',
    version='1.2',
    plugin_id='royz-gitee-auto-updater',
    plugin_type='system',
    description='定时检查Gitee资源仓库，自动触发gamedata插件进行更新。',
    document=f'{curr_dir}/README.md',
    global_config_default=f'{curr_dir}/config_default.json',
    global_config_schema=f'{curr_dir}/config_schema.json'
)

# --- 辅助函数 ---

def read_last_commit():
    if not os.path.exists(LAST_COMMIT_FILE):
        return None
    try:
        with open(LAST_COMMIT_FILE, 'r') as f:
            return f.read().strip()
    except Exception as e:
        log.error(f"读取 last_commit.txt 文件失败: {e}")
        return None

def save_last_commit(commit_hash: str):
    try:
        with open(LAST_COMMIT_FILE, 'w') as f:
            f.write(commit_hash)
    except Exception as e:
        log.error(f"写入 last_commit.txt 文件失败: {e}")

def import_plugin_lib(module_name: str) -> Optional[Any]:
    plugin_dir = os.path.abspath(os.path.join(curr_dir, '..'))
    if os.path.exists(plugin_dir):
        for dir_name in os.listdir(plugin_dir):
            if dir_name.startswith(module_name):
                with temp_sys_path(plugin_dir):
                    try:
                        module = importlib.import_module(dir_name)
                        # 重载模块确保获取到最新版本，尤其是在gamedata插件也更新后
                        importlib.reload(module)
                        return module
                    except Exception as e:
                        log.error(f"动态导入模块 {dir_name} 失败: {e}")
    return None

async def get_latest_gitee_commit_hash(repo_page_url: str) -> str | None:
    git_url = re.sub(r'/commits/.*$', '.git', repo_page_url)
    log.info(f"转换后的Git仓库地址: {git_url}")

    try:
        command = ['git', 'ls-remote', git_url, 'HEAD']
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_message = stderr.decode('utf-8', errors='ignore').strip()
            log.error(f"执行 'git ls-remote' 失败 (返回码: {process.returncode}): {error_message}")
            if "git' is not recognized" in error_message or "不是内部或外部命令" in error_message or "not found" in error_message:
                await send_to_console_channel(Chain().text("【资源自动更新】错误：'git' 命令未找到。请确保 Git 已安装并配置在系统的 PATH 环境变量中。"))
            else:
                 await send_to_console_channel(Chain().text(f"【资源自动更新】错误：无法访问Git仓库: {error_message}"))
            return None

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
        log.error(f"使用 'git ls-remote' 获取最新Commit时发生未知错误: {e}", exc_info=True)
        await send_to_console_channel(Chain().text(f"【资源自动更新】检查更新时发生未知错误: {e}"))
        return None

# --- 核心后台任务 ---

async def background_checker():
    """
    核心后台任务，使用简化的更新逻辑。
    """
    await asyncio.sleep(15) # 等待Bot完全启动

    while True:
        try:
            if not bot.get_config('plugin_enabled'):
                await asyncio.sleep(60)
                continue
            
            interval_minutes = bot.get_config('check_interval_minutes')
            interval_seconds = max(interval_minutes, 1) * 60

            try:
                repo_url = bot.get_config('repo_url')
                if not repo_url or not repo_url.startswith('http'):
                    log.warning("未在配置中找到有效的目标仓库URL，跳过本次检查。")
                    await asyncio.sleep(interval_seconds)
                    continue

                log.info(f"开始检查Gitee资源更新: {repo_url}")
                
                last_commit_hash = read_last_commit()
                latest_commit_hash = await get_latest_gitee_commit_hash(repo_url)

                if latest_commit_hash and latest_commit_hash != last_commit_hash:
                    log.info(f"检测到新Commit: {latest_commit_hash[:7]} (旧: {last_commit_hash[:7] if last_commit_hash else '无'})，准备更新。")
                    
                    gamedata_module = import_plugin_lib('amiyabot-arknights-gamedata')
                    
                    if not gamedata_module:
                        log.error("未找到或无法加载 'amiyabot-arknights-gamedata' 插件。")
                        await send_to_console_channel(Chain().text("【资源自动更新】错误：无法加载gamedata插件。"))
                        await asyncio.sleep(interval_seconds)
                        continue
                    
                    # 尝试从 __init__.py 或 builder.py 中获取 download_gamedata 函数
                    download_func = getattr(gamedata_module, 'download_gamedata', None)
                    if not callable(download_func) and hasattr(gamedata_module, 'builder'):
                        download_func = getattr(gamedata_module.builder, 'download_gamedata', None)

                    if not callable(download_func):
                        log.error("在 gamedata 插件中未找到可调用的 'download_gamedata' 函数。")
                        await send_to_console_channel(Chain().text("【资源自动更新】错误：目标插件结构已改变，找不到更新函数。"))
                        await asyncio.sleep(interval_seconds)
                        continue

                    # --- 步骤 1: 触发下载 ---
                    log.info("开始触发资源下载...")
                    await send_to_console_channel(
                        Chain().text(f"【资源自动更新】检测到新版本: {latest_commit_hash[:7]}，已将更新任务交由 gamedata 插件处理。")
                    )
                    download_func() # 直接调用，不等待

                    # --- 步骤 2: 立即更新本地记录 ---
                    # 只要触发了下载，就认为我们的任务完成了。gamedata会负责后续所有事情。
                    save_last_commit(latest_commit_hash)
                    log.info("资源更新已触发，本地Commit记录已更新。gamedata插件将自动处理后续流程。")

                elif latest_commit_hash:
                    log.info("资源已是最新，无需更新。")

            except Exception as e:
                log.error(f"检查更新任务发生意外错误: {e}", exc_info=True)
                await send_to_console_channel(Chain().text(f"【资源自动更新】检查任务发生意外错误: {e}"))

            log.info(f"下一次检查将在 {interval_minutes} 分钟后进行。")
            await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            # 捕获任务取消异常，优雅退出循环
            log.info("后台检查任务被取消。")
            break
        except Exception as e:
            # 捕获其他未知异常，防止循环意外终止
            log.error(f"后台检查任务主循环发生严重错误: {e}", exc_info=True)
            await asyncio.sleep(60) # 发生严重错误后等待一段时间再重试