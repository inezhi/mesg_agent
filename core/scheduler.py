"""
内置调度器 - 一次性延时任务 + Cron 周期性任务

逻辑：任务持久化在 jobs.json 中，后台线程每 10 秒检查一次。
触发时：调用 chat_fn(message, "scheduler") -> LLM 处理 -> 通过工具发送消息。

依赖：标准库 + croniter (pip install croniter)
"""


import threading
import time
import json
import os
from datetime import datetime, timezone, timedelta

from loguru import logger

CST = timezone(timedelta(hours=8))


# ============================================================
#  状态管理 (State)
# ============================================================

_jobs = []                    # 当前内存中的任务列表
_jobs_file = ""               # 存储文件路径
_chat_fn = None               # 由 init() 注入的对话函数
_jobs_lock = threading.Lock() # 任务列表线程锁


def init(jobs_file, chat_fn):
    """
    初始化调度器。
    :param jobs_file: 任务文件路径，用于持久化任务。
    :param chat_fn: 用于触发任务的对话函数，签名 chat_fn(message: str, session_key: str) -> str。
    """
    global _jobs_file, _chat_fn
    _jobs_file = jobs_file
    _chat_fn = chat_fn
    _load_jobs()

    if _chat_fn is None:
        logger.error("[scheduler]scheduler not initialized: chat_fn is None")
        raise RuntimeError("scheduler not initialized: chat_fn is None")
    
    
    logger.info(f"[scheduler] (3)调度器初始化完毕，已加载 {len(_jobs)} 个任务")

def start():
    """Start background check thread"""
    # 创建一个线程对象，指定线程要执行的函数是 _loop，并设置为守护线程
    #   - 主线程结束时自动终止：当所有非守护线程结束时，守护线程会被强制终止，程序退出
    #   - 不能阻止程序退出：如果只有守护线程在运行，程序会直接结束
    #   - 适合后台任务：如日志监控、心跳检测、后台清理等
    t = threading.Thread(target=_loop, daemon=True)
    t.start()

# ============================================================
#  内部核心逻辑 (Internals)
# ============================================================
def _load_jobs():
    """从本地 JSON 文件加载任务"""
    global _jobs
    if os.path.exists(_jobs_file):
        try:
            with open(_jobs_file, "r", encoding="utf-8") as f:
                _jobs = json.load(f)
        except Exception:
            _jobs = []
    else:
        _jobs = []

def _check():
    """任务调度检查器，负责扫描任务列表并触发到期的任务。"""
    now = time.time()
    to_trigger = []

    with _jobs_lock:
        remaining = []  # 存储需要保留的任务

        for job in _jobs:
            # 只在指定时间执行一次，类似于定时闹钟
            if job.get("type") == "once" and now >= job.get("trigger_at", 0):
                to_trigger.append(job) # 加入到待触发队列

            # 周期性运行任务，根据 cron 表达式判断是否触发
            elif job.get("type") in ("cron", "once_cron"):
                try:
                    from croniter import croniter
                    # 获取上次执行的时间，或者使用创建时间，再或者使用当前时间减去60秒
                    last_run = job.get("last_run") or job.get("created_ts", now - 60)
                    # 不能是字符串，如果是的话兜底处理为当前时间减去60秒
                    if isinstance(last_run, str):
                        last_run = now - 60

                    # 将时间戳转换为datetime对象
                    last_run_dt = datetime.fromtimestamp(last_run, CST)

                    # 创建croniter迭代器对象，指定 cron 表达式和上次执行时间作为起点
                    cron = croniter(job["cron_expr"], last_run_dt)

                    # 获取下一次应该执行的时间
                    next_dt = cron.get_next(datetime)
                    next_time = next_dt.timestamp()
                    # 判断当前时间是否已经超过了下次应该执行时间
                    if now >= next_time:
                        to_trigger.append(job) # 加入到待触发队列
                        if job["type"] == "cron":
                            job["last_run"] = now
                            remaining.append(job) # 加入到remaining列表，表示保留该任务
                        continue
                except Exception as e:
                    logger.error(f"[scheduler] cron error for {job['name']}: {e}")

                remaining.append(job)

            # 未知类型的任务直接保留
            else:
                remaining.append(job)

        # 将 _jobs 列表的内容替换为 remaining
        _jobs[:] = remaining
        if to_trigger:
            # 调用 _save_jobs() 保存任务状态到磁盘
            _save_jobs()

    for job in to_trigger:
        logger.info(f"[scheduler] triggering: {job['name']}")
        threading.Thread(target=_trigger, args=(job,), daemon=True).start()

def _log_heartbeat():
    """打印心跳日志：显示任务总数和每个cron任务的下次触发时间"""

    # 加锁保护，确保读取_jobs列表时线程安全
    with _jobs_lock:
        if not _jobs:
            return

        # 创建列表，用于存储每个cron任务的下次触发时间字符串    
        lines = []
        for job in _jobs:
            # 只处理包含cron表达式的周期性任务
            if job.get("cron_expr"):
                try:
                    from croniter import croniter
                    lr = job.get("last_run") or job.get("created_ts", time.time() - 60)
                    lr_dt = datetime.fromtimestamp(lr, CST)
                    c = croniter(job["cron_expr"], lr_dt)
                    nxt = c.get_next(datetime)
                    lines.append(f"{job['name']}->{nxt.strftime('%H:%M')}")
                except Exception:
                    lines.append(f"{job['name']}->?")
        # 打印心跳日志：任务总数 + 所有cron任务的下次触发时间
        logger.info(f"[scheduler] heartbeat: {len(_jobs)} jobs, next: {', '.join(lines)}")

def _trigger(job):
    """
    触发单个任务，并在失败时尝试做二次通知。
    参数:
    job: 一个任务字典，至少包含
    - name: 任务名（用于日志）
    - message: 触发时要发送给聊天函数的内容
    """
    if _chat_fn is None:
        logger.error("[scheduler] chat_fn is not initialized, skip trigger")
        raise RuntimeError("scheduler not initialized: chat_fn is None")
    try:

        # 1) 调用注入进来的聊天函数执行任务主体逻辑
        # session_key 固定为 scheduler，表示“调度器会话”
        # 这样会话历史会被归到同一个调度上下文里，便于追踪
        reply = _chat_fn(job["message"], "scheduler")
        logger.info(f"[scheduler] {job['name']} OK: {reply[:100] if reply else '(empty)'}")

    except Exception as e:
        logger.error(f"[scheduler] {job['name']} FAILED: {e}", exc_info=True)
        # Notify owner that task failed
        try:
            _chat_fn(
                f"Scheduled task '{job['name']}' failed with error: {e}. Please notify the owner via message tool.",
                "scheduler"
            )
        except Exception:
            pass  # Notification also failed, can only wait for next heartbeat



def _loop():
    check_count = 0
    while True:
        try:
            _check()  # 执行核心检查任务
        except Exception as e:
            logger.error(f"[scheduler] loop error: {e}", exc_info=True)
        check_count += 1

        # 每执行180次（180 * 10秒 = 1800秒 = 30分钟）记录一次心跳
        if check_count % 180 == 0:  # every 180 * 10s = 30 minutes
            _log_heartbeat()  # 记录心跳日志，证明服务还在运行


        time.sleep(10) # 休眠10秒，控制循环频率