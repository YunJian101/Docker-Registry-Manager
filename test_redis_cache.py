#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis缓存测试脚本
用于验证Redis缓存功能是否正常工作
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_redis_cache():
    """测试Redis缓存功能"""
    print("开始测试Redis缓存...")
    print(f"REDIS_HOST环境变量: {os.getenv('REDIS_HOST', '未设置')}")
    print(f"REDIS_PORT环境变量: {os.getenv('REDIS_PORT', '未设置')}")
    
    try:
        # 导入缓存模块
        from backend.cache import redis_cache
        
        print(f"\n=== 连接状态 ===")
        print(f"Redis连接状态: {redis_cache._redis_connected}")
        print(f"缓存预加载状态: {redis_cache._warmup_completed}")
        
        if not redis_cache._redis_connected:
            print("❌ Redis连接失败，请检查:")
            print("1. Redis服务是否在 192.168.11.3:6379 运行")
            print("2. 网络连通性是否正常")
            print("3. 防火墙是否允许访问")
            return False
        
        # 测试基本功能
        print("\n=== 测试基本缓存功能 ===")
        
        # 测试API结果缓存
        test_data = {"test": "data", "timestamp": int(time.time())}
        cache_success = redis_cache.cache_api_result("test_endpoint", test_data, ttl=60)
        print(f"API结果缓存: {'✅ 成功' if cache_success else '❌ 失败'}")
        
        # 测试获取缓存结果
        cached_data = redis_cache.get_cached_api_result("test_endpoint")
        print(f"获取缓存结果: {cached_data}")
        
        # 测试仓库信息缓存
        repo_info = redis_cache.get_repo_info("test/repo")
        print(f"获取仓库信息: {repo_info}")
        
        # 测试仓库列表
        repos = redis_cache.get_repositories()
        print(f"仓库列表数量: {len(repos)}")
        if repos:
            print(f"前3个仓库: {repos[:3]}")
        
        print("\n=== 缓存状态 ===")
        print(f"Redis连接: {'✅ 是' if redis_cache._redis_connected else '❌ 否'}")
        print(f"预加载完成: {'✅ 是' if redis_cache._warmup_completed else '❌ 否'}")
        
        # 测试缓存清除
        print("\n=== 测试缓存清除 ===")
        try:
            redis_cache.clear_cache()
            print("✅ 缓存清除成功")
        except Exception as e:
            print(f"❌ 缓存清除失败: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import time
    success = test_redis_cache()
    if success:
        print("\n🎉 Redis缓存测试通过!")
    else:
        print("\n💥 Redis缓存测试失败!")
        sys.exit(1)