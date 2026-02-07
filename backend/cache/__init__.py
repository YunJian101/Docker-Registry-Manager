#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cache模块初始化文件
"""

# 延迟导入Redis缓存，避免循环导入
try:
    from .redis_cache import RedisCache, redis_cache
    __all__ = ['RedisCache', 'redis_cache']
except ImportError as e:
    # 如果Redis不可用，创建一个简单的mock缓存
    class MockCache:
        def get_repo_info(self, repository):
            return {
                "name": repository,
                "description": f"这是一个Docker镜像仓库: {repository}",
                "category": "unknown",
                "tags": []
            }
        def update_repo_info(self, repository, description, category=None, tags=None):
            return True
        def get_repositories(self):
            return []
        def get_tags(self, repository):
            return []
        def clear_cache(self):
            pass
    
    redis_cache = MockCache()
    __all__ = ['redis_cache']