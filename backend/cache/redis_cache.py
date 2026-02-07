#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis Cache Service Module
Redis缓存服务模块
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import time

# 延迟导入redis，避免在没有安装时出错
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from ..config import get_mirror_file_path, get_config_dir

logger = logging.getLogger('registry_backend.redis_cache')

class BaseCache:
    """基础缓存类"""
    
    _instance = None
    _cache = None
    _cache_loaded = False
    _file_mtime = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BaseCache, cls).__new__(cls)
            cls._cache = {}
            cls._cache_loaded = False
        return cls._instance
    
    def __init__(self):
        # 确保配置目录存在
        config_dir = get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"确保配置目录存在: {config_dir}")
    
    def _ensure_file_exists(self):
        """确保Mirror.json文件存在"""
        mirror_file = get_mirror_file_path()
        if not mirror_file.exists():
            # 创建默认的Mirror.json文件
            default_data = {
                "scheme_version": "1.0",
                "description": "Docker镜像仓库描述信息",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "repositories": []
            }
            with open(mirror_file, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)
            logger.info(f"创建默认Mirror.json文件: {mirror_file}")
    
    def _get_default_info(self) -> Dict:
        """获取默认仓库信息"""
        return {
            "description": "这是一个Docker镜像仓库，包含多个版本的镜像文件。",
            "category": "unknown",
            "tags": []
        }
    
    def get_repositories(self) -> List[str]:
        """获取所有仓库名称列表"""
        try:
            mirror_file = get_mirror_file_path()
            if not mirror_file.exists():
                self._ensure_file_exists()
                return []
            
            with open(mirror_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return [repo['name'] for repo in data.get('repositories', [])]
        except Exception as e:
            logger.error(f"获取仓库列表失败: {e}")
            return []
    
    def get_repo_info(self, repository: str) -> Dict:
        """获取仓库信息"""
        try:
            mirror_file = get_mirror_file_path()
            if not mirror_file.exists():
                self._ensure_file_exists()
                return self._get_default_info()
            
            with open(mirror_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 查找对应的仓库信息
            for repo in data.get('repositories', []):
                if repo['name'] == repository:
                    return {
                        "description": repo.get('description', ''),
                        "category": repo.get('category', 'unknown'),
                        "tags": repo.get('tags', [])
                    }
            
            # 如果没找到，返回默认信息
            return self._get_default_info()
        except Exception as e:
            logger.error(f"获取仓库信息失败 {repository}: {e}")
            return self._get_default_info()
    
    def get_tags(self, repository: str) -> List[str]:
        """获取仓库的标签列表"""
        try:
            # 这里应该调用真实的registry client，暂时返回空列表
            # 实际实现应该从registry API获取标签信息
            return []
        except Exception as e:
            logger.error(f"获取标签列表失败 {repository}: {e}")
            return []
    
    def update_repo_info(self, repository: str, description: str, category: str = None, tags: List[str] = None) -> bool:
        """更新仓库信息"""
        try:
            mirror_file = get_mirror_file_path()
            if not mirror_file.exists():
                self._ensure_file_exists()
            
            # 读取现有数据
            with open(mirror_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 查找或创建仓库条目
            repo_found = False
            for repo in data.setdefault('repositories', []):
                if repo['name'] == repository:
                    repo['description'] = description
                    if category:
                        repo['category'] = category
                    if tags is not None:
                        repo['tags'] = tags
                    repo_found = True
                    break
            
            # 如果没找到，创建新条目
            if not repo_found:
                new_repo = {
                    'name': repository,
                    'description': description,
                    'category': category or 'unknown',
                    'tags': tags or []
                }
                data.setdefault('repositories', []).append(new_repo)
            
            # 写回文件
            with open(mirror_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"更新仓库信息成功: {repository}")
            return True
        except Exception as e:
            logger.error(f"更新仓库信息失败 {repository}: {e}")
            return False
    
    def clear_cache(self):
        """清空缓存（主要用于测试和调试）"""
        self._cache = {}
        self._cache_loaded = False
        self._file_mtime = None
        logger.info("Mirror.json缓存已清空")

class RedisCache(BaseCache):
    """Redis缓存服务类 - 两层缓存架构"""
    
    _instance = None
    _redis_client = None
    _redis_connected = False
    _warmup_completed = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisCache, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        super().__init__()
        self._connect_redis()
        # 移除自动预加载，改为需要时手动触发
        # if self._redis_connected:
        #     self._preload_data_to_redis()
    
    def warmup_cache(self):
        """手动触发缓存预热"""
        if self._redis_connected and not self._warmup_completed:
            self._preload_data_to_redis()
            self._warmup_completed = True
    
    def _connect_redis(self):
        """连接Redis服务器"""
        if not REDIS_AVAILABLE:
            logger.warning("Redis库未安装，将使用文件缓存")
            self._redis_connected = False
            return
            
        try:
            # 使用环境变量配置，如果没有则使用默认值127.0.0.1
            redis_host = os.getenv('REDIS_HOST', '127.0.1')  # 默认使用本地Redis
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            
            self._redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            
            # 测试连接
            self._redis_client.ping()
            self._redis_connected = True
            logger.info(f"Redis连接成功: {redis_host}:{redis_port}")
            
        except Exception as e:
            self._redis_connected = False
            logger.warning(f"Redis连接失败，将使用文件缓存: {e}")
    
    def _get_cache_key(self, key_type: str, **kwargs) -> str:
        """生成Redis缓存键"""
        if key_type == 'repos_list':
            return 'registry:repos:list'
        elif key_type == 'repo_tags':
            return f"registry:repo:{kwargs['repo_name']}:tags"
        elif key_type == 'repo_info':
            return f"registry:repo:{kwargs['repo_name']}:info"
        elif key_type == 'manifest':
            return f"registry:manifest:{kwargs['repo']}:{kwargs['tag']}"
        elif key_type == 'storage_info':
            return 'registry:storage:info'
        else:
            return f"registry:cache:{key_type}"
    
    def _get_from_redis(self, key: str) -> Optional[Any]:
        """从Redis获取数据"""
        if not self._redis_connected:
            return None
            
        try:
            data = self._redis_client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Redis读取失败 {key}: {e}")
            self._redis_connected = False
        return None
    
    def _set_to_redis(self, key: str, data: Any, ttl: int = 1800) -> bool:
        """将数据写入Redis"""
        if not self._redis_connected:
            return False
            
        try:
            serialized_data = json.dumps(data, ensure_ascii=False)
            result = self._redis_client.setex(key, ttl, serialized_data)
            return result is True
        except Exception as e:
            logger.error(f"Redis写入失败 {key}: {e}")
            self._redis_connected = False
            return False
    
    def _invalidate_cache(self, pattern: str):
        """根据模式清除缓存（支持Redis和文件缓存）"""
        cleared_count = 0
        
        # Redis缓存清理
        if self._redis_connected:
            try:
                keys = self._redis_client.keys(pattern)
                if keys:
                    deleted_count = self._redis_client.delete(*keys)
                    logger.info(f"清除Redis缓存键: {pattern} ({deleted_count}个)")
                    cleared_count += deleted_count
            except Exception as e:
                logger.error(f"清除Redis缓存失败 {pattern}: {e}")
                self._redis_connected = False
        
        # 文件缓存清理（当Redis不可用时的重要后备方案）
        try:
            if pattern == "api:repositories":
                self._clear_api_repositories_cache()
                cleared_count += 1
            elif pattern == "api:storage":
                self._clear_api_storage_cache()
                cleared_count += 1
            elif pattern.startswith("api:description:"):
                repo_name = pattern.replace("api:description:", "")
                if repo_name != "*":
                    self._clear_repo_description_cache(repo_name)
                    cleared_count += 1
                else:
                    # 处理通配符模式
                    self._clear_description_caches_by_pattern()
                    cleared_count += 1
            elif pattern.startswith("api:details:"):
                repo_name = pattern.replace("api:details:", "")
                if repo_name != "*":
                    self._clear_repo_details_cache(repo_name)
                    cleared_count += 1
                else:
                    # 处理通配符模式
                    self._clear_details_caches_by_pattern()
                    cleared_count += 1
            elif pattern == "api:registry-host":
                self._clear_registry_host_cache()
                cleared_count += 1
            elif pattern == "api:tag:*:*":
                # 处理标签缓存通配符
                self._clear_tag_caches()
                cleared_count += 1
            elif pattern == "*" or pattern == "api:*":
                # 清除所有API缓存
                cleared_count += self._clear_all_file_caches()
            
            if cleared_count > 0:
                logger.info(f"清除文件缓存: {pattern} ({cleared_count}项)")
                
        except Exception as e:
            logger.warning(f"清除文件缓存失败 {pattern}: {e}")
        
        return cleared_count
    
    def _clear_api_repositories_cache(self):
        """清除API仓库列表缓存"""
        try:
            # 清除内存中的仓库列表缓存
            if hasattr(self, '_repo_list_cache'):
                self._repo_list_cache = None
                logger.debug("已清除内存中的仓库列表缓存")
            
            # 如果有文件缓存，也清除文件
            cache_file = Path(get_config_dir()) / "repo_list_cache.json"
            if cache_file.exists():
                cache_file.unlink()
                logger.debug(f"已清除仓库列表文件缓存: {cache_file}")
                
        except Exception as e:
            logger.warning(f"清除仓库列表缓存失败: {e}")

    def _clear_api_storage_cache(self):
        """清除API存储信息缓存"""
        try:
            # 清除内存中的存储信息缓存
            if hasattr(self, '_storage_cache'):
                self._storage_cache = None
                logger.debug("已清除内存中的存储信息缓存")
                
            # 清除存储信息文件缓存
            cache_file = Path(get_config_dir()) / "storage_cache.json"
            if cache_file.exists():
                cache_file.unlink()
                logger.debug(f"已清除存储信息文件缓存: {cache_file}")
                
        except Exception as e:
            logger.warning(f"清除存储信息缓存失败: {e}")

    def _clear_repo_description_cache(self, repo_name: str):
        """清除特定仓库的描述缓存"""
        try:
            # 清除内存中的描述缓存
            if hasattr(self, '_description_cache'):
                cache_key = f"desc_{repo_name}"
                if cache_key in self._description_cache:
                    del self._description_cache[cache_key]
                    logger.debug(f"已清除内存中仓库描述缓存: {repo_name}")
            
            # 清除描述文件缓存
            desc_cache_file = Path(get_config_dir()) / f"desc_{repo_name}.json"
            if desc_cache_file.exists():
                desc_cache_file.unlink()
                logger.debug(f"已清除仓库描述文件缓存: {repo_name}")
                
        except Exception as e:
            logger.warning(f"清除仓库描述缓存失败 {repo_name}: {e}")

    def _clear_repo_details_cache(self, repo_name: str):
        """清除特定仓库的详情缓存"""
        try:
            # 清除内存中的详情缓存
            if hasattr(self, '_details_cache'):
                cache_key = f"details_{repo_name}"
                if cache_key in self._details_cache:
                    del self._details_cache[cache_key]
                    logger.debug(f"已清除内存中仓库详情缓存: {repo_name}")
            
            # 清除详情文件缓存
            details_cache_file = Path(get_config_dir()) / f"details_{repo_name}.json"
            if details_cache_file.exists():
                details_cache_file.unlink()
                logger.debug(f"已清除仓库详情文件缓存: {repo_name}")
                
        except Exception as e:
            logger.warning(f"清除仓库详情缓存失败 {repo_name}: {e}")

    def _clear_registry_host_cache(self):
        """清除registry主机信息缓存"""
        try:
            # 清除内存中的主机信息缓存
            if hasattr(self, '_host_cache'):
                self._host_cache = None
                logger.debug("已清除内存中的主机信息缓存")
                
            # 清除主机信息文件缓存
            cache_file = Path(get_config_dir()) / "host_cache.json"
            if cache_file.exists():
                cache_file.unlink()
                logger.debug(f"已清除主机信息文件缓存: {cache_file}")
                
        except Exception as e:
            logger.warning(f"清除主机信息缓存失败: {e}")

    def _clear_description_caches_by_pattern(self):
        """清除所有描述缓存（通配符处理）"""
        try:
            config_dir = Path(get_config_dir())
            desc_files = list(config_dir.glob("desc_*.json"))
            for desc_file in desc_files:
                desc_file.unlink()
                logger.debug(f"已清除描述缓存文件: {desc_file.name}")
        except Exception as e:
            logger.warning(f"清除描述缓存模式失败: {e}")

    def _clear_details_caches_by_pattern(self):
        """清除所有详情缓存（通配符处理）"""
        try:
            config_dir = Path(get_config_dir())
            details_files = list(config_dir.glob("details_*.json"))
            for details_file in details_files:
                details_file.unlink()
                logger.debug(f"已清除详情缓存文件: {details_file.name}")
        except Exception as e:
            logger.warning(f"清除详情缓存模式失败: {e}")

    def _clear_tag_caches(self):
        """清除所有标签缓存"""
        try:
            config_dir = Path(get_config_dir())
            tag_files = list(config_dir.glob("tag_*_*.json"))
            for tag_file in tag_files:
                tag_file.unlink()
                logger.debug(f"已清除标签缓存文件: {tag_file.name}")
        except Exception as e:
            logger.warning(f"清除标签缓存失败: {e}")

    def _clear_all_file_caches(self):
        """清除所有文件缓存"""
        try:
            config_dir = Path(get_config_dir())
            cache_files = list(config_dir.glob("*.json"))
            cleared_count = 0
            
            for cache_file in cache_files:
                if cache_file.name.endswith('_cache.json') or cache_file.name.startswith(('desc_', 'details_')):
                    cache_file.unlink()
                    cleared_count += 1
                    logger.debug(f"已清除文件缓存: {cache_file.name}")
            
            if cleared_count > 0:
                logger.info(f"共清除 {cleared_count} 个文件缓存")
            return cleared_count
            
        except Exception as e:
            logger.error(f"清除所有文件缓存失败: {e}")
            return 0
    
    def _preload_data_to_redis(self):
        """预加载所有数据到Redis缓存"""
        if not self._redis_connected or self._warmup_completed:
            return
            
        try:
            logger.info("开始预加载数据到Redis缓存...")
            
            # 1. 加载仓库列表
            repos = super().get_repositories()
            if repos:
                cache_key = self._get_cache_key('repos_list')
                self._set_to_redis(cache_key, repos, ttl=1800)
                logger.info(f"预加载仓库列表到Redis: {len(repos)} 个仓库")
                
                # 2. 加载每个仓库的详细信息
                for repo_name in repos:
                    repo_info = super().get_repo_info(repo_name)
                    if repo_info:
                        info_key = self._get_cache_key('repo_info', repo_name=repo_name)
                        self._set_to_redis(info_key, repo_info, ttl=1800)
                        
                        # 3. 加载标签信息（如果有）
                        tags = super().get_tags(repo_name)
                        if tags:
                            tags_key = self._get_cache_key('repo_tags', repo_name=repo_name)
                            self._set_to_redis(tags_key, tags, ttl=900)
            
            self._warmup_completed = True
            logger.info("Redis缓存预加载完成")
            
        except Exception as e:
            logger.error(f"预加载数据到Redis失败: {e}")
            self._warmup_completed = False
    
    # 重写父类方法，添加Redis缓存支持
    def get_repo_info(self, repository: str) -> Dict:
        """获取仓库信息，优先从Redis获取"""
        # 1. 先尝试从Redis获取
        cache_key = self._get_cache_key('repo_info', repo_name=repository)
        cached_data = self._get_from_redis(cache_key)
        
        if cached_data:
            logger.debug(f"从Redis缓存获取仓库信息: {repository}")
            return cached_data
        
        # 2. Redis未命中，返回空字典（不再依赖父类）
        logger.debug(f"Redis缓存未命中: {repository}")
        return {}
    
    def update_repo_info(self, repository: str, description: str, category: str = None, tags: List[str] = None) -> bool:
        """更新仓库信息，同时更新Redis和文件缓存"""
        # 1. 清除Redis中该仓库的缓存
        cache_key = self._get_cache_key('repo_info', repo_name=repository)
        if self._redis_connected:
            try:
                self._redis_client.delete(cache_key)
                logger.info(f"清除仓库缓存: {repository}")
            except Exception as e:
                logger.error(f"清除Redis缓存失败: {e}")
        
        # 2. 清除仓库列表缓存（因为可能影响列表）
        self._invalidate_cache('registry:repos:list')
        
        return True
    
    def get_repositories(self) -> List[str]:
        """获取仓库列表，使用Redis缓存"""
        # 1. 先尝试从Redis获取
        cache_key = self._get_cache_key('repos_list')
        cached_repos = self._get_from_redis(cache_key)
        
        if cached_repos:
            logger.debug("从Redis缓存获取仓库列表")
            return cached_repos
        
        # 2. Redis未命中，返回空列表
        logger.debug("Redis缓存未命中仓库列表")
        return []
    
    def get_tags(self, repository: str) -> List[str]:
        """获取仓库标签，使用Redis缓存"""
        # 1. 先尝试从Redis获取
        cache_key = self._get_cache_key('repo_tags', repo_name=repository)
        cached_tags = self._get_from_redis(cache_key)
        
        if cached_tags is not None:
            logger.debug(f"从Redis缓存获取标签: {repository}")
            return cached_tags
        
        # 2. Redis未命中，返回空列表
        logger.debug(f"Redis缓存未命中标签: {repository}")
        return []
    
    # 新增方法：缓存API调用结果
    def cache_api_result(self, api_endpoint: str, data: Any, ttl: int = 1800) -> bool:
        """缓存API调用结果到Redis"""
        if not self._redis_connected:
            return False
            
        try:
            cache_key = f"registry:api:{api_endpoint}"
            return self._set_to_redis(cache_key, data, ttl)
        except Exception as e:
            logger.error(f"缓存API结果失败 {api_endpoint}: {e}")
            return False
    
    def get_cached_api_result(self, api_endpoint: str) -> Optional[Any]:
        """从Redis获取缓存的API结果"""
        if not self._redis_connected:
            return None
            
        try:
            cache_key = f"registry:api:{api_endpoint}"
            return self._get_from_redis(cache_key)
        except Exception as e:
            logger.error(f"获取缓存API结果失败 {api_endpoint}: {e}")
            return None
    
    def clear_cache(self):
        """清空所有缓存"""
        # 1. 清空Redis缓存
        if self._redis_connected:
            try:
                keys = self._redis_client.keys('registry:*')
                if keys:
                    self._redis_client.delete(*keys)
                    logger.info(f"清空Redis缓存 ({len(keys)}个键)")
            except Exception as e:
                logger.error(f"清空Redis缓存失败: {e}")
                self._redis_connected = False
        
        # 3. 重置预加载状态
        self._warmup_completed = False

# 全局Redis缓存实例
redis_cache = RedisCache()