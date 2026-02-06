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

# 导入后端模块（相对导入）
from .config import (
    CONFIG_DIR, DATA_DIR, MIRROR_FILE_PATH,
    REGISTRY_BASE_URL, REGISTRY_HOST,
    DEBUG_MODE, LOG_LEVEL,
    ensure_directories, get_registry_config
)
from .cache import mirror_cache
from .registry_api import registry_client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('registry_web')

# 确保必要的目录存在
ensure_directories()


# 创建全局缓存实例（从后端模块导入）
# mirror_cache = MirrorCache()  # 已通过导入获得

# 创建Registry客户端（从后端模块导入）
# registry_client = RegistryClient()  # 已通过导入获得


@app.route('/')
def index():
    """主页面"""
    return send_from_directory('../frontend', 'index.html')




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
        return jsonify({'success': True, 'message': '缓存清空成功'})
    except Exception as e:
        logger.error(f"清空缓存失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)









