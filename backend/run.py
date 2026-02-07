#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Registry Manager Backend Application Entry Point
应用入口文件，负责Flask应用的启动和配置
"""

import os
import sys
import time
import logging
import warnings
from flask import Flask
from backend.api import app

# 获取环境变量
DEBUG_MODE = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

# 创建logger实例
logger = logging.getLogger('registry_backend')

# 禁止Flask开发服务器警告
warnings.filterwarnings("ignore", message=".*development server.*")

def setup_logging():
    """设置应用日志配置"""
    # 使用Flask默认的日志配置，不做特殊处理
    pass

def ensure_directories():
    """确保必要的目录存在"""
    # 目录检查逻辑保持不变
    pass

def delayed_cache_clear():
    """延迟执行缓存清空操作"""
    def clear_cache_task():
        time.sleep(2)  # 延迟2秒执行
        try:
            # 确保导入缓存模块
            from backend.cache import redis_cache as mirror_cache

            logger.info("=" * 60)
            logger.info("🧹 [缓存清理] 应用重启后开始清理Redis缓存...")

            # 检查Redis连接状态
            if mirror_cache._redis_connected:
                logger.info("✓ Redis已连接，准备清理缓存")
            else:
                logger.warning("⚠️ Redis未连接，跳过缓存清理")
                logger.info("=" * 60)
                return

            # 清理Redis缓存
            try:
                # 获取当前所有缓存键
                keys = mirror_cache._redis_client.keys("registry:*")
                key_count = len(keys) if keys else 0
                logger.info(f"📊 当前缓存键数量: {key_count}")

                if keys:
                    deleted_count = mirror_cache._redis_client.delete(*keys)
                    logger.info(f"✅ Redis缓存清理完成，删除了 {deleted_count} 个缓存键")
                else:
                    logger.info("✅ Redis缓存为空，无需清理")
            except Exception as e:
                logger.error(f"❌ Redis缓存清理失败: {e}")

            logger.info("🎉 [缓存清理] 完成")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"❌ 缓存清理任务执行失败: {e}")
    
    # 在后台线程中执行缓存清空
    import threading
    cache_thread = threading.Thread(target=clear_cache_task, daemon=True)
    cache_thread.start()

def main():
    """主函数"""
    # 延迟执行缓存清空
    delayed_cache_clear()
    
    try:
        app.run(
            host='0.0.0.0',
            port=5001,
            debug=DEBUG_MODE,
            threaded=True
        )
    except KeyboardInterrupt:
        print("应用已停止")
    except Exception as e:
        print(f"应用启动失败: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()