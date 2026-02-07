#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cache Management Module
缓存管理模块
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any  # 添加缺失的类型导入
import sys
import os

# 添加backend目录到Python路径
backend_path = '/app/backend'
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# 导入配置
try:
    from config import get_mirror_file_path, get_config_dir
except ImportError:
    # 如果相对导入失败，使用绝对路径
    def get_mirror_file_path():
        return Path("/app/config/Mirror.json")
    
    def get_config_dir():
        return Path("/app/config")

logger = logging.getLogger('registry_backend.cache')

class MirrorCache:
    """Mirror.json文件缓存管理器"""
    
    _instance = None
    _cache = None
    _cache_loaded = False
    _file_mtime = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MirrorCache, cls).__new__(cls)
            cls._cache = {}
            cls._cache_loaded = False
        return cls._instance
    
    def __init__(self):
        # 确保配置目录存在
        config_dir = get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"确保配置目录存在: {config_dir}")
    
    def _ensure_file_exists(self, registry_client=None):
        """确保Mirror.json文件存在，如果不存在则创建包含当前仓库的默认文件"""
        mirror_file = get_mirror_file_path()
        if not mirror_file.exists():
            logger.info("Mirror.json文件不存在，创建默认文件")
            
            # 先创建基础结构，确保文件能创建
            default_data = {
                "scheme_version": "1.0",
                "description": "Docker镜像仓库描述信息",
                "created_at": "2026-01-06T16:04:00Z",
                "repositories": []
            }
            
            try:
                # 确保数据目录存在
                mirror_file.parent.mkdir(parents=True, exist_ok=True)
                
                # 尝试获取当前仓库列表
                if registry_client:
                    try:
                        repos = registry_client.get_repositories()
                        if repos:
                            # 添加仓库信息到文件
                            for repo in repos:
                                default_data["repositories"].append({
                                    "name": repo,
                                    "description": f"这是一个Docker镜像仓库: {repo}",
                                    "category": "unknown",
                                    "tags": []
                                })
                            logger.info(f"成功添加 {len(repos)} 个仓库到Mirror.json")
                    except Exception as e:
                        logger.warning(f"获取仓库列表失败，创建空文件: {e}")
                
                # 写入文件
                with open(mirror_file, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, ensure_ascii=False, indent=2)
                logger.info(f"默认Mirror.json文件创建成功，包含 {len(default_data['repositories'])} 个仓库: {mirror_file}")
            except Exception as e:
                logger.error(f"创建默认Mirror.json文件失败: {e}")
    
    def _load_cache(self):
        """从文件加载数据到缓存"""
        try:
            mirror_file = get_mirror_file_path()
            
            # 检查文件是否存在，不存在则创建
            self._ensure_file_exists()
            
            # 获取文件最后修改时间
            current_mtime = mirror_file.stat().st_mtime if mirror_file.exists() else 0
            
            # 如果文件未更改且缓存已加载，直接返回
            if self._cache_loaded and self._file_mtime == current_mtime:
                return True
            
            # 从文件读取数据
            with open(mirror_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 构建内存缓存：仓库名 -> 仓库信息
            self._cache = {}
            for repo_info in data.get('repositories', []):
                repo_name = repo_info.get('name')
                if repo_name:
                    self._cache[repo_name] = repo_info
            
            # 更新状态
            self._file_mtime = current_mtime
            self._cache_loaded = True
            logger.info(f"Mirror.json缓存加载成功，共 {len(self._cache)} 个仓库信息")
            return True
            
        except Exception as e:
            logger.error(f"加载Mirror.json缓存失败: {e}")
            self._cache = {}
            self._cache_loaded = False
            return False
    
    def get_repo_info(self, repository: str) -> Dict:
        """获取仓库信息，按优先级：缓存 → 文件 → 默认值"""
        # 1. 确保缓存已加载
        if not self._load_cache():
            return self._get_default_info()
        
        # 2. 优先从缓存读取
        if repository in self._cache:
            logger.debug(f"从缓存获取仓库信息: {repository}")
            return self._cache[repository]
        
        # 3. 缓存没有，检查本地文件
        mirror_file = get_mirror_file_path()
        if mirror_file.exists():
            logger.debug(f"缓存未找到 {repository}，检查本地文件")
            
            try:
                with open(mirror_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 在文件中查找仓库信息
                for repo_info in data.get('repositories', []):
                    if repo_info.get('name') == repository:
                        logger.debug(f"从文件找到仓库: {repository}")
                        # 添加到缓存供后续使用
                        self._cache[repository] = repo_info
                        return repo_info
                
                # 4. 文件中也没有，需要添加默认值
                logger.debug(f"文件中也未找到 {repository}，添加默认信息")
                return self._add_repository_to_file_and_cache(repository, data)
                
            except Exception as e:
                logger.error(f"读取Mirror.json文件失败: {e}")
                return self._get_default_info()
        
        # 5. 文件不存在，不自动添加
        logger.debug(f"Mirror.json文件不存在，返回默认信息: {repository}")
        return self._get_default_info()
    
    def _add_repository_to_file_and_cache(self, repository: str, existing_data: Dict) -> Dict:
        """向文件和缓存中添加新的仓库默认信息"""
        default_info = {
            "name": repository,
            "description": f"这是一个Docker镜像仓库: {repository}",
            "category": "unknown",
            "tags": []
        }
        
        try:
            # 添加到数据中
            existing_data.setdefault('repositories', []).append(default_info)
            
            # 写回文件
            mirror_file = get_mirror_file_path()
            with open(mirror_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
            
            # 添加到缓存
            self._cache[repository] = default_info
            logger.info(f"新增仓库到Mirror.json: {repository}")
            
            return default_info
            
        except Exception as e:
            logger.error(f"添加新仓库到文件失败 {repository}: {e}")
            return self._get_default_info()
    
    def update_repo_info(self, repository: str, description: str, category: str = None, tags: List[str] = None) -> bool:
        """更新仓库信息，同时更新缓存和文件"""
        try:
            mirror_file = get_mirror_file_path()
            
            # 确保文件存在
            self._ensure_file_exists()
            
            # 读取现有数据或创建新数据
            if mirror_file.exists():
                with open(mirror_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {
                    "scheme_version": "1.0",
                    "description": "Docker镜像仓库描述信息",
                    "created_at": "2026-01-06T16:04:00Z",
                    "repositories": []
                }
            
            # 查找是否已存在该仓库
            repo_found = False
            for repo_info in data.get('repositories', []):
                if repo_info.get('name') == repository:
                    repo_info['description'] = description
                    if category:
                        repo_info['category'] = category
                    if tags:
                        repo_info['tags'] = tags
                    repo_found = True
                    break
            
            # 如果没找到，添加新条目
            if not repo_found:
                new_repo = {
                    "name": repository,
                    "description": description,
                    "category": category or "unknown",
                    "tags": tags or []
                }
                data['repositories'].append(new_repo)
            
            # 保存到文件
            with open(mirror_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 更新缓存
            self._cache[repository] = {
                "name": repository,
                "description": description,
                "category": category or "unknown",
                "tags": tags or []
            }
            
            # 更新文件修改时间
            self._file_mtime = mirror_file.stat().st_mtime
            self._cache_loaded = True
            
            logger.info(f"仓库信息更新成功并缓存: {repository}")
            return True
            
        except Exception as e:
            logger.error(f"更新仓库信息失败: {e}")
            return False
    
    def _get_default_info(self) -> Dict:
        """获取默认仓库信息"""
        return {
            "description": "这是一个Docker镜像仓库，包含多个版本的镜像文件。",
            "category": "unknown",
            "tags": []
        }
    
    def clear_cache(self):
        """清空缓存（主要用于测试和调试）"""
        self._cache = {}
        self._cache_loaded = False
        self._file_mtime = None
        logger.info("Mirror.json缓存已清空")

# 全局缓存实例
mirror_cache = MirrorCache()