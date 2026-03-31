
"""
消息防抖器：合并用户短时间内发送的多条消息

场景：用户连续发送 "你好" "在吗" "有个问题"
防抖后：合并为一条消息 "你好\n在吗\n有个问题" 再处理
"""
import threading
import time

from loguru import logger

import core.llm as llm
import core.message as message

_owner_ids = set()  # 允许回复消息的管理员ID列表（字符串形式）
_debounce_seconds = 0.5   # 防抖时间间隔（秒）

_buffers = {}  # 消息暂存器: sender_id -> [{"text": str, "images": [...]}]
_timers = {}   # 正在倒计时的闹钟对象
_lock = threading.Lock()  # 用于保护缓冲区和计时器的线程锁



def init(debounce_seconds=0.5, owner_ids=None):
    global _debounce_seconds, _owner_ids
    _debounce_seconds = float(debounce_seconds)
    _owner_ids = set(str(x) for x in (owner_ids or []))

def debounce_flush(sender_id):
    """计时结束，合并该用户的所有消息并触发 AI"""
    with _lock:
        fragments = _buffers.pop(sender_id, []) # 取出该用户的所有消息片段，从缓冲区删除
        _timers.pop(sender_id, None) # 删除计时器引用（计时器已触发，无需再取消）

    if not fragments: return

    texts, images = [], []
    for frag in fragments:
        if isinstance(frag, dict):
            if frag.get("text"): texts.append(frag["text"])
            images.extend(frag.get("images", []))
        else: 
            texts.append(str(frag))

        """
        fragments = [
            {"text": "你好", "images": []},
            {"text": "在吗", "images": []},
            {"text": "看看这张图", "images": [img1, img2]}
        ]

        合并后：
        texts = ["你好", "在吗", "看看这张图"]
        images = [img1, img2]
        """

    combined_text = "\n".join(texts)  # "你好\n在吗\n看看这张图"

    logger.info(f"[flush] {sender_id} -> 合并消息: {combined_text}")
    logger.info(f"[flush] 管理员id: {_owner_ids}")
    
    try:
        if str(sender_id) not in _owner_ids:
            logger.info(f"[flush] {sender_id} -> 非合法人员指令，跳过")
            message.send_text(sender_id, "抱歉，该助手目前处于私有模式。")
            return
        
        logger.info(f"[chat] {sender_id} -> 进入工具循环 (图片数: {len(images)})")
        session_key = f"dm_{sender_id}"
        logger.info(f"[chat] 请求大模型...")
        reply = llm.chat(combined_text, session_key, images=images)

        if not reply or not reply.strip(): return

        # 拆分并分段回复
        for i, chunk in enumerate(split_message(reply, 1800)):
            message.send_text(sender_id, chunk)
            if i > 0: time.sleep(0.5)

        logger.info(f"[flush] {sender_id} -> 本轮对话回复完成")

    except Exception as e:
        logger.error(f"[flush] 错误: {e}", exc_info=True)
        try: message.send_text(sender_id, f"抱歉，处理消息时出错: {e}")
        except: pass

def debounce_message(sender_id, text, images=None):
    """
    接收消息，开启/刷新防抖计时器
    
    如果用户在 debounce_seconds 内继续发送消息，
    计时器会重置，直到用户停止输入才触发处理
    """
    with _lock:
        frag = {"text": text, "images": images or []}
        _buffers.setdefault(sender_id, []).append(frag)
        
        # 重置计时器 (刷新防抖)
        if _timers.get(sender_id):  # 如果找到了正在运行的闹钟（时间还在窗口内）
            _timers[sender_id].cancel()  # 取消闹钟，否则这个闹钟响的时候就触发回复了

        # 打开一个闹钟，参数1是倒计时时间，参数2是闹钟响了之后要执行的函数，参数3是刚刚函数的参数
        timer = threading.Timer(_debounce_seconds, debounce_flush, args=[sender_id])
        timer.daemon = True  # 如果 Agent 程序突然关闭或崩溃，这些正在倒计时的闹钟会立即随之消失
        timer.start()  # 开始“滴答滴答”倒计时。
        _timers[sender_id] = timer

    logger.info(f"[debounce] {sender_id}: 已缓冲 #{len(_buffers[sender_id])}")

    

def split_message(text, max_bytes=1800):
    """
    防止单条消息超过平台长度限制，智能拆分消息

    拆分策略：
    1. 优先按行合并，保持段落完整
    2. 单行超过限制时，强制按字符截断
    3. 确保不丢失任何内容

    Args:
        text: 原始文本
        max_bytes: 每块最大字节数（默认1800，预留安全余量）

    Returns:
        list: 拆分后的文本块列表
    """
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    chunks, current = [], ""

    for line in text.split("\n"):
        line_bytes = len(line.encode("utf-8"))

        # 情况1：单行就超过限制，需要强制截断
        if line_bytes > max_bytes:
            # 先保存当前累积的内容
            if current:
                chunks.append(current)
                current = ""

            # 按字符截断长行
            start = 0
            while start < len(line):
                # 逐个字符尝试，找到不超过限制的子串
                end = start
                while end < len(line):
                    test_str = line[start:end+1]
                    if len(test_str.encode("utf-8")) > max_bytes:
                        break
                    end += 1

                # 添加截断的块
                chunk = line[start:end]
                if chunk:
                    chunks.append(chunk)
                start = end
                if start == end:  # 防止死循环
                    start += 1

        # 情况2：尝试合并到当前块
        else:
            test = current + "\n" + line if current else line
            if len(test.encode("utf-8")) > max_bytes:
                # 超过限制，保存当前块，从新行开始
                if current:
                    chunks.append(current)
                current = line
            else:
                # 未超限制，继续累积
                current = test

    # 保存最后剩余的段落
    if current:
        chunks.append(current)

    return chunks
