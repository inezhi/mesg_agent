from loguru import logger




# ============================================================
#  日志相关函数
# ============================================================

def print_start():
    logger.info("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   █████╗  ██████╗ ███████╗███╗   ██╗████████╗            ║
║  ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝            ║
║  ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║               ║
║  ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║               ║
║  ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║               ║
║  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝               ║
║                                                          ║
║                   Agent System v1.0.0                    ║
╚══════════════════════════════════════════════════════════╝
""")
    logger.info("正在读取配置......")
    from time import sleep
    sleep(0.3)

def print_config(config, title="已读取配置参数"):
    """打印配置，一行一个参数"""
    logger.info("{}:", title)
    
    def flatten(data, prefix=""):
        items = []
        if isinstance(data, dict):
            for k, v in data.items():
                new_prefix = f"{prefix}.{k}" if prefix else k
                items.extend(flatten(v, new_prefix))
        elif isinstance(data, list):
            for i, v in enumerate(data):
                items.extend(flatten(v, f"{prefix}[{i}]"))
        else:
            items.append((prefix, data))
        return items
    
    for key, value in flatten(config):
        logger.info("  {} = {}", key, value)