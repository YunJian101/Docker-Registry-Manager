#!/usr/bin/env python3
"""
Docker Registry Web UI - 专业的Web管理界面
支持镜像管理、存储清理、健康监控等功能
"""

from flask import Flask, render_template, jsonify, request, send_from_directory
import requests
import os
import json
import shutil
from pathlib import Path
from typing import Dict, List, Any
from urllib.parse import unquote
import subprocess
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('registry_web')

class MirrorCache:
    """Mirror.json文件缓存管理器"""
    
    _instance = None
    _cache = None
    _file_path = "/app/config/Mirror.json"
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
        config_dir = Path("/app/config")
        config_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"确保配置目录存在: {config_dir}")
    
    def _ensure_file_exists(self):
        """确保Mirror.json文件存在，如果不存在则创建包含当前仓库的默认文件"""
        mirror_file = Path(self._file_path)
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
                logger.info(f"默认Mirror.json文件创建成功，包含 {len(default_data['repositories'])} 个仓库: {self._file_path}")
            except Exception as e:
                logger.error(f"创建默认Mirror.json文件失败: {e}")
    
    def _load_cache(self):
        """从文件加载数据到缓存"""
        try:
            mirror_file = Path(self._file_path)
            
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
        mirror_file = Path(self._file_path)
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
            mirror_file = Path(self._file_path)
            with open(mirror_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
            
            # 添加到缓存
            self._cache[repository] = default_info
            logger.info(f"新增仓库到Mirror.json: {repository}")
            
            return default_info
            
        except Exception as e:
            logger.error(f"添加新仓库到文件失败 {repository}: {e}")
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
            mirror_file = Path(self._file_path)
            with open(mirror_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
            
            # 添加到缓存
            self._cache[repository] = default_info
            logger.info(f"新增仓库到Mirror.json: {repository}")
            
            return default_info
            
        except Exception as e:
            logger.error(f"添加新仓库到文件失败 {repository}: {e}")
            return self._get_default_info()
    
    # 移除_ensure_repository_in_file方法，功能已整合到新的逻辑中

    def update_repo_info(self, repository: str, description: str, category: str = None, tags: List[str] = None) -> bool:
        """更新仓库信息，同时更新缓存和文件"""
        try:
            mirror_file = Path(self._file_path)
            
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

# 创建全局缓存实例
mirror_cache = MirrorCache()

class RegistryClient:
    def __init__(self, registry_url: str = None):
        # 优先使用环境变量，其次使用默认值
        self.registry_url = registry_url or os.getenv('REGISTRY_BASE_URL', 'http://localhost:5000')
        self.registry_url = self.registry_url.rstrip('/')
        self.base_url = f"{self.registry_url}/v2"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RegistryWebUI/1.0',
            'Accept': 'application/json'
        })
    def get_manifest(self, repository: str, tag: str) -> Dict:
        """获取manifest数据（增强版，支持多种格式）- 测试版本1"""
        try:
            # 添加明显的测试标识
            logger.info("=== OCI INDEX DEBUG VERSION 1 ===")
            return self._get_manifest(repository, tag)
        except Exception as e:
            logger.error(f"Error fetching manifest for {repository}:{tag}: {e}")
            raise

    def get_repositories(self) -> List[str]:
        """获取所有仓库（智能发现完整仓库路径）"""
        try:
            # 使用智能仓库发现：先获取顶层仓库，然后探测子仓库
            manifests_path = Path("data/manifests")
            all_repos = []
            
            # 方法1：文件系统扫描（最准确）
            if manifests_path.exists():
                logger.info("使用文件系统扫描发现仓库...")
                
                # 第一步：收集有manifest文件的仓库
                found_manifest_repos = set()
                for manifest_file in manifests_path.rglob("*"):
                    if manifest_file.is_file():
                        relative_path = manifest_file.relative_to(manifests_path)
                        # 将Windows路径分隔符\转换为标准的/
                        repository_path = str(relative_path.parent).replace('\\', '/')
                        if repository_path and repository_path != ".":
                            found_manifest_repos.add(repository_path)
                            all_repos.append(repository_path)
                
                # 第二步：检查并清理无效的仓库目录（谨慎操作）
                logger.info("检查无效仓库目录...")
                checked_dirs = set()
                
                # 只检查最顶层的目录，不递归删除，避免误删父目录
                for repo_dir in manifests_path.iterdir():
                    if repo_dir.is_dir():
                        repo_relative_path = str(repo_dir.relative_to(manifests_path))
                        if repo_relative_path not in checked_dirs:
                            checked_dirs.add(repo_relative_path)
                            
                            # 检查这个目录是否在发现的仓库列表中
                            if repo_relative_path not in found_manifest_repos:
                                # 检查目录是否为空或者包含无效文件
                                has_valid_files = False
                                has_subdirs = False
                                
                                try:
                                    for item in repo_dir.iterdir():
                                        if item.is_file():
                                            # 检查是否是一个有效的manifest文件
                                            try:
                                                with open(item, 'r', encoding='utf-8') as f:
                                                    manifest_data = json.load(f)
                                                    if 'schemaVersion' in manifest_data:  # 有效的Docker manifest
                                                        has_valid_files = True
                                                        break
                                            except:
                                                pass  # 无效的文件
                                        elif item.is_dir():
                                            has_subdirs = True  # 如果有子目录，可能是多级仓库
                                except:
                                    pass
                                
                                # 注释掉直接文件删除，改为API方式处理
                                # 在只读模式下不再直接删除文件系统
                                # 无效仓库的清理应该通过registry API完成
                                if not has_valid_files and not has_subdirs:
                                    logger.info(f"发现无效仓库目录: {repo_dir} (只读模式下不自动删除)")
                                    # 可以添加日志记录，但不执行删除操作
            
            # 方法2：API探测（备选方案）
            if not all_repos:
                logger.info("使用API探测发现仓库...")
                try:
                    response = self.session.get(f"{self.base_url}/_catalog", timeout=10)
                    response.raise_for_status()
                    top_level_repos = response.json().get('repositories', [])
                    
                    # 对于每个顶层仓库，尝试探测子仓库结构
                    for repo in top_level_repos:
                        all_repos.append(repo)
                        
                        # 尝试探测可能的子仓库
                        try:
                            tags_response = self.session.get(f"{self.base_url}/{repo}/tags/list", timeout=5)
                            if tags_response.status_code == 200:
                                tags_data = tags_response.json()
                                actual_repo_name = tags_data.get('name', repo)
                                if actual_repo_name != repo:  # 如果实际名称不同，说明有子仓库
                                    all_repos.append(actual_repo_name)
                        except:
                            pass  # 忽略探测失败
                            
                except Exception as api_error:
                    logger.error(f"API探测失败: {api_error}")
            
            # 去重并确保完整性
            final_repos = []
            seen = set()
            
            for repo in all_repos:
                if repo not in seen:
                    seen.add(repo)
                    final_repos.append(repo)
            
            logger.info(f"发现仓库列表: {final_repos}")
            return final_repos
            
        except Exception as e:
            logger.error(f"获取仓库列表失败: {e}")
            # 当出错时，总是返回空列表，除非有证据表明这是临时错误
            return []  # 空目录/不存在的目录应该返回空列表

    def get_tags(self, repository: str) -> List[str]:
        """获取仓库的所有标签"""
        try:
            # URL编码仓库名称以处理斜杠
            from urllib.parse import quote
            encoded_repo = quote(repository, safe='')
            response = self.session.get(f"{self.base_url}/{encoded_repo}/tags/list", timeout=10)
            response.raise_for_status()
            data = response.json()
            tags = data.get('tags')
            # 处理tags为null的情况，确保返回空列表
            return tags if isinstance(tags, list) else []
        except Exception as e:
            logger.error(f"获取标签列表失败 {repository}: {e}")
            return []

    def get_manifest(self, repository: str, tag: str) -> Dict:
        """获取manifest数据（增强版，支持多种格式）"""
        try:
            # 定义多种Accept头，按优先级排序
            accept_headers = [
                'application/vnd.docker.distribution.manifest.v2+json',  # Docker V2 Schema
                'application/vnd.oci.image.manifest.v1+json',            # OCI Image Manifest
                'application/vnd.oci.image.index.v1+json',               # OCI Image Index
                'application/vnd.docker.distribution.manifest.list.v2+json'  # Docker Manifest List
            ]
            
            manifest_data = None
            used_accept_header = None
            
            # 尝试每种Accept头，直到成功获取数据
            for accept_header in accept_headers:
                try:
                    response = self.session.get(
                        f"{self.base_url}/{repository}/manifests/{tag}",
                        headers={'Accept': accept_header},
                        timeout=10
                    )
                    if response.status_code == 200:
                        manifest_data = response.json()
                        used_accept_header = accept_header
                        logger.info(f"成功使用Accept头 {accept_header} 获取 {repository}:{tag} 的manifest")
                        break
                    elif response.status_code == 404:
                        # 如果是404，说明标签不存在，直接抛出异常
                        response.raise_for_status()
                except Exception as e:
                    logger.debug(f"使用Accept头 {accept_header} 获取manifest失败: {e}")
                    continue
            
            # 如果所有尝试都失败，抛出异常
            if manifest_data is None:
                raise Exception(f"无法获取 {repository}:{tag} 的manifest，所有Accept头尝试失败")
            
            # 提取实际的镜像大小和创建时间
            total_size = 0
            created = '未知'
            architecture = '未知'
            os_name = '未知'
            image_id = '未知'
            media_type = manifest_data.get('mediaType', used_accept_header or '未知')
            
            # 初始化层信息列表
            layers_info = []
            history_info = []
            diff_ids_info = []
            
            # 处理不同类型的manifest
            if media_type in ['application/vnd.docker.distribution.manifest.v2+json', 
                             'application/vnd.oci.image.manifest.v1+json']:
                # 单一镜像manifest处理
                logger.info(f"处理单一镜像manifest，layers数量: {len(manifest_data.get('layers', []))}")
                # 计算总大小（所有层的总和）
                if 'layers' in manifest_data:
                    for layer in manifest_data['layers']:
                        layer_size = layer.get('size', 0)
                        total_size += layer_size
                        # 保存详细的层信息
                        layers_info.append({
                            'digest': layer.get('digest', 'unknown'),
                            'size': layer_size,
                            'mediaType': layer.get('mediaType', 'unknown')
                        })
                
                # 从config获取创建时间和平台信息
                if 'config' in manifest_data:
                    config_digest = manifest_data['config'].get('digest', '')
                    if config_digest:
                        try:
                            # 获取config blob详细信息
                            config_response = self.session.get(
                                f"{self.base_url}/{repository}/blobs/{config_digest}",
                                timeout=10
                            )
                            if config_response.status_code == 200:
                                config_data = config_response.json()
                                created = config_data.get('created', '未知')
                                architecture = config_data.get('architecture', '未知')
                                os_name = config_data.get('os', '未知')
                                image_id = config_digest.replace('sha256:', '')[:12]  # 取前12位作为精简ID
                                
                                # 获取构建历史信息
                                if 'history' in config_data:
                                    history_info = config_data['history']
                                
                                # 获取diff_ids信息
                                if 'rootfs' in config_data and 'diff_ids' in config_data['rootfs']:
                                    diff_ids_info = config_data['rootfs']['diff_ids']
                        except Exception as e:
                            logger.warning(f"获取config失败: {e}")
                            pass  # 如果获取config失败，使用默认值
                            
            elif media_type in ['application/vnd.oci.image.index.v1+json',
                               'application/vnd.docker.distribution.manifest.list.v2+json']:
                # OCI Index或Manifest List处理
                logger.info(f"处理Index/List类型manifest，manifests数量: {len(manifest_data.get('manifests', []))}")
                if 'manifests' in manifest_data and len(manifest_data['manifests']) > 0:
                    # 优先选择有明确平台信息的manifest
                    target_manifest = None
                    for manifest_item in manifest_data['manifests']:
                        platform = manifest_item.get('platform', {})
                        arch = platform.get('architecture', 'unknown')
                        os_type = platform.get('os', 'unknown')
                        # 优先选择明确的平台信息
                        if arch != 'unknown' and os_type != 'unknown':
                            target_manifest = manifest_item
                            break
                    
                    # 如果没有找到明确平台的，就用第一个
                    if target_manifest is None:
                        target_manifest = manifest_data['manifests'][0]
                    
                    total_size = target_manifest.get('size', 0)
                    platform = target_manifest.get('platform', {})
                    architecture = platform.get('architecture', '未知')
                    os_name = platform.get('os', '未知')
                    digest = target_manifest.get('digest', '')
                    logger.info(f"选中的manifest: size={total_size}, arch={architecture}, os={os_name}, digest={digest}")
                    if digest:
                        image_id = digest.replace('sha256:', '')[:12]
                        
                    # 尝试获取具体的manifest来获得更详细信息
                    if digest:
                        try:
                            logger.info(f"尝试获取具体manifest: {digest}")
                            # 保持完整的digest（包含sha256:前缀）
                            full_digest = digest
                            
                            # 按照OCI规范，尝试获取具体的manifest
                            manifest_attempts = [
                                # OCI Image Manifest格式
                                {
                                    'url': f"{self.base_url}/{repository}/manifests/{full_digest}",
                                    'headers': {'Accept': 'application/vnd.oci.image.manifest.v1+json'}
                                },
                                # Docker V2格式（兼容性）
                                {
                                    'url': f"{self.base_url}/{repository}/manifests/{full_digest}",
                                    'headers': {'Accept': 'application/vnd.docker.distribution.manifest.v2+json'}
                                }
                            ]
                            
                            specific_manifest = None
                            for attempt in manifest_attempts:
                                try:
                                    logger.info(f"尝试获取manifest: {attempt['url']}")
                                    response = self.session.get(
                                        attempt['url'],
                                        headers=attempt['headers'],
                                        timeout=10
                                    )
                                    logger.info(f"Manifest响应状态: {response.status_code}")
                                    
                                    if response.status_code == 200:
                                        specific_manifest = response.json()
                                        logger.info(f"成功获取manifest，类型: {specific_manifest.get('mediaType', '未知')}")
                                        logger.info(f"Manifest keys: {list(specific_manifest.keys())}")
                                        break
                                    elif response.status_code == 404:
                                        logger.info(f"Manifest不存在: {attempt['url']}")
                                        continue
                                except Exception as manifest_e:
                                    logger.info(f"Manifest获取失败: {manifest_e}")
                                    continue
                            
                            if specific_manifest:
                                # 处理层数据
                                if 'layers' in specific_manifest:
                                    layer_count = len(specific_manifest['layers'])
                                    logger.info(f"Layers数量: {layer_count}")
                                    total_size = 0  # 重新计算大小
                                    for i, layer in enumerate(specific_manifest['layers']):
                                        layer_size = layer.get('size', 0)
                                        logger.info(f"Layer {i}: size={layer_size}, digest={layer.get('digest', 'unknown')}")
                                        total_size += layer_size
                                        # 保存详细的层信息
                                        layers_info.append({
                                            'digest': layer.get('digest', 'unknown'),
                                            'size': layer_size,
                                            'mediaType': layer.get('mediaType', 'unknown')
                                        })
                                    logger.info(f"计算得到的总大小: {total_size}")
                                
                                # 获取配置数据（按照OCI规范）
                                if 'config' in specific_manifest:
                                    config_digest = specific_manifest['config'].get('digest', '')
                                    logger.info(f"Config digest: {config_digest}")
                                    if config_digest:
                                        # 按照OCI规范获取config blob
                                        config_url = f"{self.base_url}/{repository}/blobs/{config_digest}"
                                        logger.info(f"获取config: {config_url}")
                                        
                                        try:
                                            config_response = self.session.get(config_url, timeout=10)
                                            logger.info(f"Config响应状态: {config_response.status_code}")
                                            
                                            if config_response.status_code == 200:
                                                config_data = config_response.json()
                                                logger.info(f"Config数据keys: {list(config_data.keys())}")
                                                
                                                # 更新创建时间和平台信息
                                                created = config_data.get('created', created)
                                                architecture = config_data.get('architecture', architecture)
                                                os_name = config_data.get('os', os_name)
                                                image_id = config_digest.replace('sha256:', '')[:12]
                                                
                                                # 获取构建历史信息
                                                if 'history' in config_data:
                                                    history_info = config_data['history']
                                                
                                                # 获取diff_ids信息
                                                if 'rootfs' in config_data and 'diff_ids' in config_data['rootfs']:
                                                    diff_ids_info = config_data['rootfs']['diff_ids']
                                                
                                                logger.info(f"从config提取: created={created}, arch={architecture}, os={os_name}")
                                            else:
                                                logger.info(f"Config获取失败，状态码: {config_response.status_code}")
                                        except Exception as config_e:
                                            logger.info(f"Config获取异常: {config_e}")
                            else:
                                logger.info("无法获取具体的manifest，使用Index提供的基本信息")
                        except Exception as e:
                            logger.info(f"处理具体manifest时出错: {e}")
            
            # 构建返回数据，确保包含所有必要的信息
            result = {
                'total_size': total_size,
                'size': total_size,  # 兼容性字段
                'created': created,
                'architecture': architecture,
                'os': os_name,
                'image_id': image_id,
                'mediaType': media_type,
                'schemaVersion': manifest_data.get('schemaVersion', '未知'),
                'layers': layers_info,  # 确保返回详细的层信息
                'history': history_info,  # 返回构建历史
                'diff_ids': diff_ids_info,  # 返回diff_ids
                'config': manifest_data.get('config', {})  # 返回原始config信息
            }
            
            logger.info(f"返回结果 - 总大小: {total_size}, 层数: {len(layers_info)}, 历史数: {len(history_info)}")
            return result
            
        except Exception as e:
            logger.error(f"获取manifest失败 {repository}:{tag}: {e}")
            # 返回基本的错误信息结构
            return {
                'total_size': 0,
                'size': 0,
                'created': '未知',
                'architecture': '未知',
                'os': '未知',
                'image_id': '未知',
                'mediaType': '未知',
                'schemaVersion': '未知',
                'layers': [],
                'history': [],
                'diff_ids': [],
                'config': {},
                'error': str(e)
            }

    def delete_image(self, repository: str, tag: str) -> bool:
        """删除镜像 - 支持OCI镜像格式"""
        try:
            # 首先获取manifest以确定正确的mediaType
            manifest_info = self.get_manifest(repository, tag)
            media_type = manifest_info.get('mediaType', '')
            
            # 根据mediaType确定正确的Accept头
            accept_header_map = {
                'application/vnd.oci.image.index.v1+json': 'application/vnd.oci.image.index.v1+json',
                'application/vnd.oci.image.manifest.v1+json': 'application/vnd.oci.image.manifest.v1+json',
                'application/vnd.docker.distribution.manifest.v2+json': 'application/vnd.docker.distribution.manifest.v2+json',
                'application/vnd.docker.distribution.manifest.list.v2+json': 'application/vnd.docker.distribution.manifest.list.v2+json'
            }
            
            # 默认使用Docker V2 Schema
            accept_header = accept_header_map.get(media_type, 'application/vnd.docker.distribution.manifest.v2+json')
            
            logger.info(f"删除镜像 {repository}:{tag}, 使用Accept头: {accept_header}, mediaType: {media_type}")
            
            # 先获取manifest digest
            response = self.session.head(
                f"{self.base_url}/{repository}/manifests/{tag}",
                headers={'Accept': accept_header},
                timeout=10
            )
            
            # 检查响应状态码
            if response.status_code != 200:
                logger.error(f"获取manifest失败，状态码: {response.status_code}")
                return False
                
            digest = response.headers.get('Docker-Content-Digest', '')
            if not digest:
                logger.error(f"无法获取Docker-Content-Digest头部")
                return False
            
            logger.info(f"获取到digest: {digest}")
            
            # 使用digest删除
            delete_response = self.session.delete(
                f"{self.base_url}/{repository}/manifests/{digest}",
                timeout=10
            )
            
            success = delete_response.status_code in [202, 404]
            logger.info(f"删除操作结果: 状态码={delete_response.status_code}, 成功={success}")
            
            return success
            
        except Exception as e:
            logger.error(f"删除镜像失败 {repository}:{tag}: {e}")
            return False

    def get_storage_info(self) -> Dict:
        """获取存储信息"""
        try:
            response = self.session.get(f"{self.registry_url}/health", timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return {}

# 废弃的旧方法，功能由 MirrorCache 类接管
# get_repo_description 和 update_repo_description 已被移除

@app.route('/api/repository/<path:repository>/description')
def api_repository_description(repository: str):
    """API: 获取仓库的描述信息（使用缓存）"""
    try:
        repository = unquote(repository)
        # 使用缓存类获取仓库信息
        description_data = mirror_cache.get_repo_info(repository)
        return jsonify({'success': True, 'data': description_data})
    except Exception as e:
        logger.error(f"获取仓库描述失败 {repository}: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/repository/<path:repository>/description', methods=['POST'])
def api_update_repository_description(repository: str):
    """API: 更新仓库的描述信息（使用缓存）"""
    try:
        repository = unquote(repository)
        data = request.get_json()
        
        description = data.get('description')
        category = data.get('category')
        tags = data.get('tags')
        
        # 使用缓存类的update方法
        success = mirror_cache.update_repo_info(repository, description, category, tags)
        
        if success:
            return jsonify({'success': True, 'message': '描述信息更新成功'})
        else:
            return jsonify({'success': False, 'error': '更新失败'})
    
    except Exception as e:
        logger.error(f"更新仓库描述失败 {repository}: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/mirror/cache/clear', methods=['POST'])
def api_clear_mirror_cache():
    """API: 手动清空Mirror.json缓存"""
    try:
        mirror_cache.clear_cache()
        return jsonify({'success': True, 'message': 'Mirror.json缓存已清空'})
    except Exception as e:
        logger.error(f"清空Mirror.json缓存失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/mirror/cache/status')
def api_mirror_cache_status():
    """API: 获取Mirror.json缓存状态"""
    try:
        status = {
            'cache_loaded': mirror_cache._cache_loaded,
            'cache_size': len(mirror_cache._cache),
            'file_mtime': mirror_cache._file_mtime,
            'file_exists': Path(mirror_cache._file_path).exists()
        }
        return jsonify({'success': True, 'data': status})
    except Exception as e:
        logger.error(f"获取Mirror.json缓存状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

# 创建Registry客户端
registry_client = RegistryClient()

@app.route('/')
def index():
    """主页面"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>Docker Registry Web UI</title>
    <style>
        /* Docker命令容器基础样式 */
        .docker-command-line {
            cursor: pointer;
            padding: 0.85rem 1.2rem;
            margin: 0.8rem 0;  /* 增加垂直间距 */
            border-radius: 8px;
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border: 1px solid #dee2e6;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 0.8rem;  /* 增加内部元素间距 */
            min-height: 50px;  /* 设置最小高度确保一致性 */
            position: relative;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        
        /* Docker命令悬停效果 */
        .docker-command-line:hover {
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%) !important;
            border-color: #42a5f5 !important;
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 16px rgba(66, 165, 245, 0.2) !important;
            cursor: pointer !important;
        }
        
        .command-prefix {
            color: #28a745;
            font-weight: bold;
            font-size: 1rem;
            font-family: 'Courier New', monospace;
            min-width: 12px;  /* 确保$符号宽度固定 */
            text-align: center;
        }
        
        .command-text {
            flex: 1;
            font-family: 'Fira Code', 'Courier New', monospace;
            color: #2c3e50;
            font-size: 0.95rem;
            padding: 0.2rem 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            display: flex;
            align-items: center;
            line-height: 1.4;
        }
        
        .copy-indicator {
            color: #6c757d;
            font-size: 1.1rem;
            transition: all 0.3s ease;
            padding: 0.4rem;
            border-radius: 6px;
            background: rgba(255,255,255,0.7);
            min-width: 32px;
            text-align: center;
        }
        
        .docker-command-line:hover .copy-indicator {
            background: rgba(102, 126, 234, 0.15) !important;
            color: #4a68c7 !important;
            transform: scale(1.1) !important;
            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.2);
        }
    </style>
    <script>
        // ✅ 预先定义复制函数，确保在任何地方都可使用（加强版）
        function copyToClipboard(text) {
            // 优先使用现代 Clipboard API
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(function() {
                    console.log('✅ 使用Clipboard API复制成功:', text);
                    showToast('✅ Docker命令已复制到剪贴板');
                    return true;
                }).catch(function(err) {
                    console.log('❌ Clipboard API失败，回退到execCommand:', err);
                    useExecCommand(text);
                });
            } else {
                // 回退到execCommand
                useExecCommand(text);
            }
            
            function useExecCommand(commandText) {
                // 创建临时textarea元素
                const textarea = document.createElement('textarea');
                textarea.value = commandText;
                textarea.style.position = 'fixed';
                textarea.style.left = '-999999px';
                textarea.style.top = '-999999px';
                document.body.appendChild(textarea);
                
                // 选择和复制文本
                textarea.select();
                textarea.setSelectionRange(0, 99999); // 对于移动设备
                
                try {
                    const successful = document.execCommand('copy');
                    if (successful) {
                        console.log('✅ 使用execCommand复制成功:', commandText);
                        showToast('✅ Docker命令已复制到剪贴板');
                    } else {
                        console.log('❌ execCommand复制失败，请手动复制');
                        showToast('❌ 复制失败，请手动选择并复制');
                    }
                } catch (err) {
                    console.log('❌ execCommand异常:', err);
                    showToast('❌ 复制功能不可用，请手动复制');
                } finally {
                    // 清理临时元素
                    document.body.removeChild(textarea);
                }
            }
            
            // 阻止默认事件冒泡
            if (event) {
                event.stopPropagation();
                event.preventDefault();
            }
        }
    </script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; }
        
        /* 全局文本溢出防护 */
        .info-value, .tag-name, .repo-name, .layer-digest, 
        .env-list, .stat-value, .stat-label, .tag-details,
        .info-label, .tag-header, .repo-header {
            word-break: break-word;
            overflow-wrap: break-word;
            max-width: 100%;
        }
        
        /* 可滚动区域 */
        .scrollable {
            max-height: 200px;
            overflow-y: auto;
            padding: 0.5rem;
        }
        
        /* 长文本自动换行 */
        .long-text {
            white-space: pre-wrap;
            word-break: break-all;
        }
        
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 2rem; text-align: center; }
        .header h1 { font-size: 2.5rem; margin-bottom: 0.5rem; }
        .header p { opacity: 0.9; font-size: 1.1rem; }
        
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        
        .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 2rem; margin-bottom: 2rem; }
        .card { background: white; border-radius: 12px; padding: 1.5rem; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
        .card h3 { color: #667eea; margin-bottom: 1rem; font-size: 1.3rem; }
        .stat { font-size: 2rem; font-weight: bold; color: #764ba2; }
        .stat-label { color: #666; font-size: 0.9rem; }
        
        .repositories-section { background: white; border-radius: 12px; padding: 2rem; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
        .repo-item { border: 1px solid #e0e0e0; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
        .repo-header { display: flex; justify-content: between; align-items: center; margin-bottom: 0.5rem; }
        .repo-name { font-weight: bold; color: #333; font-size: 1.2rem; }
        .repo-tags { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }
        .tag { background: #f0f0f0; padding: 0.3rem 0.8rem; border-radius: 4px; font-size: 0.9rem; display: flex; align-items: center; gap: 0.5rem; }
        
        .btn { padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-weight: 500; transition: all 0.3s; }
        .btn-danger { 
            background: #e74c3c; 
            color: white; 
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 2px 6px rgba(231, 76, 60, 0.3);
        }
        .btn-danger:hover { 
            background: #c0392b;
            transform: translateY(-2px) scale(1.05);
            box-shadow: 0 4px 12px rgba(192, 57, 43, 0.4);
        }
        .btn-primary { 
            background: linear-gradient(135deg, #3498db 0%, #2c81ba 100%);
            color: white;
            border: none;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 2px 8px rgba(52, 152, 219, 0.3);
        }
        .btn-primary:hover { 
            background: linear-gradient(135deg, #2980b9 0%, #2472a4 100%);
            transform: translateY(-2px) scale(1.05);
            box-shadow: 0 4px 12px rgba(41, 128, 185, 0.4);
        }
        .btn-secondary { 
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            border: none;
            box-shadow: 0 2px 8px rgba(74, 144, 226, 0.3);
            transition: all 0.3s ease;
        }
        .btn-secondary:hover { 
            background: linear-gradient(135deg, #3b89d1 0%, #00c9e6 100%);
            box-shadow: 0 4px 12px rgba(74, 144, 226, 0.4);
            transform: translateY(-1px);
        }
        .btn-secondary:disabled {
            background: linear-gradient(135deg, #cccccc 0%, #aaaaaa 100%);
            box-shadow: none;
            transform: none;
            cursor: not-allowed;
        }
        .btn-small { padding: 0.3rem 0.6rem; font-size: 0.8rem; }
        
        .loading { text-align: center; padding: 2rem; color: #666; }
        .error { background: #f8d7da; color: #721c24; padding: 1rem; border-radius: 6px; margin: 1rem 0; }
        
        .action-bar { display: flex; gap: 1rem; margin-bottom: 1rem; }
        
        /* 卡片式布局样式 */
        .repos-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 1.5rem;
            margin-top: 1rem;
        }
        
        .repo-card {
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            border: 1px solid #e0e0e0;
            transition: all 0.3s ease;
            display: flex;
            flex-direction: column;
            min-height: 280px;
        }
        
        .repo-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
        }
        
        .repo-card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1rem;
            border-bottom: 1px solid #f0f0f0;
            padding-bottom: 1rem;
        }
        
        .repo-name-container {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex: 1;
            min-width: 0;
        }
        
        .repo-icon {
            font-size: 1.5rem;
            flex-shrink: 0;
        }
        
        .repo-name {
            font-weight: 600;
            font-size: 1.1rem;
            color: #2c3e50;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .repo-actions {
            flex-shrink: 0;
        }
        
        .repo-stats {
            display: flex;
            gap: 1rem;
            margin-bottom: 1rem;
            justify-content: space-around;
        }
        
        .stat-item {
            text-align: center;
            padding: 0.5rem;
            background: #f8f9fa;
            border-radius: 8px;
            flex: 1;
        }
        
        .stat-number {
            display: block;
            font-size: 1.3rem;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            display: block;
            font-size: 0.8rem;
            color: #666;
            margin-top: 0.2rem;
        }
        
        .tags-section {
            flex: 1;
            margin-bottom: 1rem;
        }
        
        .tags-title {
            font-size: 0.9rem;
            color: #666;
            margin-bottom: 0.5rem;
            font-weight: 500;
        }
        
        .tags-container {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
        }
        
        .tag-item {
            background: #e3f2fd;
            border: 1px solid #bbdefb;
            border-radius: 6px;
            padding: 0.3rem 0.6rem;
            font-size: 0.8rem;
            display: flex;
            align-items: center;
            gap: 0.3rem;
            transition: all 0.2s;
        }
        
        .tag-item:hover {
            background: #bbdefb;
        }
        
        .tag-name {
            color: #1565c0;
            font-weight: 500;
        }
        
        .tag-delete {
            background: none;
            border: none;
            color: #f44336;
            cursor: pointer;
            padding: 0.1rem 0.3rem;
            border-radius: 3px;
            font-size: 0.9rem;
            transition: background 0.2s;
        }
        
        .tag-delete:hover {
            background: #ffcdd2;
        }
        
        .more-tags {
            background: #f5f5f5;
            border: 1px dashed #ddd;
            border-radius: 6px;
            padding: 0.3rem 0.6rem;
            font-size: 0.8rem;
            color: #666;
            cursor: pointer;
        }
        
        .more-tags:hover {
            background: #e0e0e0;
        }
        
        .empty-state {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2rem;
            color: #999;
        }
        
        .empty-icon {
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }
        
        .empty-text {
            font-size: 0.9rem;
        }
        
        /* 详情页样式 */
        .repository-detail {
            background: white;
            border-radius: 12px;
            padding: 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .detail-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid #eee;
        }
        
        .detail-header h2 {
            color: #2c3e50;
            font-size: 1.5rem;
        }
        
        .detail-stats {
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        .detail-description {
            margin-bottom: 1.5rem;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            padding: 1.5rem;
        }
        
        .detail-description h3 {
            color: #2c3e50;
            border-bottom: 2px solid #667eea;
            padding-bottom: 0.75rem;
            margin-bottom: 1.25rem;
            font-size: 1.2rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .detail-tags h3 {
            color: #2c3e50;
            margin-bottom: 1rem;
        }
        
        .tag-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 1rem;
        }
        
        .tag-card {
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 12px;
            padding: 1.2rem;
            box-shadow: 0 3px 8px rgba(0, 0, 0, 0.08);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
            position: relative;
            overflow: hidden;
        }
        
        .tag-card:hover {
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            border-color: #42a5f5;
            transform: translateY(-4px) scale(1.02);
            box-shadow: 0 8px 25px rgba(66, 165, 245, 0.25);
        }
        
        .tag-card:hover::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(135deg, #42a5f5 0%, #1e88e5 100%);
        }
        
        .tag-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #f0f0f0;
        }
        
        .tag-name {
            font-weight: 600;
            color: #2c3e50;
        }
        
        .tag-details div {
            margin-bottom: 0.3rem;
            font-size: 0.9rem;
        }
        
        .tag-details strong {
            color: #666;
            min-width: 80px;
            display: inline-block;
        }
        
        /* 标签详情页样式 */
        .tag-detail-page {
            background: white;
            border-radius: 12px;
            padding: 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .tag-detail-header {
            display: flex;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid #eee;
        }
        
        .tag-detail-header h2 {
            color: #2c3e50;
            font-size: 1.5rem;
            margin: 0;
            flex: 1;
        }
        
        .tag-detail-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        
        .stat-card {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 1rem;
            text-align: center;
            border: 1px solid #e9ecef;
        }
        
        .stat-value {
            font-size: 1.3rem;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 0.5rem;
        }
        
        .stat-label {
            color: #666;
            font-size: 0.9rem;
        }
        
        .tag-detail-info {
            margin-bottom: 2rem;
        }
        
        .info-section {
            margin-bottom: 2rem;
        }
        
        .info-section h3 {
            color: #2c3e50;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #f0f0f0;
        }
        
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1rem;
        }
        
        .info-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.8rem;
            background: #f8f9fa;
            border-radius: 6px;
            border-left: 4px solid #667eea;
        }
        
        .info-label {
            font-weight: 600;
            color: #2c3e50;
        }
        
        .info-value {
            color: #495057;
            font-family: 'Courier New', monospace;
            font-size: 0.9rem;
        }
        
        .layers-list {
            max-height: 300px;
            overflow-y: auto;
            border: 1px solid #e9ecef;
            border-radius: 6px;
        }
        
        .layer-item {
            padding: 0.8rem;
            border-bottom: 1px solid #f0f0f0;
        }
        
        .layer-item:last-child {
            border-bottom: none;
        }
        
        .layer-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.3rem;
        }
        
        .layer-index {
            background: #667eea;
            color: white;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8rem;
        }
        
        .layer-digest {
            font-family: 'Courier New', monospace;
            font-size: 0.8rem;
            color: #666;
            flex: 1;
            margin: 0 1rem;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .layer-size {
            color: #28a745;
            font-weight: 500;
        }
        
        .layer-media-type {
            font-size: 0.8rem;
            color: #999;
        }
        
        .tag-actions {
            display: flex;
            gap: 1rem;
            justify-content: center;
            padding-top: 2rem;
            border-top: 1px solid #eee;
        }
        
        .no-data {
            text-align: center;
            color: #999;
            padding: 2rem;
            font-style: italic;
        }
        
        /* 手机端响应式设计 */
        @media (max-width: 768px) {
            .container {
                padding: 0.8rem;
                overflow-x: hidden;
                width: 100%;
            }
            
            .dashboard {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 0.6rem;
                margin-bottom: 1rem;
                width: 100%;
            }
            
            /* 存储统计和仓库状态占用前两列，快速操作占整行 */
            .dashboard .card:nth-child(1) { 
                grid-column: 1; 
            }
            .dashboard .card:nth-child(2) { 
                grid-column: 2; 
            }
            .dashboard .card:nth-child(3) { 
                grid-column: 1 / -1;
                margin-top: 0.6rem;
            }
            
            .dashboard .card {
                padding: 0.7rem;
                min-height: 100px;
                margin-bottom: 0;
                display: flex;
                flex-direction: column;
                width: 100%;
                box-sizing: border-box;
                word-wrap: break-word;
            }
            
            .dashboard .card h3 {
                font-size: 0.9rem;
                margin-bottom: 0.4rem;
                word-break: break-word;
            }
            
            .dashboard .stat {
                font-size: 1rem;
                margin-bottom: 0.2rem;
                word-break: break-word;
            }
            
            /* 操作按钮缩小以适应小屏幕 */
            .dashboard .card:nth-child(3) .btn {
                padding: 0.5rem 0.8rem;
                font-size: 0.8rem;
            }
            
            .repos-grid {
                grid-template-columns: 1fr;
                gap: 1rem;
            }
            
            .repo-card {
                margin-bottom: 0.5rem;
                padding: 1rem;
                min-height: auto;
            }
            
            .repo-card-header {
                flex-direction: column;
                align-items: flex-start;
                margin-bottom: 0.5rem;
            }
            
            .repo-name-container {
                margin-bottom: 0.5rem;
            }
            
            .repo-name {
                font-size: 1rem;
                word-break: break-word;
                white-space: normal;
                line-height: 1.3;
            }
            
            .repo-stats {
                flex-direction: column;
                gap: 0.5rem;
                margin-bottom: 0.5rem;
            }
            
            .stat-item {
                padding: 0.3rem;
            }
            
            .stat-number {
                font-size: 1.1rem;
            }
            
            .tags-container {
                gap: 0.2rem;
            }
            
            .tag-item {
                padding: 0.2rem 0.4rem;
                font-size: 0.75rem;
            }
            
            /* 标签详情页适配 */
            .tag-detail-page {
                padding: 1rem;
            }
            
            .tag-detail-header {
                flex-direction: column;
                text-align: center;
                margin-bottom: 1rem;
            }
            
            .tag-detail-header h2 {
                font-size: 1.3rem;
                margin: 0.5rem 0;
                word-break: break-word;
            }
            
            .tag-detail-stats {
                grid-template-columns: 1fr;
                gap: 0.5rem;
                margin-bottom: 1rem;
            }
            
            .stat-card {
                padding: 0.5rem;
            }
            
            .stat-value {
                font-size: 1.1rem;
            }
            
            .info-grid {
                grid-template-columns: 1fr;
                gap: 0.5rem;
            }
            
            .config-section {
                margin-bottom: 0.5rem;
            }
            
            .info-item {
                padding: 0.5rem;
                margin-bottom: 0.3rem;
                flex-direction: column;
                align-items: flex-start;
            }
            
            .info-label {
                font-size: 0.9rem;
                margin-bottom: 0.2rem;
            }
            
            .info-value {
                font-size: 0.85rem;
                line-height: 1.3;
                word-break: break-all;
            }
            
            .tag-actions {
                flex-direction: column;
                gap: 0.5rem;
                padding-top: 1rem;
            }
            
            .btn {
                padding: 0.8rem 1rem;
                font-size: 0.9rem;
            }
            
            .layers-list {
                max-height: 200px;
            }
            
            .layer-header {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .layer-digest {
                margin: 0.3rem 0;
                font-size: 0.7rem;
            }
        }

        /* 小屏幕手机适配 */
        @media (max-width: 480px) {
            .header {
                padding: 1rem;
            }
            
            .header h1 {
                font-size: 1.5rem;
            }
            
            .header p {
                font-size: 0.9rem;
            }
            
            .container {
                padding: 0.5rem;
            }
            
            .card {
                padding: 1rem;
            }
            
            .repository-detail, 
            .repositories-section {
                padding: 1rem;
            }
            
            .tag-detail-stats {
                grid-template-columns: 1fr;
            }
            
            .info-grid {
                grid-template-columns: 1fr;
            }
        }
        
        /* 防止移动端viewport缩放 */
        @media (max-width: 768px) {
            body {
                -webkit-text-size-adjust: 100%;
                -moz-text-size-adjust: 100%;
                text-size-adjust: 100%;
                overflow-x: hidden;
            }
        }
    </style>
</head>
<body>
    <div class="header" onclick="backToHome()" style="cursor: pointer;">
        <h1>🐳 Docker Registry Manager</h1>
        <p>专业的私有Docker镜像仓库管理界面</p>
    </div>
    
    <div class="container">
        <!-- 仪表板 -->
        <div class="dashboard">
            <div class="card">
                <h3>📊 存储统计</h3>
                <div id="storage-stats">
                    <div class="loading">加载中...</div>
                </div>
            </div>
            
            <div class="card">
                <h3>🏗️ 仓库状态</h3>
                <div id="repo-stats">
                    <div class="loading">加载中...</div>
                </div>
            </div>
            
            <div class="card">
                <h3>⚡ 快速操作</h3>
                <div style="display: flex; flex-direction: column; gap: 0.5rem;">
                    <button class="btn btn-primary" onclick="loadData()">🔄 刷新数据</button>
                    <button class="btn btn-primary" onclick="restartRegistry()">🔄 重启后端</button>
                    <button class="btn btn-primary" onclick="healthCheck()">❤️ 健康检查</button>
                </div>
            </div>
        </div>
        
        <!-- 仓库列表 -->
        <div class="repositories-section">
            <div class="action-bar">
                <h3 style="flex: 1;">📦 镜像仓库</h3>
                <button class="btn btn-primary" onclick="loadRepositories()">刷新列表</button>
            </div>
            
            <div id="repositories-list">
                <div class="loading">正在加载仓库列表...</div>
            </div>
            
            <!-- 分页控件 -->
            <div id="pagination-controls" style="display: none; margin-top: 2rem; text-align: center;">
                <div style="display: flex; justify-content: center; align-items: center; gap: 1rem;">
                    <button id="prev-page" class="btn btn-secondary" onclick="prevPage()" disabled>← 上一页</button>
                    <span id="page-info" style="color: #666; font-weight: 500;">第 <span id="current-page">1</span> 页，共 <span id="total-pages">0</span> 页</span>
                    <button id="next-page" class="btn btn-secondary" onclick="nextPage()" disabled>→ 下一页</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        // API基础URL
        const API_BASE = '/api';
        
        // 分页相关变量
        let currentPage = 1;
        const repositoriesPerPage = 6;
        let allRepositories = [];
        
        // 加载所有数据
        async function loadData() {
            await loadStorageStats();
            await loadRepoStats();
            await loadRepositories();
        }
        // 加载存储统计
        async function loadStorageStats() {
            try {
                const storageStatsElem = document.getElementById('storage-stats');
                if (!storageStatsElem) {
                    console.warn('storage-stats 元素未找到');
                    return;
                }
                
                const response = await fetch(`${API_BASE}/storage`);
                const data = await response.json();
                
                if (data.success) {
                    const stats = data.data;
                    storageStatsElem.innerHTML = `
                        <div class="stat">${stats.total_size_gb || 0} GB</div>
                        <div class="stat-label">总存储大小</div>
                        <div style="margin-top: 0.5rem;">
                            <div>使用率: ${stats.used_percentage || 0}%</div>
                            <div>可用空间: ${stats.available_gb || 0} GB</div>
                        </div>
                    `;
                }
            } catch (error) {
                const storageStatsElem = document.getElementById('storage-stats');
                if (storageStatsElem) {
                    storageStatsElem.innerHTML = '<div class="error">加载失败</div>';
                }
            }
        }
        
        // 加载仓库统计
        async function loadRepoStats() {
            try {
                const repoStatsElem = document.getElementById('repo-stats');
                if (!repoStatsElem) {
                    console.warn('repo-stats 元素未找到');
                    return;
                }
                
                const response = await fetch(`${API_BASE}/repositories`);
                const data = await response.json();
                
                if (data.repositories) {
                    const totalRepos = data.repositories.length;
                    const totalTags = data.repositories.reduce((sum, repo) => sum + repo.tag_count, 0);
                    
                    // 显示总共多少个仓库（不随分页改变）
                    repoStatsElem.innerHTML = `
                        <div class="stat">${totalRepos}</div>
                        <div class="stat-label">总仓库数</div>
                        <div style="margin-top: 0.5rem;">
                            <div>总标签数: ${totalTags}</div>
                            ${totalRepos > repositoriesPerPage ? `<div>共 ${Math.ceil(totalRepos / repositoriesPerPage)} 页</div>` : ''}
                        </div>
                    `;
                }
            } catch (error) {
                const repoStatsElem = document.getElementById('repo-stats');
                if (repoStatsElem) {
                    repoStatsElem.innerHTML = '<div class="error">加载失败</div>';
                }
            }
        }
        
        // 分页状态更新
        function updatePagination(current, total) {
            console.log(`更新分页: 第 ${current} 页，共 ${total} 页`);
            
            // 安全检查：确保元素存在
            const currentPageElem = document.getElementById('current-page');
            const totalPagesElem = document.getElementById('total-pages');
            const paginationControls = document.getElementById('pagination-controls');
            
            if (currentPageElem) currentPageElem.textContent = current;
            if (totalPagesElem) totalPagesElem.textContent = total;
            if (paginationControls) {
                paginationControls.style.display = total > 1 ? 'block' : 'none';
            }
            
            const prevBtn = document.getElementById('prev-page');
            const nextBtn = document.getElementById('next-page');
            
            if (prevBtn) prevBtn.disabled = current <= 1;
            if (nextBtn) nextBtn.disabled = current >= total;
        }
        
        // 上一页
        function prevPage() {
            if (currentPage > 1) {
                currentPage--;
                renderRepositoriesPage();
            }
        }
        
        // 下一页
        function nextPage() {
            const totalPages = Math.ceil(allRepositories.length / repositoriesPerPage);
            if (currentPage < totalPages) {
                currentPage++;
                renderRepositoriesPage();
            }
        }
        
        // 渲染当前页的仓库
        function renderRepositoriesPage() {
            if (allRepositories.length === 0) {
                document.getElementById('repositories-list').innerHTML = '<div class="loading">正在加载仓库列表...</div>';
                return;
            }
            
            const startIndex = (currentPage - 1) * repositoriesPerPage;
            const endIndex = Math.min(startIndex + repositoriesPerPage, allRepositories.length);
            const pageRepositories = allRepositories.slice(startIndex, endIndex);
            
            const html = `
                <div class="repos-grid">
                    ${pageRepositories.map(repo => `
                        <div class="repo-card">
                            <div class="repo-card-header">
                                <div class="repo-name-container">
                                <span class="repo-icon">📦</span>
                                <span class="repo-name" title="${repo.name}">${repo.name}</span>
                                </div>
                            </div>
                            
                            <div class="repo-stats">
                                <div class="stat-item">
                                    <span class="stat-number">${repo.tag_count}</span>
                                    <span class="stat-label">标签数</span>
                                </div>
                            </div>
                            
                            ${repo.tags && repo.tags.length > 0 ? `
                                <div class="tags-section">
                                    <div class="tags-title">镜像标签 (${repo.tag_count}个):</div>
                                    <div class="tags-container" style="display: flex; flex-wrap: wrap; gap: 0.4rem; max-height: 100px; overflow-y: auto;">
                                        ${repo.tags.slice(0, 6).map(tag => `
                                            <div class="tag-item" onclick="viewTagDetails('${repo.name}', '${tag}')" style="cursor: pointer;">
                                                <span class="tag-name">${tag}</span>
                                            </div>
                                        `).join('')}
                                        ${repo.tags.length > 6 ? `<div class="more-tags" onclick="event.stopPropagation(); showMoreTags(this, ${JSON.stringify(repo.tags).replace(/'/g, "\\'")}, '${repo.name}')" title="点击显示全部标签">+${repo.tags.length - 6} 更多</div>` : ''}
                                    </div>
                                </div>
                            ` : `
                                <div class="empty-state">
                                    <div class="empty-icon">📭</div>
                                    <div class="empty-text">暂无镜像标签</div>
                                </div>
                            `}
                            
                            <!-- 移除查看详情按钮，改为卡片点击 -->
                        </div>
                    `).join('')}
                </div>
            `;
            
            document.getElementById('repositories-list').innerHTML = html;
            setupCardClicks(); // 设置卡片点击事件
            
            // 更新分页信息
            const totalPages = Math.ceil(allRepositories.length / repositoriesPerPage);
            updatePagination(currentPage, totalPages);
        }
        
        // 加载仓库列表 - 卡片式布局（带分页）
        async function loadRepositories() {
            try {
                console.log('正在加载仓库列表，API地址:', `${API_BASE}/repositories`);
                const response = await fetch(`${API_BASE}/repositories`);
                console.log('API响应状态:', response.status, response.statusText);
                
                if (!response.ok) {
                    throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
                }
                
                const data = await response.json();
                console.log('API响应数据:', data);
                
                if (data.repositories) {
                    allRepositories = data.repositories;
                    console.log(`成功获取 ${allRepositories.length} 个仓库`);
                    currentPage = 1; // 重置到第一页
                    renderRepositoriesPage(); // 渲染第一页
                } else {
                    throw new Error('API返回数据格式不正确: 缺少repositories字段');
                }
            } catch (error) {
                console.error('加载仓库列表失败:', error);
                document.getElementById('repositories-list').innerHTML = `
                    <div class="error">
                        <strong>加载仓库列表失败</strong><br>
                        <small>${error.message}</small><br>
                        <button class="btn btn-primary btn-small" onclick="loadRepositories()">重试</button>
                    </div>
                `;
            }
        }
        
        // 动态生成Docker命令
        async function updateDockerCommands(tags, repository) {
            try {
                const commandsElem = document.getElementById('docker-commands-content');
                if (!commandsElem) return;
                
                // 智能选择标签
                let selectedTag = 'latest';
                if (tags && tags.length > 0) {
                    // 优先使用latest标签
                    const latestTag = tags.find(tag => tag.tag === 'latest');
                    if (latestTag) {
                        selectedTag = 'latest';
                    } else {
                        // 寻找最大的数字版本标签
                        const numericTags = tags
                            .filter(tag => /^v?\d+(\.\d+)*$/.test(tag.tag))
                            .sort((a, b) => {
                                const aParts = a.tag.replace(/^v/, '').split('.').map(Number);
                                const bParts = b.tag.replace(/^v/, '').split('.').map(Number);
                                for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
                                    const aVal = aParts[i] || 0;
                                    const bVal = bParts[i] || 0;
                                    if (bVal !== aVal) return bVal - aVal;
                                }
                                return 0;
                            });
                        
                        if (numericTags.length > 0) {
                            selectedTag = numericTags[0].tag;
                        } else {
                            // 如果没有数字标签，使用最新的标签（按时间排序）
                            const sortedTags = tags
                                .filter(tag => tag.created && tag.created !== '未知')
                                .sort((a, b) => new Date(b.created) - new Date(a.created));
                            
                            selectedTag = sortedTags.length > 0 ? sortedTags[0].tag : tags[0].tag;
                        }
                    }
                }
                
                // 使用当前仓库名替换示例中的ddn-k8s/quay.io/sclorg/postgresql-15-c9s
                const imageName = repository;
                
                // 生成完整的Docker命令（使用环境变量获取registry地址）
                const registryHost = await getRegistryHost();
                const pullCommand = `docker pull ${registryHost}/${imageName}:${selectedTag}`;
                const tagCommand = `docker tag ${registryHost}/${imageName}:${selectedTag} ${imageName}:${selectedTag}`;
                
                // 更新显示内容 - 添加点击复制功能和精美UI
                // 安全转义单引号
                const escapedPullCommand = pullCommand.replace(/'/g, "\\'");
                const escapedTagCommand = tagCommand.replace(/'/g, "\\'");
                
                commandsElem.innerHTML = `
                    <div class="docker-command-line" data-command="${escapedPullCommand}" 
                         title="点击复制: ${pullCommand}">
                        <span class="command-prefix">$</span>
                        <span class="command-text">${pullCommand}</span>
                        <span class="copy-indicator">📋</span>
                    </div>
                    <div class="docker-command-line" data-command="${escapedTagCommand}" 
                         title="点击复制: ${tagCommand}">
                        <span class="command-prefix">$</span>
                        <span class="command-text">${tagCommand}</span>
                        <span class="copy-indicator">📋</span>
                    </div>
                `;
                
                // 使用事件委托，避免内联onclick的问题
                setTimeout(() => {
                    const commandLines = commandsElem.querySelectorAll('.docker-command-line');
                    commandLines.forEach(line => {
                        // 使用data属性存储命令文本，避免字符串转义问题
                        line.removeAttribute('onclick');
                        line.addEventListener('click', function(e) {
                            const commandText = this.getAttribute('data-command').replace(/\\'/g, "'");
                            console.log('🖱️ 点击复制事件触发，命令:', commandText);
                            console.log('🔄 调用 window.copyToClipboard 函数');
                            
                            // 双重验证函数存在
                            if (typeof window.copyToClipboard === 'function') {
                                console.log('✅ copyToClipboard 函数存在，开始复制');
                                window.copyToClipboard(commandText);
                            } else {
                                console.error('❌ ERROR: window.copyToClipboard is not a function');
                                console.log('函数状态:', typeof window.copyToClipboard);
                                
                                // 尝试手动复制作为备选方案
                                navigator.clipboard.writeText(commandText).then(() => {
                                    alert('✅ 命令已复制到剪贴板');
                                }).catch(() => {
                                    alert('❌ 复制功能不可用，请手动复制命令');
                                });
                            }
                            e.stopPropagation();
                        });
                    });
                    
                    // 调试信息
                    console.log('Docker命令复制功能已初始化，绑定事件:', commandLines.length);
                }, 100);
                
                // 添加复制功能样式
                const style = document.createElement('style');
                style.textContent = `
                    .docker-command-line {
                        cursor: pointer;
                        padding: 0.75rem 1rem;
                        margin: 0.5rem 0;
                        border-radius: 8px;
                        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                        border: 1px solid #dee2e6;
                        transition: all 0.3s ease;
                        display: flex;
                        align-items: center;
                        gap: 0.5rem;
                        position: relative;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                    }
                    .docker-command-line:hover {
                        background: linear-gradient(135deg, #e9ecef 0%, #dee2e6 100%);
                        border-color: #667eea;
                        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.2);
                        transform: translateY(-2px);
                    }
                    .command-prefix {
                        color: #28a745;
                        font-weight: bold;
                        font-size: 1rem;
                    }
                    .command-text {
                        flex: 1;
                        font-family: 'Fira Code', 'Courier New', monospace;
                        color: #2c3e50;
                        font-size: 0.95rem;
                        overflow: hidden;
                        text-overflow: ellipsis;
                    }
        .copy-indicator {
            color: #6c757d;
            font-size: 1rem;
            transition: all 0.3s ease;
            padding: 0.3rem;
            border-radius: 4px;
        }
        .docker-command-line:hover .copy-indicator {
            color: #667eea;
            background: rgba(102, 126, 234, 0.1);
            transform: scale(1.1);
        }
    `;
    document.head.appendChild(style);
    
    // 添加成功复制后的动画样式
    const successStyle = document.createElement('style');
    successStyle.textContent = `
        @keyframes copySuccess { 
            0% { opacity: 0; transform: translateY(-10px); }
            50% { opacity: 1; transform: translateY(0); }
            100% { opacity: 0; transform: translateY(10px); }
        }
        .copy-success {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(40, 167, 69, 0.9);
            color: white;
            padding: 1rem 2rem;
            border-radius: 8px;
            z-index: 10000;
            animation: copySuccess 2s ease-in-out;
            font-weight: 500;
        }
    `;
    document.head.appendChild(successStyle);
                
                console.log(`Docker命令已更新: 仓库=${repository}, 标签=${selectedTag}`);
            } catch (error) {
                console.error('生成Docker命令失败:', error);
                const commandsElem = document.getElementById('docker-commands-content');
                if (commandsElem) {
                    commandsElem.innerHTML = `生成Docker命令失败: ${error.message}`;
                }
            }
        }
        
        // 删除标签（优化版） - 确保触发空仓库清理
        async function deleteTag(repository, tag) {
            // 使用setTimeout避免阻塞UI
            setTimeout(async () => {
                if (!confirm(`确定要删除 ${repository}:${tag} 吗？此操作不可撤销！`)) return;
                
                try {
                    const url = `${API_BASE}/repository/${encodeURIComponent(repository)}/tag/${encodeURIComponent(tag)}`;
                    console.log('删除标签URL:', url);
                    
                    // 显示加载状态
                    const deleteBtn = document.querySelector(`button[onclick*="deleteTag('${repository}', '${tag}')"]`);
                    if (deleteBtn) {
                        deleteBtn.disabled = true;
                        deleteBtn.innerHTML = '删除中...';
                    }
                    
                    // 直接删除标签
                    const response = await fetch(url, {
                        method: 'DELETE',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        }
                    });
                    
                    if (response.ok) {
                        const result = await response.json();
                        console.log('标签删除成功:', result);
                        
                        // 🔥 关键修复：强制调用空仓库清理API
                        console.log(`强制触发空仓库清理: ${repository}`);
                        try {
                            const cleanResponse = await fetch(`${API_BASE}/clean-empty`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' }
                            });
                            
                            if (cleanResponse.ok) {
                                const cleanResult = await cleanResponse.json();
                                console.log('空仓库清理结果:', cleanResult);
                                
                                if (cleanResult.success && cleanResult.deleted_repositories && cleanResult.deleted_repositories.length > 0) {
                                    alert(`✅ 标签删除完成，${cleanResult.deleted_repositories.length}个空仓库已清理`);
                                } else {
                                    alert(`✅ 标签删除完成，暂无空仓库需要清理`);
                                }
                            } else {
                                console.warn('空仓库清理API调用失败，但标签删除成功');
                                alert(`✅ 标签删除成功`);
                            }
                        } catch (cleanError) {
                            console.warn('空仓库清理执行失败:', cleanError);
                            alert(`✅ 标签删除成功（空仓库清理失败: ${cleanError.message})`);
                        }
                        
                        // 强制刷新数据
                        setTimeout(() => {
                            loadData();
                        }, 500);
                    } else {
                        const error = await response.json();
                        console.error('删除失败:', error);
                        alert('删除失败: ' + (error.error || response.statusText));
                    }
                } catch (error) {
                    console.error('删除标签错误:', error);
                    alert('删除失败: ' + error.message);
                } finally {
                    // 恢复按钮状态
                    if (deleteBtn) {
                        deleteBtn.disabled = false;
                        deleteBtn.innerHTML = '×';
                    }
                }
            }, 100);  // 100ms延迟确保UI响应
        }
        
        // 检查是否是最后一个标签
        async function checkIfLastTag(repository, currentTag) {
            try {
                const response = await fetch(`${API_BASE}/repository/${encodeURIComponent(repository)}/tags`);
                if (response.ok) {
                    const data = await response.json();
                    // 如果只有1个标签且是当前要删除的标签
                    return data.tags && data.tags.length === 1 && data.tags[0] === currentTag;
                }
                return false;
            } catch (error) {
                console.error('检查最后一个标签失败:', error);
                return false;
            }
        }
        
        // 检查并清理空仓库（集成到删除标签功能中）
        async function checkAndCleanEmptyRepository(repository) {
            try {
                console.log('检查仓库是否为空:', repository);
                
                // 获取该仓库的标签列表
                const repoResponse = await fetch(`${API_BASE}/repository/${encodeURIComponent(repository)}/tags`);
                if (!repoResponse.ok) {
                    console.log('获取仓库标签失败，可能是仓库已被删除');
                    return;
                }
                
                const repoData = await repoResponse.json();
                
                // 检查是否是最后一个标签
                if (repoData.tags && repoData.tags.length === 0) {
                    console.log(`仓库 ${repository} 已无标签，执行空仓库清理...`);
                    
                    // 调用空仓库清理API
                    const cleanResponse = await fetch(`${API_BASE}/clean-empty`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' }
                    });
                    
                    const cleanResult = await cleanResponse.json();
                    if (cleanResponse.ok) {
                        console.log('空仓库清理结果:', cleanResult);
                        if (cleanResult.deleted_repositories && cleanResult.deleted_repositories.includes(repository)) {
                            console.log(`仓库 ${repository} 已成功清理`);
                            alert(`✅ 已删除空仓库: ${repository}`);
                        }
                    } else {
                        console.error('空仓库清理失败:', cleanResult);
                        alert(`⚠️ 标签删除成功，但空仓库清理失败: ${cleanResult.error}`);
                    }
                } else {
                    console.log(`仓库 ${repository} 还有 ${repoData.tags.length} 个标签，无需清理`);
                }
            } catch (error) {
                console.error('检查空仓库失败:', error);
                // 忽略检查错误，不影响主流程
            }
        }
        
        // 查看仓库详情（点击卡片触发）
        function viewRepository(repository) {
            // 创建详情页HTML
            const detailHtml = `
                <div class="detail-header">
                    <h2>📦 ${repository}</h2>
                    <div style="display: flex; gap: 1rem;">
                        <button class="btn btn-danger" onclick="deleteRepository('${repository}')" 
                                style="background: #dc3545; border-color: #dc3545; color: white;">
                            🗑️ 删除仓库
                        </button>
                        <button class="btn btn-primary" onclick="backToList()">返回首页</button>
                    </div>
                </div>
                
                <div class="detail-stats">
                    <div class="stat-item">
                        <span class="stat-number" id="detail-tag-count">0</span>
                        <span class="stat-label">标签数量</span>
                    </div>
                </div>
                
                <div class="detail-description">
                    <h3>镜像描述</h3>
                    <div id="repository-description-content">
                        正在加载镜像描述...
                    </div>
                </div>

                <div class="docker-commands" style="margin-bottom: 1.5rem; background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 1.5rem;">
                    <h3 style="color: #2c3e50; margin-bottom: 1rem; font-size: 1.1rem; border-bottom: 2px solid #667eea; padding-bottom: 0.5rem; display: flex; align-items: center;">
                        <span style="flex: 1;">Docker命令</span>
                        <span style="font-size: 0.8rem; color: #6c757d;">点击命令可复制</span>
                    </h3>
                    <div id="docker-commands-content" style="font-family: 'Courier New', monospace; color: #2c3e50; background: #f8f9fa; padding: 1.2rem; border-radius: 8px; border: 1px solid #e9ecef; font-size: 0.9rem; line-height: 1.6;">
                        正在加载Docker命令...
                    </div>
                </div>
                
                <div class="detail-tags">
                    <h3>镜像版本</h3>
                    <div id="tag-list" class="tag-list">
                        <div class="loading">加载标签列表...</div>
                    </div>
                </div>
            `;
            
            // 替换主内容区
            document.querySelector('.container').innerHTML = `
                <div class="repository-detail">
                    ${detailHtml}
                </div>
            `;
            
            // 加载详情数据
            loadRepositoryDetails(repository);
        }
        
        // 加载镜像描述信息
        async function loadRepositoryDescription(repository) {
            try {
                const response = await fetch(`${API_BASE}/repository/${encodeURIComponent(repository)}/description`);
                const data = await response.json();
                
                const descriptionElem = document.getElementById('repository-description-content');
                if (!descriptionElem) {
                    console.warn('repository-description-content 元素未找到');
                    return;
                }
                
                if (data.success && data.data) {
                    const description = data.data.description || "这是一个Docker镜像仓库，包含多个版本的镜像文件。";
                    const category = data.data.category || 'unknown';
                    const tags = data.data.tags || [];
                    
                    // 格式化显示描述信息，添加缩进（两个全角空格）
                    let descriptionHtml = `<p style="text-indent: 2em; line-height: 1.6;">${description}</p>`;
                    
                    // 添加分类和标签信息（如果有）- 统一样式和布局
                    
                    // 分类信息（如果可用且不是unknown）
                    if (category && category !== 'unknown') {
                        descriptionHtml += `<div style="margin-top: 1rem;">
                            <div style="font-size: 0.9rem; color: #666; margin-bottom: 0.5rem; font-weight: 600;">分类</div>
                            <div style="display: flex; flex-wrap: wrap; gap: 0.4rem;">
                                <span style="
                                    background: #e8f5e8; 
                                    color: #2e7d32; 
                                    padding: 0.3rem 0.7rem; 
                                    border-radius: 16px; 
                                    font-size: 0.85rem;
                                    font-weight: 500;
                                    border: 1px solid #c8e6c9;
                                    transition: all 0.3s ease;
                                    cursor: default;
                                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                                "
                                onmouseover="this.style.background='#c8e6c9'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 8px rgba(0,0,0,0.15)';"
                                onmouseout="this.style.background='#e8f5e8'; this.style.transform='translateY(0)'; this.style.boxShadow='0 1px 3px rgba(0,0,0,0.1)';"
                                title="镜像分类"
                                >
                                    ${category}
                                </span>
                            </div>
                        </div>`;
                    }
                    
                    // 标签信息（如果可用）- 统一标题格式
                    if (tags && Array.isArray(tags) && tags.length > 0) {
                        const validTags = tags.filter(tag => tag && tag.trim() !== '');
                        if (validTags.length > 0) {
                            descriptionHtml += `<div style="margin-top: 1rem;">
                                <div style="font-size: 0.9rem; color: #666; margin-bottom: 0.5rem; font-weight: 600;">标签</div>
                                <div style="display: flex; flex-wrap: wrap; gap: 0.4rem;">
                                    ${validTags.map(tag => `
                                        <span style="
                                            background: #e3f2fd; 
                                            color: #1976d2; 
                                            padding: 0.3rem 0.7rem; 
                                            border-radius: 16px; 
                                            font-size: 0.85rem;
                                            font-weight: 500;
                                            border: 1px solid #bbdefb;
                                            transition: all 0.3s ease;
                                            cursor: default;
                                            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                                        "
                                        onmouseover="this.style.background='#bbdefb'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 8px rgba(0,0,0,0.15)';"
                                        onmouseout="this.style.background='#e3f2fd'; this.style.transform='translateY(0)'; this.style.boxShadow='0 1px 3px rgba(0,0,0,0.1)';"
                                        title="点击标签查看类似镜像"
                                        >
                                            ${tag}
                                        </span>
                                    `).join('')}
                                </div>
                            </div>`;
                        }
                    }
                    
                    descriptionElem.innerHTML = descriptionHtml;
                } else {
                    descriptionElem.innerHTML = '<p style="text-indent: 2em; line-height: 1.6;">这是一个Docker镜像仓库，包含多个版本的镜像文件。</p>';
                }
            } catch (error) {
                console.error('加载镜像描述失败:', error);
                const descriptionElem = document.getElementById('repository-description-content');
                if (descriptionElem) {
                    descriptionElem.innerHTML = '<p>这是一个Docker镜像仓库，包含多个版本的镜像文件。</p>';
                }
            }
        }

        // 加载仓库详情数据
        async function loadRepositoryDetails(repository) {
            try {
                const response = await fetch(`${API_BASE}/repository/${encodeURIComponent(repository)}/details`);
                const data = await response.json();
                
                // 提前加载镜像描述信息
                loadRepositoryDescription(repository);
                
                // 动态生成Docker命令
                await updateDockerCommands(data.tags, repository);
                
                if (data.success) {
                    // 更新标签数量 - 安全检查
                    const detailTagCount = document.getElementById('detail-tag-count');
                    if (detailTagCount) {
                        detailTagCount.textContent = data.tag_count;
                    } else {
                        console.warn('detail-tag-count 元素未找到');
                    }
                    
                    // 先打印标签数据用于调试
                    console.log('标签详情数据:', data.tags);
                    
                    // 渲染标签列表（增强显示）
                    const tagListHtml = data.tags.map(tag => {
                        // 格式化时间（如果可用）
                        const formattedTime = formatDateTime(tag.created || tag.last_updated);
                        
                        // 尝试不同的字段名获取镜像ID
                        const imageId = tag.image_id || tag.digest || getShortDigest(tag) || '未知';
                        
                        // 尝试不同的字段名获取大小
                        const size = tag.total_size || tag.size || tag.length || 0;
                        
                        return `
                            <div class="tag-card" onclick="viewTagDetails('${repository}', '${tag.tag}')" style="cursor: pointer;">
                                <div class="tag-header">
                                    <span class="tag-name">${tag.name}</span>
                                    <button class="btn btn-danger btn-small" 
                                        onclick="event.stopPropagation(); deleteTag('${repository}', '${tag.tag}')">
                                        🗑️ 删除
                                    </button>
                                </div>
                                <div class="tag-details">
                                    <div><strong>大小:</strong> ${formatBytes(size)}</div>
                                    <div><strong>创建时间:</strong> ${formattedTime}</div>
                                    <div><strong>镜像ID:</strong> ${imageId}</div>
                                </div>
                            </div>
                        `;
                    }).join('');
                    
                    // 安全检查
                    const tagList = document.getElementById('tag-list');
                    if (tagList) {
                        tagList.innerHTML = tagListHtml;
                    } else {
                        console.error('tag-list 元素未找到，无法显示标签列表');
                    }
                } else {
                    const tagList = document.getElementById('tag-list');
                    if (tagList) {
                        tagList.innerHTML = `
                            <div class="error">加载失败: ${data.error || '未知错误'}</div>
                        `;
                    }
                }
            } catch (error) {
                const tagList = document.getElementById('tag-list');
                if (tagList) {
                    tagList.innerHTML = `
                        <div class="error">加载失败: ${error.message}</div>
                    `;
                }
            }
        }
        
        // 格式化日期时间
        function formatDateTime(dateString) {
            if (!dateString || dateString === '未知') return '未知';
            try {
                const date = new Date(dateString);
                if (isNaN(date.getTime())) return dateString; // 如果无法解析，返回原值
                
                // 格式化为：YYYY-MM-DD HH:MM
                return date.toISOString().slice(0, 16).replace('T', ' ');
            } catch {
                return dateString;
            }
        }
        
        // 从任意字段提取短digest
        function getShortDigest(tag) {
            const possibleFields = ['image_id', 'digest', 'id', 'config.digest'];
            for (const field of possibleFields) {
                const value = getNestedValue(tag, field);
                if (value && typeof value === 'string' && value.includes(':')) {
                    return value.split(':')[1].substring(0, 12); // 取SHA256前12位
                }
            }
            return null;
        }
        
        // 获取嵌套对象值
        function getNestedValue(obj, path) {
            return path.split('.').reduce((acc, part) => acc && acc[part], obj);
        }
        
        // 检查值是否有效（不为空、'未知'、0等）
        function isValidValue(value) {
            if (value === null || value === undefined) return false;
            if (typeof value === 'string' && (value === '未知' || value.trim() === '')) return false;
            if (typeof value === 'number' && value === 0) return false;
            if (Array.isArray(value) && value.length === 0) return false;
            if (typeof value === 'object' && Object.keys(value).length === 0) return false;
            return true;
        }
        
        // 格式化字节大小
        function formatBytes(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
        
        // 点击仓库卡片触发查看详情
        function setupCardClicks() {
            document.querySelectorAll('.repo-card').forEach(card => {
                const repoNameElem = card.querySelector('.repo-name');
                if (repoNameElem) {
                    const repoName = repoNameElem.textContent;
                    card.style.cursor = 'pointer';
                    card.addEventListener('click', (e) => {
                        // 避免点击按钮和标签时触发
                        if (!e.target.closest('.btn, .tag-delete, .more-tags, .tag-item')) {
                            viewRepository(repoName);
                        }
                    });
                } else {
                    console.warn('仓库卡片中未找到 repo-name 元素');
                }
            });
        }
        
        // 显示更多标签
        function showMoreTags(container, tags, repoName) {
            const tagElements = tags.map(tag => `
                <div class="tag-item">
                    <span class="tag-name">${tag}</span>
                    <button class="tag-delete" onclick="event.stopPropagation(); deleteTag('${repoName}', '${tag}')" title="删除标签">
                        ×
                    </button>
                </div>
            `).join('');
            
            container.innerHTML = tagElements;
        }
        
        // 查看标签详情（统一处理，不再区分来源页面）
        function viewTagDetails(repository, tag) {
            // 清除所有导航状态，统一返回首页
            navigationStack = ['home', 'tag_detail'];
            sessionStorage.removeItem('fromRepositoryDetail');
            sessionStorage.removeItem('lastRepositoryDetail');
            
            sessionStorage.setItem('currentRepository', repository);
            sessionStorage.setItem('currentTag', tag);
            fetch(`${API_BASE}/repository/${encodeURIComponent(repository)}/tag/${encodeURIComponent(tag)}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        renderTagDetailPage(data.data);
                    } else {
                        alert('加载标签详情失败: ' + (data.error || '未知错误'));
                    }
                })
                .catch(error => {
                    alert('加载标签详情失败: ' + error.message);
                });
        }

        // 查看镜像详情页面
        function viewRepositoryDetails(repository) {
            // 创建详情页HTML
            const detailHtml = `
                <div class="detail-header">
                    <h2>📦 ${repository}</h2>
                    <div style="display: flex; gap: 1rem;">
                        <button class="btn btn-danger" onclick="deleteRepository('${repository}')" 
                                style="background: #dc3545; border-color: #dc3545; color: white;">
                            🗑️ 删除仓库
                        </button>
                        <button class="btn btn-primary" onclick="backToList()">返回首页</button>
                    </div>
                </div>
                
                <div class="detail-stats">
                    <div class="stat-item">
                        <span class="stat-number" id="detail-tag-count">0</span>
                        <span class="stat-label">标签数量</span>
                    </div>
                </div>
                
                <div class="detail-description">
                    <h3>镜像描述</h3>
                    <div id="repository-description-content">
                        正在加载镜像描述...
                    </div>
                </div>

                <div class="docker-commands" style="margin-bottom: 1.5rem; background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 1.5rem;">
                    <h3 style="color: #2c3e50; margin-bottom: 1rem; font-size: 1.1rem; border-bottom: 2px solid #667eea; padding-bottom: 0.5rem; display: flex; align-items: center;">
                        <span style="flex: 1;">Docker命令</span>
                        <span style="font-size: 0.8rem; color: #6c757d;">点击命令可复制</span>
                    </h3>
                    <div id="docker-commands-content" style="font-family: 'Courier New', monospace; color: #2c3e50; background: #f8f9fa; padding: 1.2rem; border-radius: 8px; border: 1px solid #e9ecef; font-size: 0.9rem; line-height: 1.6;">
                        正在加载Docker命令...
                    </div>
                </div>
                
                <div class="detail-tags">
                    <h3>镜像版本</h3>
                    <div id="tag-list" class="tag-list">
                        <div class="loading">加载标签列表...</div>
                    </div>
                </div>
            `;
            
            // 替换主内容区
            document.querySelector('.container').innerHTML = `
                <div class="repository-detail">
                    ${detailHtml}
                </div>
            `;
            
            // 加载详情数据
            loadRepositoryDetails(repository);
        }

        // 渲染标签详情页面
        function renderTagDetailPage(tagData) {
            const detailHtml = `
                <div class="tag-detail-page">
                    <div class="tag-detail-header">
                        <h2>📦 ${tagData.full_name}</h2>
                        <div style="display: flex; gap: 0.5rem;">
                            <button class="btn btn-secondary" onclick="viewRepositoryDetails('${tagData.repository}')">← 返回镜像页</button>
                            <button class="btn btn-primary" onclick="backToList()">← 返回首页</button>
                        </div>
                    </div>

        <div class="tag-detail-stats">
            <div class="stat-card">
                <div class="stat-value">${formatBytes(tagData.size)}</div>
                <div class="stat-label">镜像大小</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${tagData.architecture}</div>
                <div class="stat-label">架构</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${tagData.os}</div>
                <div class="stat-label">操作系统</div>
            </div>
        </div>

                <div class="docker-commands" style="margin-bottom: 1.5rem; background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 1.5rem;">
                    <h3 style="color: #2c3e50; margin-bottom: 1rem; font-size: 1.1rem; border-bottom: 2px solid #667eea; padding-bottom: 0.5rem; display: flex; align-items: center;">
                        <span style="flex: 1;">Docker命令</span>
                        <span style="font-size: 0.8rem; color: #6c757d;">点击命令可复制</span>
                    </h3>
                    <div id="docker-commands-content-tag" style="font-family: 'Courier New', monospace; color: #2c3e50; background: #f8f9fa; padding: 1.2rem; border-radius: 8px; border: 1px solid #e9ecef; font-size: 0.9rem; line-height: 1.6;">
                        <div class="docker-command-line" 
                             data-command="docker pull r.ue6.fun:8888/${tagData.repository}:${tagData.tag}">
                            <span class="command-prefix">$</span>
                            <span class="command-text">docker pull r.ue6.fun:8888/${tagData.repository}:${tagData.tag}</span>
                            <span class="copy-indicator">📋</span>
                        </div>
                        <div class="docker-command-line" 
                             data-command="docker tag r.ue6.fun:8888/${tagData.repository}:${tagData.tag} ${tagData.repository}:${tagData.tag}">
                            <span class="command-prefix">$</span>
                            <span class="command-text">docker tag r.ue6.fun:8888/${tagData.repository}:${tagData.tag} ${tagData.repository}:${tagData.tag}</span>
                            <span class="copy-indicator">📋</span>
                        </div>
                    </div>
                </div>

                    <div class="tag-detail-info">
                        <div class="info-section">
                            <h3>基本信息</h3>
                            <div class="info-grid" style="grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; width: 100%;">
                                <div class="info-item" style="padding: 1rem; margin-bottom: 0.5rem;">
                                    <span class="info-label">镜像ID:</span>
                                    <span class="info-value" style="font-weight: 500;">${tagData.image_id || '未知'}</span>
                                </div>
                                <div class="info-item" style="padding: 1rem; margin-bottom: 0.5rem;">
                                    <span class="info-label">更新时间:</span>
                                    <span class="info-value" style="font-weight: 500;">${formatDateTime(tagData.created)}</span>
                                </div>
                                <div class="info-item" style="padding: 1rem; margin-bottom: 0.5rem;">
                                    <span class="info-label">Schema版本:</span>
                                    <span class="info-value" style="font-weight: 500;">${tagData.schemaVersion}</span>
                                </div>
                                ${tagData.config?.ExposedPorts || tagData.config?.exposedPorts || tagData.config?.ports || tagData.config?.Ports ? `
                                <div class="info-item" style="padding: 1rem; margin-bottom: 0.5rem;">
                                    <span class="info-label">暴露端口:</span>
                                    <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.3rem;">
                                        ${Object.keys(
                                            tagData.config.ExposedPorts || 
                                            tagData.config.exposedPorts || 
                                            tagData.config.ports || 
                                            tagData.config.Ports || {}
                                        ).map(port => `
                                            <span style="background: #667eea; color: white; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.85rem; font-weight: 500;">
                                                ${port}
                                            </span>
                                        `).join('')}
                                    </div>
                                </div>
                                ` : ''}
                            </div>
                            <div class="full-width">
                                <div class="info-item" style="padding: 1rem; margin-top: 1rem;">
                                    <span class="info-label" style="font-weight: 600;">完整镜像ID:</span>
                                    <span class="info-value" style="font-size: 0.85rem; word-break: break-all; line-height: 1.4; background: #f8f9fa; padding: 0.5rem; border-radius: 4px; margin: 0.3rem auto 0; display: block; text-align: center; max-width: 90%;">
                                        ${tagData.digest || tagData.config?.digest || '未知'}
                                    </span>
                                </div>
                            </div>
                        </div>
                        
                        ${tagData.config && Object.keys(tagData.config).length > 0 ? `
                        <div class="info-section">
                            <h3>配置信息</h3>
                            <div class="info-grid" style="grid-template-columns: 1fr; gap: 1.5rem;">
                                <div class="config-section">
                                    ${tagData.config.entrypoint && tagData.config.entrypoint.length ? `
                                        <div class="info-item" style="padding: 1rem; margin-bottom: 0.8rem; min-height: auto;">
                                            <span class="info-label">入口点:</span>
                                            <span class="info-value" style="font-weight: 500; word-break: break-all; max-width: 70%;">${tagData.config.entrypoint.join(' ')}</span>
                                        </div>
                                    ` : ''}
                                    ${tagData.config.cmd && tagData.config.cmd.length ? `
                                        <div class="info-item" style="padding: 1rem; margin-bottom: 0.8rem; min-height: auto;">
                                            <span class="info-label">CMD:</span>
                                            <span class="info-value" style="font-weight: 500; word-break: break-all; max-width: 70%;">${tagData.config.cmd.join(' ')}</span>
                                        </div>
                                    ` : ''}
                                    <div class="info-item" style="padding: 1rem; margin-bottom: 0.8rem; min-height: auto;">
                                        <span class="info-label">工作目录:</span>
                                        <span class="info-value" style="font-weight: 500; word-break: break-all; max-width: 70%;">${tagData.config.working_dir || '/'}</span>
                                    </div>
                                    <div class="info-item" style="padding: 1rem; margin-bottom: 0.8rem; min-height: auto;">
                                        <span class="info-label">用户:</span>
                                        <span class="info-value" style="font-weight: 500; word-break: break-all; max-width: 70%;">${tagData.config.user || '默认'}</span>
                                    </div>
                                </div>
                                <div class="config-section">
                                    ${tagData.config.env && tagData.config.env.length ? `
                                        <div class="info-item" style="padding: 1rem; margin-bottom: 0.8rem; min-height: auto; grid-column: 1 / -1;">
                                            <span class="info-label" style="display: block; margin-bottom: 0.5rem; font-weight: 600;">环境变量:</span>
                                            <div class="env-list" style="font-size: 0.85rem; font-family: 'Courier New', monospace; background: #f8f9fa; padding: 0.8rem; border-radius: 6px; max-height: 120px; overflow-y: auto; display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem;">
                                                ${tagData.config.env.slice(0, 10).map(env => `
                                                    <div style="margin-bottom: 0.3rem; word-break: break-all; overflow-wrap: break-word; background: #fff; padding: 0.5rem; border-radius: 4px; border-left: 3px solid #667eea;">
                                                        ${env}
                                                    </div>
                                                `).join('')}
                                                ${tagData.config.env.length > 10 ? `<div style="color: #666; font-style: italic; margin-top: 0.5rem; grid-column: 1 / -1;">... 和 ${tagData.config.env.length - 10} 个其他变量</div>` : ''}
                                            </div>
                                        </div>
                                    ` : `
                                        <div class="info-item" style="padding: 1rem; margin-bottom: 0.8rem; min-height: auto; grid-column: 1 / -1; text-align: center; color: #999;">
                                            <span class="info-label" style="display: block; margin-bottom: 0.5rem; font-weight: 600;">环境变量:</span>
                                            <div>无环境变量配置</div>
                                        </div>
                                    `}
                                </div>
                            </div>
                            <div class="full-width" style="margin-top: 1rem;">
                                ${tagData.config.exposedPorts ? `
                                    <div class="info-item" style="padding: 1rem; margin-bottom: 1rem;">
                                        <span class="info-label" style="display: block; margin-bottom: 0.5rem; font-weight: 600;">暴露端口:</span>
                                        <div class="ports-container" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                                            ${Object.keys(tagData.config.exposedPorts).map(port => `
                                                <span style="background: #667eea; color: white; padding: 0.3rem 0.7rem; border-radius: 6px; font-size: 0.85rem; font-weight: 500;">
                                                    ${port}
                                                </span>
                                            `).join('')}
                                        </div>
                                    </div>
                                ` : ''}
                                ${tagData.config?.volumes && Object.keys(tagData.config.volumes).length > 0 ? `
                                    <div class="info-item" style="padding: 1rem; margin-bottom: 1rem;">
                                        <span class="info-label" style="display: block; margin-bottom: 0.5rem; font-weight: 600;">数据卷:</span>
                                        <div class="volumes-container" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                                            ${Object.keys(tagData.config.volumes).map(volume => `
                                                <span style="background: #28a745; color: white; padding: 0.3rem 0.7rem; border-radius: 6px; font-size: 0.85rem; font-weight: 500;">
                                                    ${volume}
                                                </span>
                                            `).join('')}
                                        </div>
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                        ` : ''}

                        <div class="info-section">
                            <h3>镜像层 (${tagData.layers ? tagData.layers.length : 0}层)</h3>
                            ${tagData.layers && tagData.layers.length > 0 ? `
                                <div class="layers-list">
                                    ${tagData.layers.map((layer, index) => `
                                        <div class="layer-item">
                                            <div class="layer-header">
                                                <span class="layer-index">${index + 1}</span>
                                                <span class="layer-digest">${layer.digest || '未知'}</span>
                                                <span class="layer-size">${formatBytes(layer.size || 0)}</span>
                                            </div>
                                            <div class="layer-media-type">${layer.mediaType || '未知'}</div>
                                        </div>
                                    `).join('')}
                                </div>
                            ` : `
                                <div class="no-data">无层数据</div>
                            `}
                        </div>
                    </div>

                    <div class="tag-actions">
                        <button class="btn btn-danger" onclick="deleteTag('${tagData.repository}', '${tagData.tag}')">
                            🗑️ 删除此标签
                        </button>
                    </div>
                </div>
            `;

            document.querySelector('.container').innerHTML = detailHtml;
            
            // 为标签详情页的Docker命令添加点击复制功能
            setTimeout(() => {
                const commandLines = document.querySelectorAll('#docker-commands-content-tag .docker-command-line');
                commandLines.forEach(line => {
                    // 使用data属性存储命令文本，避免字符串转义问题
                    line.removeAttribute('onclick');
                    line.addEventListener('click', function(e) {
                        const commandText = this.getAttribute('data-command');
                        console.log('🖱️ 标签详情页点击复制事件触发，命令:', commandText);
                        
                        if (typeof window.copyToClipboard === 'function') {
                            console.log('✅ copyToClipboard 函数存在，开始复制');
                            window.copyToClipboard(commandText);
                        } else {
                            console.error('❌ ERROR: window.copyToClipboard is not a function');
                            // 备选复制方案
                            navigator.clipboard.writeText(commandText).then(() => {
                                showToast('✅ 命令已复制到剪贴板');
                            }).catch(() => {
                                alert('❌ 复制功能不可用，请手动复制命令');
                            });
                        }
                        e.stopPropagation();
                    });
                });
                
                console.log('标签详情页Docker命令复制功能已初始化，绑定事件:', commandLines.length);
            }, 100);
        }

        // 复制Docker命令到剪贴板
        function copyDockerCommand(imageName) {
            const command = `docker pull ${imageName}`;
            navigator.clipboard.writeText(command)
                .then(() => alert('Docker命令已复制到剪贴板: ' + command))
                .catch(err => alert('复制失败: ' + err));
        }

        // 删除仓库（调试增强版）
        async function deleteRepository(repository) {
            console.log('开始删除仓库:', repository);
            
            if (!confirm(`确定要删除整个仓库 ${repository} 吗？此操作不可恢复！`)) return;
            
            try {
                console.log('获取仓库标签列表...');
                // 先删除所有标签
                const repoResponse = await fetch(`${API_BASE}/repository/${encodeURIComponent(repository)}/tags`);
                console.log('标签响应状态:', repoResponse.status);
                
                const repoData = await repoResponse.json();
                console.log('标签数据:', repoData);
                
                // 等待所有标签删除完成
                if (repoData.tags && repoData.tags.length > 0) {
                    console.log(`发现 ${repoData.tags.length} 个标签需要删除`);
                    for (const tag of repoData.tags) {
                        console.log(`删除标签: ${repository}:${tag}`);
                        const deleteResponse = await fetch(`${API_BASE}/repository/${encodeURIComponent(repository)}/tag/${encodeURIComponent(tag)}`, {
                            method: 'DELETE',
                            headers: {
                                'Content-Type': 'application/json'
                            }
                        });
                        console.log(`删除响应状态: ${deleteResponse.status}`);
                        
                        if (!deleteResponse.ok) {
                            const errorData = await deleteResponse.json();
                            console.error(`删除标签失败: ${repository}:${tag}`, errorData);
                        } else {
                            console.log(`标签删除成功: ${repository}:${tag}`);
                        }
                    }
                } else {
                    console.log('仓库为空，无需删除标签');
                }
                
                console.log('强制清理空仓库目录...');
                // 🔥 关键修复：强制调用空仓库清理API
                const cleanResponse = await fetch(`${API_BASE}/clean-empty`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                console.log('空仓库清理响应状态:', cleanResponse.status);
                
                let cleanResultMessage = "空仓库目录已清理";
                if (cleanResponse.ok) {
                    const cleanResult = await cleanResponse.json();
                    console.log('空仓库清理结果:', cleanResult);
                    if (cleanResult.deleted_repositories && cleanResult.deleted_repositories.includes(repository)) {
                        cleanResultMessage = `✅ 已删除空仓库目录: ${repository}`;
                    }
                } else {
                    console.warn('空仓库清理API调用失败');
                    cleanResultMessage = "⚠️ 空仓库目录清理失败";
                }
                
                console.log('运行垃圾回收清理文件...');
                // 然后运行垃圾回收清理底层文件
                const gcResponse = await fetch(`${API_BASE}/gc`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                console.log('垃圾回收响应状态:', gcResponse.status);
                
                if (gcResponse.ok) {
                    const gcResult = await gcResponse.json();
                    console.log('垃圾回收结果:', gcResult);
                    alert(`✅ 仓库删除完成\n${cleanResultMessage}\n${gcResult.message || ''}`);
                } else {
                    const gcError = await gcResponse.json();
                    console.error('垃圾回收失败:', gcError);
                    alert(`✅ 仓库删除完成\n${cleanResultMessage}\n⚠️ 垃圾回收未执行`);
                }
                
                console.log('刷新页面数据...');
                // 刷新页面显示最新状态
                setTimeout(() => {
                    loadData();
                }, 2000);
                
            } catch (error) {
                console.error('删除仓库错误详情:', error);
                alert('❌ 删除失败: ' + error.message);
            }
        }
        
        // 重启Registry容器
        async function garbageCollection() {
            if (!confirm('确定要重启registry容器吗？服务将短暂中断！')) return;
            
            try {
                const response = await fetch(`${API_BASE}/restart-registry`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                const result = await response.json();
                
                if (response.ok) {
                    alert(`✅ ${result.message}\nRegistry容器已成功重启`);
                    // 不再自动执行健康检查，避免重复提示
                } else {
                    alert('重启失败: ' + (result.error || response.statusText));
                }
            } catch (error) {
                alert('重启失败: ' + error.message);
            }
        }
        
        // 获取Registry外部地址函数
        async function getRegistryHost() {
            try {
                // 尝试从后端获取环境变量配置的地址
                const response = await fetch(`${API_BASE}/registry-host`);
                if (response.ok) {
                    const data = await response.json();
                    return data.host || 'r.ue6.fun:8888'; // 默认值
                }
            } catch (error) {
                console.warn('获取registry host失败，使用默认值:', error);
            }
            return 'r.ue6.fun:8888'; // 默认值
        }
        
        // 重启Registry容器
        async function restartRegistry() {
            if (!confirm('确定要重启registry容器吗？服务将短暂中断！')) return;
            
            try {
                // 显示加载状态
                const restartBtn = event.target;
                const originalText = restartBtn.innerHTML;
                restartBtn.disabled = true;
                restartBtn.innerHTML = '🔄 重启中...';
                
                const response = await fetch(`${API_BASE}/restart-registry`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                const result = await response.json();
                
                // 恢复按钮状态
                restartBtn.disabled = false;
                restartBtn.innerHTML = originalText;
                
                if (response.ok) {
                    alert(`✅ ${result.message}\nRegistry容器已成功重启`);
                    // 不再自动执行健康检查，避免重复提示
                } else {
                    alert('重启失败: ' + (result.error || response.statusText));
                }
            } catch (error) {
                // 恢复按钮状态
                const restartBtn = event.target;
                restartBtn.disabled = false;
                restartBtn.innerHTML = '🔄 重启Registry';
                
                alert('重启失败: ' + error.message);
            }
        }
        
        // 垃圾回收（释放已删除镜像的实际空间）
        async function garbageCollection() {
            if (!confirm('确定要运行垃圾回收吗？这将删除所有未引用的镜像层，真正释放存储空间。')) return;
            
            try {
                // 显示加载状态
                const gcBtn = event.target;
                const originalText = gcBtn.innerHTML;
                gcBtn.disabled = true;
                gcBtn.innerHTML = '🔄 垃圾回收中...';
                
                const response = await fetch(`${API_BASE}/gc`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                const result = await response.json();
                
                // 恢复按钮状态
                gcBtn.disabled = false;
                gcBtn.innerHTML = originalText;
                
                if (response.ok) {
                    let message = `垃圾回收完成！\n\n`;
                    message += `执行命令: ${result.msg || result.message}\n`;
                    message += result.freed_space ? `释放空间: ${result.freed_space}GB\n` : '';
                    message += `详情请查看Registry容器日志`;
                    
                    alert(message);
                    loadData(); // 刷新存储统计
                } else {
                    alert('垃圾回收失败: ' + (result.error || response.statusText));
                }
            } catch (error) {
                // 恢复按钮状态
                const gcBtn = event.target;
                gcBtn.disabled = false;
                gcBtn.innerHTML = '🧹 垃圾回收';
                
                alert('垃圾回收失败: ' + error.message);
            }
        }

        // 快速清理（保留原有快速清理功能）
        async function quickCleanup() {
            if (!confirm('确定要清理临时上传文件吗？这只会删除未完成的临时上传，不会影响现有镜像。')) return;
            
            try {
                const response = await fetch(`${API_BASE}/cleanup`, {
                    method: 'POST'
                });
                const result = await response.json();
                
                if (result.success) {
                    alert(`清理完成: ${result.message}\n删除临时文件数量: ${result.deleted_count || 0}`);
                    loadData(); // 刷新页面
                } else {
                    alert('清理失败: ' + result.error);
                }
            } catch (error) {
                alert('清理失败: ' + error.message);
            }
        }
        
        // 健康检查
        async function healthCheck() {
            try {
                const response = await fetch(`${API_BASE}/health`);
                const result = await response.json();
                alert(`Registry状态: ${result.status}`);
            } catch (error) {
                alert('健康检查失败: ' + error.message);
            }
        }
        
        // 页面加载时自动加载数据并设置卡片点击
        document.addEventListener('DOMContentLoaded', () => {
            console.log('页面加载完成，初始化复制功能检测');
            
            // 立即验证复制功能是否可用
            if (typeof window.copyToClipboard === 'function') {
                console.log('✅ copyToClipboard函数已正确加载（预定义）');
            } else {
                console.error('❌ copyToClipboard函数预定义加载失败，使用后备方案');
            }
            
            loadAllData();
            
            // 页面加载后再次验证复制功能是否可用（通过全局导出）
            setTimeout(() => {
                if (typeof window.copyToClipboard === 'function') {
                    console.log('✅ copyToClipboard函数已正确加载（全局导出）');
                } else {
                    console.error('❌ copyToClipboard函数全局导出失败');
                }
            }, 1000);
        });
        
        // 主数据加载函数（避免与已有的loadData冲突）
        async function loadAllData() {
            await loadStorageStats();
            await loadRepoStats();
            await loadRepositories();
        }
        
        // 全局函数导出
        window.prevPage = prevPage;
        window.nextPage = nextPage;
        window.showMoreTags = showMoreTags;
        
        // 路由追踪栈
        let navigationStack = ['home']; // home, repository_detail, tag_detail
        
        // 返回到首页（统一所有返回操作都回到首页）
        function backToList() {
            fallbackToHome();
        }
        
        // 返回到首页（点击标题触发）
        function backToHome() {
            fallbackToHome();
        }
        
        // 渲染仓库详情页（不重置navigationStack）
        function renderRepositoryDetailPage(repository) {
            // 保留当前导航栈中到repository_detail的路径
            while (navigationStack.length > 0 && navigationStack[navigationStack.length - 1] !== 'repository_detail') {
                navigationStack.pop();
            }
            
            if (navigationStack.length === 0) {
                navigationStack = ['home', 'repository_detail'];
                sessionStorage.setItem('currentRepository', repository);
            } else if (navigationStack[navigationStack.length - 1] !== 'repository_detail') {
                navigationStack.push('repository_detail');
                sessionStorage.setItem('currentRepository', repository);
            }
            
            loadRepositoryDetails(repository);
        }
        
        // 回退到首页（重新加载整个页面）
        function fallbackToHome() {
            navigationStack = ['home'];
            sessionStorage.clear(); // 清空所有sessionStorage
            window.location.reload(); // 重新加载页面回到首页
        }
        
        // loadData别名，兼容现有代码
        window.loadData = loadAllData;
        
        // 复制到剪贴板辅助函数
        function copyToClipboard(text) {
            // 创建临时textarea元素
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.left = '-999999px';
            textarea.style.top = '-999999px';
            document.body.appendChild(textarea);
            
            // 选择和复制文本
            textarea.select();
            textarea.setSelectionRange(0, 99999); // 对于移动设备
            
            try {
                const successful = document.execCommand('copy');
                if (successful) {
                    showToast('✅ Docker命令已复制到剪贴板');
                } else {
                    showToast('❌ 复制失败，请手动复制');
                }
            } catch (err) {
                showToast('❌ 复制失败，请手动复制');
            }
            
            // 清理临时元素
            document.body.removeChild(textarea);
        }

        // 显示Toast提示
        function showToast(message) {
            // 移除现有的toast
            const existingToast = document.querySelector('.copy-toast');
            if (existingToast) {
                existingToast.remove();
            }

            // 创建新的toast
            const toast = document.createElement('div');
            toast.className = 'copy-toast';
            toast.textContent = message;
            
            // 应用样式
            Object.assign(toast.style, {
                position: 'fixed',
                top: '20px',
                right: '20px',
                background: '#28a745',
                color: 'white',
                padding: '12px 20px',
                borderRadius: '6px',
                zIndex: '9999',
                fontSize: '14px',
                boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                animation: 'slideIn 0.3s ease, fadeOut 0.3s ease 2s forwards'
            });

            document.body.appendChild(toast);

            // 3秒后自动移除
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.remove();
                }
            }, 3000);
        }
        
        // 添加CSS动画样式
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes fadeOut {
                from { opacity: 1; }
                to { opacity: 0; transform: translateY(-20px); }
            }
        `;
        document.head.appendChild(style);
        
        // 导出标签详情函数到全局作用域
        window.viewTagDetails = viewTagDetails;
        window.viewRepositoryDetails = viewRepositoryDetails;
        window.renderTagDetailPage = renderTagDetailPage;
        window.copyDockerCommand = copyDockerCommand;
        window.backToList = backToList;
        window.loadRepositories = loadRepositories;
        window.setupCardClicks = setupCardClicks;
        window.deleteTag = deleteTag;
        
        // 导出复制函数到全局作用域（必须在页面关闭前）
        window.copyToClipboard = copyToClipboard;
        window.showToast = showToast;
    </script>
    
    <!-- 页脚版权信息 -->
    <footer id="footer" style="
        text-align: center; 
        padding: 1rem; 
        color: #666; 
        font-size: 0.9rem; 
        border-top: 1px solid #e0e0e0;
        margin-top: 1rem;
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
    ">
        <div style="margin-bottom: 0.2rem;">
            <a href="https://github.com/YunJian101/Docker-Registry-Manager" 
               target="_blank" 
               rel="noopener noreferrer"
               style="color: #667eea; font-weight: 500; text-decoration: none; cursor: pointer;"
               onmouseover="this.style.textDecoration='underline'"
               onmouseout="this.style.textDecoration='none'">
                © 2026 云笺 Ownership
            </a>
        </div>
        <div style="opacity: 0.8; font-size: 0.85rem;">
            Open Source Docker Registry Manager
        </div>
    </footer>
</body>
</html>
    """

@app.route('/api/repositories')
def api_repositories():
    """API: 获取所有仓库（包含空仓库状态）"""
    repositories = registry_client.get_repositories()
    
    # 为每个仓库获取标签信息
    repositories_with_status = []
    for repo in repositories:
        tags = registry_client.get_tags(repo)
        repositories_with_status.append({
            'name': repo,
            'tags': tags,
            'tag_count': len(tags),
            'empty': len(tags) == 0
        })
    
    return jsonify({'repositories': repositories_with_status})

@app.route('/api/repository/<path:repository>/tags')
def api_tags(repository: str):
    """API: 获取仓库的标签"""
    # 解码repository路径
    repository = unquote(repository)
    tags = registry_client.get_tags(repository)
    return jsonify({'tags': tags})

@app.route('/api/repository/<path:repository>/tag/<tag>', methods=['DELETE'])
def api_delete_tag(repository: str, tag: str):
    """API: 删除标签"""
    # 解码repository和tag
    repository = unquote(repository)
    tag = unquote(tag)
    success = registry_client.delete_image(repository, tag)
    return jsonify({'success': success})

@app.route('/api/repository/<path:repository>', methods=['DELETE'])
def api_delete_repository(repository: str):
    """API: 删除整个仓库 - 符合Docker Distribution API V2规范"""
    try:
        repository = unquote(repository)
        deleted_tags = []
        failed_tags = []
        
        # 1. 获取仓库的所有标签
        try:
            tags = registry_client.get_tags(repository)
            logger.info(f"准备删除仓库 {repository} 的 {len(tags)} 个标签")
        except Exception as e:
            logger.error(f"获取仓库标签失败 {repository}: {e}")
            return jsonify({
                'success': False, 
                'error': f'无法获取仓库标签: {str(e)}'
            }), 500
        
        # 2. 删除所有标签（根据Docker Distribution API规范）
        for tag in tags:
            try:
                success = registry_client.delete_image(repository, tag)
                if success:
                    deleted_tags.append(tag)
                    logger.info(f"成功删除标签: {repository}:{tag}")
                else:
                    failed_tags.append(tag)
            except Exception as tag_error:
                logger.error(f"删除标签失败 {repository}:{tag}: {tag_error}")
                failed_tags.append(tag)
        
        # 3. 根据Docker Distribution规范，删除后需要运行垃圾回收才能真正释放空间
        logger.info(f"提醒用户运行垃圾回收以释放存储空间")
        
        # 4. 返回删除结果
        result = {
            'success': True,
            'message': f'仓库 {repository} 删除完成，请运行垃圾回收释放存储空间',
            'repository': repository,
            'total_tags': len(tags),
            'deleted_tags': deleted_tags,
            'failed_tags': failed_tags,
            'deleted_count': len(deleted_tags),
            'official_api_note': '根据Docker Distribution API V2规范，删除manifest后需要运行垃圾回收才能实际释放磁盘空间',
            'gc_command': 'docker exec <registry-container> registry garbage-collect /etc/docker/registry/config.yml'
        }
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"删除仓库失败 {repository}: {e}")
        return jsonify({
            'success': False, 
            'error': f'删除仓库失败: {str(e)}'
        }), 500

@app.route('/api/storage')
def api_storage():
    """API: 获取存储信息 - 计算本地存储目录大小"""
    try:
        # 计算Registry存储目录总大小
        registry_path = Path('/var/lib/registry')
        total_size_bytes = 0
        
        if registry_path.exists():
            # 递归计算目录中所有文件的总大小
            for file_path in registry_path.rglob('*'):
                if file_path.is_file():
                    try:
                        total_size_bytes += file_path.stat().st_size
                    except:
                        pass  # 忽略无法访问的文件
        
        # 获取磁盘空间信息（在容器中可能受限）
        try:
            disk_stats = os.statvfs('/var/lib/registry')
            available_bytes = disk_stats.f_bavail * disk_stats.f_frsize
            total_disk_bytes = disk_stats.f_blocks * disk_stats.f_frsize
            used_percentage = round(100 * (1 - available_bytes / total_disk_bytes), 2)
        except:
            # 如果无法获取磁盘信息，使用默认值
            available_bytes = 0
            total_disk_bytes = total_size_bytes
            used_percentage = 0
        
        repositories = registry_client.get_repositories()
        
        return jsonify({
            'success': True,
            'data': {
                'total_size_bytes': total_size_bytes,
                'total_size_mb': round(total_size_bytes / (1024 * 1024), 2),
                'total_size_gb': round(total_size_bytes / (1024 * 1024 * 1024), 2),
                'used_percentage': used_percentage,
                'available_bytes': available_bytes,
                'available_gb': round(available_bytes / (1024 * 1024 * 1024), 2),
                'repository_count': len(repositories),
                'status': 'healthy'
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/cleanup', methods=['POST'])
def api_cleanup():
    """API: 快速清理（只读安全版）"""
    try:
        # 在只读模式下，不能删除文件系统
        # 返回成功信息但不执行实际操作
        return jsonify({
            'success': True,
            'message': '清理完成（只读模式下仅模拟操作）',
            'note': '前端容器配置为只读模式，所有删除操作必须通过Registry API完成',
            'deleted_count': 0
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clean-empty', methods=['POST'])
def api_clean_empty():
    """API: 清理空仓库 - 实际删除空仓库目录"""
    try:
        import docker
        client = docker.from_env()
        registry_container = client.containers.get('docker_registry')
        
        repositories = registry_client.get_repositories()
        logger.info(f"开始清理空仓库，总仓库数: {len(repositories)}")
        
        empty_repos = []
        deleted_repos = []
        failed_repos = []
        
        # 找出空仓库 - 添加详细日志
        for repo in repositories:
            try:
                tags = registry_client.get_tags(repo)
                if not tags:
                    logger.info(f"发现空仓库: {repo}")
                    empty_repos.append(repo)
                    
                    # 使用正确的Registry容器内部路径（保持仓库的分层结构）
                    # cloudnas/clouddrive2 -> 删除/var/lib/registry/docker/registry/v2/repositories/cloudnas/clouddrive2/
                    actual_path = f"/var/lib/registry/docker/registry/v2/repositories/{repo}"
                    logger.info(f"处理仓库: {repo}, 容器路径: {actual_path}")
                    
                    # 检查目录是否存在 - 使用/bin/sh执行shell命令
                    check_result = registry_container.exec_run(
                        "/bin/sh -c \"if [ -d '" + actual_path + "' ]; then echo 'EXISTS'; ls -la '" + actual_path + "'; else echo 'NOT_EXISTS'; fi\"",
                        stdout=True,
                        stderr=True,
                        demux=True
                    )
                    
                    stdout = check_result.output[0].decode('utf-8') if check_result.output[0] else ""
                    stderr = check_result.output[1].decode('utf-8') if check_result.output[1] else ""
                    
                    logger.info(f"目录检查结果 - 仓库: {repo}, 退出码: {check_result.exit_code}, 输出: {stdout}")
                    
                    if "EXISTS" in stdout and check_result.exit_code == 0:
                        logger.info(f"准备删除目录: {actual_path}")
                        
                        # 执行删除 - 添加详细日志
                        delete_result = registry_container.exec_run(
                            f"rm -rf '{actual_path}'",
                            stdout=True,
                            stderr=True,
                            demux=True
                        )
                        
                        delete_stdout = delete_result.output[0].decode('utf-8') if delete_result.output[0] else ""
                        delete_stderr = delete_result.output[1].decode('utf-8') if delete_result.output[1] else ""
                        
                        logger.info(f"删除结果 - 仓库: {repo}, 退出码: {delete_result.exit_code}, 输出: {delete_stdout}, 错误: {delete_stderr}")
                        
                        if delete_result.exit_code == 0:
                            deleted_repos.append(repo)
                            logger.info(f"✅ 成功删除空仓库目录: {actual_path}")
                        else:
                            failed_repos.append(repo)
                            logger.error(f"❌ 删除空仓库目录失败: {actual_path}, 错误: {delete_stderr}")
                    elif "NOT_EXISTS" in stdout:
                        logger.info(f"仓库目录不存在，跳过删除: {repo}")
                        deleted_repos.append(repo)  # 目录不存在也算成功
                    else:
                        logger.warning(f"目录检查失败，跳过删除: {repo}")
                        failed_repos.append(repo)
            except Exception as e:
                logger.error(f"处理仓库 {repo} 失败: {e}")
                failed_repos.append(repo)
        
        return jsonify({
            'success': True,
            'message': f'清理完成: 成功删除 {len(deleted_repos)} 个空仓库目录，失败 {len(failed_repos)} 个',
            'total_empty': len(empty_repos),
            'deleted_repositories': deleted_repos,
            'failed_repositories': failed_repos,
            'note': '✓ 空仓库目录已从文件系统删除，存储空间已释放。\n⚠️ Registry的API仍可能显示已删除的空仓库（这是正常的缓存行为）',
            'explanation': 'Docker Registry会将仓库名称缓存在其内部数据库中，即使目录被删除，API可能仍会显示。\n这不会影响存储使用，只是UI显示问题。实际存储空间已经释放。'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/gc', methods=['POST'])
def api_garbage_collection():
    """API: 垃圾回收 - 使用Docker SDK执行garbage-collect命令"""
    try:
        # 使用Docker SDK而不是命令行
        import docker
        
        # 创建Docker客户端
        client = docker.from_env()
        
        # 执行垃圾回收命令
        logger.info("执行垃圾回收命令...")
        
        # 在registry容器中执行garbage-collect命令
        container = client.containers.get('docker_registry')
        
        # 执行命令并获取实时输出
        result = container.exec_run(
            "registry garbage-collect /etc/docker/registry/config.yml",
            stdout=True,
            stderr=True,
            demux=True  # 分离stdout和stderr
        )
        
        # 处理输出结果
        exit_code = result.exit_code
        stdout = result.output[0].decode('utf-8') if result.output[0] else ""
        stderr = result.output[1].decode('utf-8') if result.output[1] else ""
        
        logger.info(f"垃圾回收执行完成，退出码: {exit_code}")
        
        if exit_code == 0:
            # 解析输出获取释放的空间信息
            output_lines = stdout.split('\n')
            freed_space_info = ""
            for line in output_lines:
                if 'freed' in line.lower() or 'blobs' in line.lower():
                    freed_space_info = line.strip()
                    break
            
            return jsonify({
                'success': True,
                'message': f'垃圾回收执行成功: {freed_space_info}' if freed_space_info else '垃圾回收执行完成',
                'stdout': stdout,
                'stderr': stderr,
                'returncode': exit_code,
                'freed_space': freed_space_info or '未知'
            })
        else:
            logger.error(f"垃圾回收失败: {stderr}")
            return jsonify({
                'success': False,
                'error': f'垃圾回收执行失败: {stderr}',
                'stdout': stdout,
                'stderr': stderr,
                'returncode': exit_code
            }), 500
        
    except docker.errors.NotFound:
        logger.error("找不到docker_registry容器")
        return jsonify({
            'success': False,
            'error': '找不到docker_registry容器，请确保registry容器正在运行'
        }), 500
    except docker.errors.APIError as e:
        logger.error(f"Docker API错误: {e}")
        return jsonify({
            'success': False,
            'error': f'Docker API错误: {str(e)}'
        }), 500
    except Exception as e:
        logger.error(f"垃圾回收API调用失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/repository/<path:repository>/details')
def api_repository_details(repository: str):
    """获取仓库的详细信息（使用增强的manifest数据）"""
    try:
        repository = unquote(repository)
        tags = registry_client.get_tags(repository)
        
        # 获取每个标签的详细信息
        tag_details = []
        for tag in tags:
            manifest = registry_client.get_manifest(repository, tag)
            # 使用增强的manifest数据字段
            tag_details.append({
                'name': f"{repository}:{tag}",
                'tag': tag,
                'total_size': manifest.get('total_size', 0),  # 使用增强的total_size
                'size': manifest.get('total_size', 0),         # 兼容性字段
                'created': manifest.get('created', '未知'),
                'image_id': manifest.get('image_id', '未知'),   # 使用增强的image_id
                'digest': manifest.get('config', {}).get('digest', '未知').replace('sha256:', ''),  # 计算digest
                'architecture': manifest.get('architecture', '未知'),
                'os': manifest.get('os', '未知')
            })
        
        return jsonify({
            'success': True,
            'repository': repository,
            'tag_count': len(tags),
            'tags': tag_details
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/repository/<path:repository>/tag/<tag>')
def api_tag_details(repository: str, tag: str):
    """获取单个标签的详细信息"""
    try:
        repository = unquote(repository)
        tag = unquote(tag)
        
        # 获取详细的manifest信息
        manifest = registry_client.get_manifest(repository, tag)
        
        # 构建丰富的标签信息
        tag_info = {
            'repository': repository,
            'tag': tag,
            'full_name': f"{repository}:{tag}",
            'size': manifest.get('total_size', 0),
            'created': manifest.get('created', '未知'),
            'image_id': manifest.get('image_id', '未知'),
            'digest': manifest.get('config', {}).get('digest', '未知'),
            'architecture': manifest.get('architecture', '未知'),
            'os': manifest.get('os', '未知'),
            'layers': manifest.get('layers', []),  # 确保返回层信息
            'history': manifest.get('history', []),  # 添加构建历史
            'diff_ids': manifest.get('diff_ids', []),  # 添加diff_ids用于关联
            'mediaType': manifest.get('mediaType', '未知'),
            'schemaVersion': manifest.get('schemaVersion', '未知'),
            'layers_count': len(manifest.get('layers', [])),  # 明确的层数字段
            'has_layers': len(manifest.get('layers', [])) > 0,  # 层存在标志
            'has_history': len(manifest.get('history', [])) > 0  # 历史存在标志
        }
        
        # 尝试获取更详细的config信息
        if 'config' in manifest:
            config_digest = manifest['config'].get('digest', '')
            if config_digest:
                try:
                    config_response = registry_client.session.get(
                        f"{registry_client.base_url}/{repository}/blobs/{config_digest}",
                        timeout=10
                    )
                    if config_response.status_code == 200:
                        config_data = config_response.json()
                        tag_info.update({
                            'config': {
                                'cmd': config_data.get('config', {}).get('Cmd', []),
                                'entrypoint': config_data.get('config', {}).get('Entrypoint', []),
                                'working_dir': config_data.get('config', {}).get('WorkingDir', '/'),
                                'env': config_data.get('config', {}).get('Env', []),
                                'volumes': config_data.get('config', {}).get('Volumes', {}),
                                'user': config_data.get('config', {}).get('User', ''),
                                'labels': config_data.get('config', {}).get('Labels', {}),
                                'exposed_ports': config_data.get('config', {}).get('ExposedPorts', {})
                            }
                        })
                except Exception as e:
                    logger.warning(f"获取详细config信息失败: {e}")
                    pass
        
        logger.info(f"标签详情API返回 - 层数: {tag_info['layers_count']}, 有层: {tag_info['has_layers']}")
        return jsonify({
            'success': True,
            'data': tag_info
        })
    except Exception as e:
        logger.error(f"获取标签详情失败 {repository}:{tag}: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/restart-registry', methods=['POST'])
def api_restart_registry():
    """API: 重启registry容器"""
    try:
        import docker
        client = docker.from_env()
        
        logger.info("正在重启registry容器...")
        container = client.containers.get('docker_registry')
        
        # 重启容器
        container.restart(timeout=30)
        logger.info("registry容器重启成功")
        
        # 等待容器重新启动并检查健康状态
        import time
        time.sleep(3)  # 给容器一些启动时间
        
        # 检查容器状态
        container.reload()  # 重新加载容器状态
        if container.status == 'running':
            return jsonify({
                'success': True,
                'message': '✅ registry容器重启成功',
                'status': container.status,
                'restarted_at': container.attrs['State']['StartedAt']
            })
        else:
            return jsonify({
                'success': False,
                'error': f'容器重启后状态异常: {container.status}',
                'status': container.status
            }), 500
            
    except docker.errors.NotFound:
        logger.error("找不到docker_registry容器")
        return jsonify({
            'success': False,
            'error': '找不到docker_registry容器'
        }), 500
    except Exception as e:
        logger.error(f"重启registry容器失败: {e}")
        return jsonify({
            'success': False,
            'error': f'重启失败: {str(e)}'
        }), 500

@app.route('/api/registry-host')
def api_registry_host():
    """API: 获取配置的registry地址"""
    import os
    registry_host = os.environ.get('REGISTRY_HOST', 'r.ue6.fun:8888')
    return jsonify({
        'success': True,
        'host': registry_host
    })

@app.route('/api/health')
def api_health():
    """健康检查 - 使用registry:2的v2 API端点进行健康检查"""
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        # 使用registry:2的标准v2 API端点进行健康检查
        response = registry_client.session.get(f"{registry_client.base_url}/", timeout=5)
        if response.status_code == 200 or response.status_code == 401:
            # 200表示正常，401表示需要认证但服务正常运行
            status_text = "运行正常" if response.status_code == 200 else "需要认证"
            return jsonify({
                'status': status_text,
                'registry': registry_client.registry_url,
                'api_version': 'Docker Registry API v2',
                'message': '✅ Docker镜像仓库服务运行正常',
                'details': {
                    '服务状态': '正常运行' if response.status_code == 200 else '需要认证授权',
                    '最后检测时间': current_time,
                    '建议': '所有功能均可正常使用' if response.status_code == 200 else '服务需要身份认证'
                }
            })
        else:
            return jsonify({
                'status': '服务异常',
                'registry': registry_client.registry_url,
                'api_version': 'Docker Registry API v2',
                'message': '❌ Docker镜像仓库服务响应异常',
                'details': {
                    '错误原因': f'API返回状态码: {response.status_code}',
                    '最后检测时间': current_time,
                    '建议': f'1. 检查Registry容器是否正常运行\n2. 查看服务日志排查状态码{response.status_code}错误\n3. 重启Registry服务'
                }
            }), 500
    except Exception as e:
        return jsonify({
            'status': '不可用',
            'registry': registry_client.registry_url,
            'api_version': 'Docker Registry API v2',
            'message': '❌ Docker镜像仓库服务不可用',
            'details': {
                '错误原因': f'连接异常: {str(e)}',
                '最后检测时间': current_time,
                '建议': '1. 检查Registry容器是否运行\n2. 检查网络连接是否正常\n3. 查看服务日志排查连接问题\n4. 确认Registry地址配置正确'
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)