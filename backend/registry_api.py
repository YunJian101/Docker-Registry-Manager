#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registry API Client Module
Registry API客户端模块
"""

import requests
import json
import logging
from pathlib import Path
from typing import Dict, List, Any
from urllib.parse import quote
import sys
import os

# 添加backend目录到Python路径
backend_path = '/app/backend'
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# 导入配置
try:
    from config import REGISTRY_BASE_URL
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    try:
        sys.path.append('/app/backend')
        from config import REGISTRY_BASE_URL
    except ImportError:
        REGISTRY_BASE_URL = "http://registry:5000/v2"

logger = logging.getLogger('registry_backend.registry_api')

class RegistryClient:
    """Registry API客户端"""
    
    def __init__(self, registry_url: str = None):
        # 优先使用传入的URL，然后是环境变量，最后是配置文件中的默认值
        base_url = registry_url or REGISTRY_BASE_URL
        
        # 确保基础URL不包含末尾的/v2，我们会自己添加
        self.registry_url = base_url.rstrip('/').rstrip('/v2')
        self.base_url = f"{self.registry_url}/v2"
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RegistryWebUI/1.0',
            'Accept': 'application/json'
        })
    
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
                        # 只有当路径不是根目录(".")时才添加
                        if repository_path and repository_path != ".":
                            found_manifest_repos.add(repository_path)
                            # 避免重复添加
                            if repository_path not in all_repos:
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
                if repo not in seen and repo != "repositories":  # 过滤掉无效的"repositories"条目
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

    def trigger_garbage_collection(self) -> dict:
        """触发垃圾回收"""
        try:
            import docker
            
            # 创建Docker客户端
            client = docker.from_env()
            
            # 直接获取指定的registry容器
            container = client.containers.get('docker_registry')
            
            logger.info("在容器 docker_registry 中执行垃圾回收")
            
            # 执行垃圾回收命令
            result = container.exec_run(
                ["registry", "garbage-collect", "/etc/docker/registry/config.yml"],
                stdout=True,
                stderr=True
            )
            
            # 处理ExecResult对象
            stdout_output = result.output.decode('utf-8') if result.output else ""
            stderr_output = ""
            
            logger.info(f"GC stdout: {stdout_output}")
            
            # 解析GC结果
            success = result.exit_code == 0
            message = "垃圾回收执行完成"
            
            if "eligible for deletion" in stdout_output:
                lines = [line.strip() for line in stdout_output.split('\n') if line.strip()]
                last_message_line = lines[-2] if len(lines) > 1 else lines[-1]
                message = last_message_line
            
            # 解析释放的空间
            freed_bytes = 0
            blobs_deleted = 0
            manifests_deleted = 0
            
            if stdout_output:
                # 查找实际删除的blob
                import re
                delete_matches = re.findall(r'Deleting blob: .*', stdout_output)
                blobs_deleted = len(delete_matches)
                
                # 简单估算释放空间（每个blob平均1MB）
                freed_bytes = blobs_deleted * 1024 * 1024
            
            return {
                'success': success,
                'message': message,
                'container': 'docker_registry',
                'exit_code': result.exit_code,
                'stdout': stdout_output,
                'stderr': stderr_output,
                'blobs_deleted': blobs_deleted,
                'manifests_deleted': manifests_deleted,
                'freed_bytes': freed_bytes
            }
            
        except Exception as e:
            logger.error(f"垃圾回收执行失败: {e}")
            return {
                'success': False,
                'message': str(e),
                'container': 'unknown',
                'error': str(e)
            }

    def delete_image_with_gc(self, repository: str, tag: str) -> dict:
        """删除镜像并触发垃圾回收"""
        try:
            logger.info(f"开始删除镜像并触发垃圾回收: {repository}:{tag}")
            
            # 1. 执行删除操作
            delete_success = self.delete_image(repository, tag)
            
            if not delete_success:
                return {
                    'success': False,
                    'message': '镜像删除失败',
                    'repository': repository,
                    'tag': tag
                }
            
            # 2. 触发垃圾回收
            gc_result = self.trigger_garbage_collection()
            
            return {
                'success': True,
                'message': '镜像删除成功并已触发垃圾回收',
                'repository': repository,
                'tag': tag,
                'gc_result': gc_result,
                'freed_bytes': gc_result.get('freed_bytes', 0) if gc_result.get('success') else 0
            }
            
        except Exception as e:
            logger.error(f"删除镜像并触发GC失败 {repository}:{tag}: {e}")
            return {
                'success': False,
                'message': f'删除镜像并触发GC失败: {str(e)}',
                'repository': repository,
                'tag': tag
            }

    def delete_repository_with_gc(self, repository: str) -> dict:
        """删除整个仓库并触发垃圾回收"""
        try:
            logger.info(f"开始删除仓库并触发垃圾回收: {repository}")
            
            deleted_tags = []
            failed_tags = []
            
            # 1. 获取所有标签
            try:
                tags = self.get_tags(repository)
                logger.info(f"准备删除仓库 {repository} 的 {len(tags)} 个标签")
            except Exception as e:
                logger.error(f"获取仓库标签失败 {repository}: {e}")
                return {
                    'success': False,
                    'message': f'无法获取仓库标签: {str(e)}',
                    'repository': repository
                }
            
            # 2. 删除所有标签
            for tag in tags:
                try:
                    success = self.delete_image(repository, tag)
                    if success:
                        deleted_tags.append(tag)
                        logger.info(f"成功删除标签: {repository}:{tag}")
                    else:
                        failed_tags.append(tag)
                except Exception as tag_error:
                    logger.error(f"删除标签失败 {repository}:{tag}: {tag_error}")
                    failed_tags.append(tag)
            
            # 3. 触发垃圾回收
            gc_result = self.trigger_garbage_collection()
            
            return {
                'success': True,
                'message': f'仓库删除完成并已触发垃圾回收',
                'repository': repository,
                'total_tags': len(tags),
                'deleted_tags': deleted_tags,
                'failed_tags': failed_tags,
                'deleted_count': len(deleted_tags),
                'gc_result': gc_result,
                'freed_bytes': gc_result.get('freed_bytes', 0) if gc_result.get('success') else 0
            }
            
        except Exception as e:
            logger.error(f"删除仓库并触发GC失败 {repository}: {e}")
            return {
                'success': False,
                'message': f'删除仓库并触发GC失败: {str(e)}',
                'repository': repository
            }

    def get_storage_info(self) -> Dict:
        """获取存储信息"""
        try:
            response = self.session.get(f"{self.registry_url}/health", timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return {}

# 创建全局Registry客户端实例
registry_client = RegistryClient()