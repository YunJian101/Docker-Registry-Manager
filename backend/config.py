#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration Management Module
配置管理模块
"""

import os
from pathlib import Path

# 基础配置
CONFIG_DIR = "/app/config"
MIRROR_FILE_PATH = f"{CONFIG_DIR}/Mirror.json"

# Registry 配置
REGISTRY_BASE_URL = os.environ.get('REGISTRY_BASE_URL', 'http://registry:5000')
REGISTRY_HOST = os.environ.get('REGISTRY_HOST', 'localhost:5000')

# 应用配置
DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# 缓存配置
CACHE_TTL = int(os.environ.get('CACHE_TTL', '300'))  # 5分钟默认缓存时间
MAX_CACHE_SIZE = int(os.environ.get('MAX_CACHE_SIZE', '1000'))

# 文件系统配置
ALLOWED_EXTENSIONS = {'.json', '.txt', '.md'}
FILE_ENCODING = 'utf-8'

def get_config_dir() -> Path:
    """获取配置目录路径"""
    return Path(CONFIG_DIR)

def get_mirror_file_path() -> Path:
    """获取Mirror.json文件路径"""
    return Path(MIRROR_FILE_PATH)

def ensure_directories():
    """确保必要的配置目录存在（不创建data目录）"""
    # 只创建配置目录，data目录由用户或docker-compose管理
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)

def get_registry_config() -> dict:
    """获取Registry配置信息"""
    return {
        'base_url': REGISTRY_BASE_URL,
        'host': REGISTRY_HOST,
        'timeout': 30,
        'verify_ssl': False
    }
