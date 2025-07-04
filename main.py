from __future__ import annotations

import os
import time
import asyncio
import importlib
import subprocess
from core import AmiyaBotPluginInstance, log, send_to_console_channel, Chain, GitAutomation, event_bus, Requirement
from core import bot as main_bot
from core.resource.arknightsGameData import ArknightsConfig, ArknightsGameData
from typing import Optional

# 获取当前文件所在的目录
curr_dir = os.path.dirname(__file__)

# 定义用于存储上一次Commit哈希值的文件路径
LAST_COMMIT_FILE = os.path.join(curr_dir, 'last_commit.txt')

# --- 插件实例定义 ---
bot = AmiyaBotPluginInstance(
    name='资源自动更新插件',
    version='1.4',
    plugin_id='royz-gitee-auto-updater',
    plugin_type='',
    description='定时检查Gitee资源仓库，通过直接调用核心组件进行更新和构建，绕过事件总线。',
    document=f'{curr_dir}/README.md',
    global_config_default=f'{curr_dir}/config_default.json',
    global_config_schema=f'{curr_dir}/config_schema.json',
    requirements=[Requirement('amiyabot-arknights-gamedata', official=True)]
)

# --- 状态变量 ---
# 用于记录上一次执行实际检查的时间戳，初始化为0.0，确保机器人启动后会立即执行一次检查
last_check_timestamp = 0.0

# --- 辅助函数 ---

def read_last_commit() -> Optional[str]:
    """读取本地存储的最后一个Commit哈希值"""
    if not os.path.exists(LAST_COMMIT_FILE):
        return None
    try:
        with open(LAST_COMMIT_FILE, 'r') as f:
            return f.read().strip()
    except Exception as e:
        log.error(f"读取 last_commit.txt 文件失败: {e}")
        return None

def save_last_commit(commit_hash: str):
    """保存最新的Commit哈希值到本地文件"""
    try:
        with open(LAST_COMMIT_FILE, 'w') as f:
            f.write(commit_hash)
    except Exception as e:
        log.error(f"写入 last_commit.txt 文件失败: {e}")

async def get_latest_gitee_commit_hash(repo_page_url: str) -> Optional[str]:
    """通过git命令获取远程仓库最新的Commit哈希值"""
    if not repo_page_url.endswith('.git'):
        git_url = f"{repo_page_url}.git"
    else:
        git_url = repo_page_url
    
    try:
        command = ['git', 'ls-remote', git_url, 'HEAD']
        process = await asyncio.create_subprocess_exec(
            *command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
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

# --- 核心逻辑 ---

async def perform_update_check():
    """
    执行实际的资源检查、下载和构建任务。
    这个函数包含了所有耗时的操作。
    """
    try:
        # 从配置中实时读取仓库URL
        repo_url = bot.get_config('repo_url')
        if not repo_url or not repo_url.startswith('http'):
            log.warning("未在配置中找到有效的目标仓库URL，跳过本次检查。")
            return

        log.info(f"开始检查资源更新: {repo_url}")
        
        last_commit_hash = read_last_commit()
        latest_commit_hash = await get_latest_gitee_commit_hash(repo_url)

        if latest_commit_hash and latest_commit_hash != last_commit_hash:
            log.info(f"检测到新Commit: {latest_commit_hash[:7]} (旧: {last_commit_hash[:7] if last_commit_hash else '无'})，准备更新。")
            
            gamedata_plugin_id = 'amiyabot-arknights-gamedata'
            gamedata_plugin = main_bot.plugins.get(gamedata_plugin_id)
            if not gamedata_plugin:
                log.error(f"无法从框架中获取ID为 '{gamedata_plugin_id}' 的插件实例。")
                return
            
            gamedata_module = importlib.import_module(gamedata_plugin.__module__)
            gamedata_path = getattr(gamedata_module, 'gamedata_path', 'resource/gamedata')
            repo = getattr(gamedata_module, 'repo', 'https://gitee.com/amiya-bot/amiya-bot-assets.git')
            
            def run_blocking_update_tasks():
                log.info("步骤1: 开始执行资源下载 (后台线程)...")
                GitAutomation(gamedata_path, repo).update(['--depth 1'])
                log.info("资源下载完成。")
                
                log.info("步骤2: 开始执行数据初始化 (后台线程)...")
                ArknightsConfig.initialize()
                ArknightsGameData.initialize()
                log.info("数据初始化完成。")

            await send_to_console_channel(
                Chain().text(f"【资源自动更新】检测到新版本: {latest_commit_hash[:7]}，开始执行更新和解析...")
            )
            
            await asyncio.to_thread(run_blocking_update_tasks)
            log.info("后台下载与解析任务已完成。")

            log.info("步骤3: 在主线程中触发数据构建事件...")
            event_bus.publish('gameDataInitialized')
            log.info("数据构建事件已成功发布。")

            save_last_commit(latest_commit_hash)
            log.info("完整的资源更新流程已执行完毕，本地Commit记录已更新。")

        elif latest_commit_hash:
            log.info("资源已是最新，无需更新。")

    except Exception as e:
        log.error(f"执行更新检查任务时发生意外错误: {e}", exc_info=True)
        await send_to_console_channel(Chain().text(f"【资源自动更新】检查任务发生意外错误: {e}"))


@bot.timed_task(each=10)
async def timed_worker(_):
    """
    轻量的调度器，每10秒运行一次。
    它会检查配置，并决定是否要触发真正的更新检查任务。
    """
    global last_check_timestamp

    # 1. 动态读取总开关，如果关闭则直接返回
    if not bot.get_config('plugin_enabled'):
        return

    # 2. 动态读取用户设置的检查间隔（分钟）
    try:
        # 'check_interval_minutes'
        interval_minutes = int(bot.get_config('check_interval_minutes', 30))
    except (ValueError, TypeError):
        log.warning(f"配置中的'check_interval_minutes'值无效，将使用默认值30分钟。")
        interval_minutes = 30
    
    # 转换为秒
    interval_seconds = interval_minutes * 60

    # 3. 判断是否到达检查时间
    current_time = time.time()
    if current_time - last_check_timestamp >= interval_seconds:
        log.info(f"到达预定检查时间（间隔: {interval_minutes} 分钟），准备执行更新检查。")
        # 立刻更新时间戳，防止因任务执行时间过长导致下个周期重复执行
        last_check_timestamp = current_time
        # 调用核心逻辑
        await perform_update_check()