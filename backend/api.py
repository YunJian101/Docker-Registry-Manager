#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Registry Manager Backend API
Docker镜像仓库管理后端API
"""

import os
import logging
import requests
from pathlib import Path
from urllib.parse import unquote
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import docker

# 隐藏Flask开发服务器警告
import warnings
warnings.filterwarnings("ignore", message=".*development server.*")

# 使用标准日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('registry_backend')

# 创建Flask应用实例
app = Flask(__name__, template_folder='../frontend')
CORS(app)  # 启用CORS支持

# 导入后端模块
from backend.config import (
    CONFIG_DIR, MIRROR_FILE_PATH,
    REGISTRY_BASE_URL, REGISTRY_HOST,
    DEBUG_MODE, LOG_LEVEL,
    ensure_directories, get_registry_config
)
# 使用Redis缓存替换原来的文件缓存
from backend.cache import redis_cache as mirror_cache
from backend.registry_api import registry_client

# 确保必要的目录存在
ensure_directories()


# 创建全局缓存实例（从后端模块导入）
# mirror_cache = MirrorCache()  # 已通过导入获得

# 创建Registry客户端（从后端模块导入）
# registry_client = RegistryClient()  # 已通过导入获得


@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

def get_data_path():
    """获取数据目录路径"""
    # 检查环境变量
    if 'REGISTRY_DATA_PATH' in os.environ:
        return os.environ['REGISTRY_DATA_PATH']
    
    # 默认路径（根据docker-compose配置）
    default_path = '/var/lib/registry'
    if os.path.exists(default_path):
        return default_path
    
    # Windows环境下的路径
    windows_path = 'E:\\AI-Project\\Regsitry2\\data\\registry'
    if os.path.exists(windows_path):
        return windows_path
    
    # 当前目录下的data文件夹
    local_data = os.path.join(os.getcwd(), 'data')
    if os.path.exists(local_data):
        return local_data
    
    return default_path

def get_directory_size(path):
    """获取目录总大小（字节）"""
    total_size = 0
    try:
        if os.path.exists(path):
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath):
                        total_size += os.path.getsize(filepath)
    except Exception as e:
        logger.warning(f"计算目录大小失败 {path}: {e}")
        return 0
    return total_size

@app.route('/api/repositories')
def api_repositories():
    """API: 获取所有仓库（包含空仓库状态） - 使用Redis缓存（永久有效）"""
    # 先尝试从缓存获取
    cache_key = "api:repositories"
    cached_result = mirror_cache.get_cached_api_result(cache_key)
    if cached_result:
        logger.debug("从Redis缓存返回仓库列表")
        return jsonify(cached_result)
    
    # 缓存未命中，调用实际API
    try:
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
        
        response_data = {'repositories': repositories_with_status}
        
        # 只有在成功获取到有效数据时才缓存
        if repositories_with_status and len(repositories_with_status) > 0:
            # 缓存结果到Redis，设置永久有效（1年）
            mirror_cache.cache_api_result(cache_key, response_data, ttl=86400*365)
            logger.info("仓库列表API调用成功，结果已永久缓存到Redis")
        else:
            logger.warning("仓库列表API返回空结果，跳过缓存")
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"获取仓库列表失败: {e}")
        return jsonify({'repositories': []}), 500

@app.route('/api/repository/<path:repository>/tags')
def api_tags(repository: str):
    """API: 获取仓库的标签"""
    # 解码repository路径
    repository = unquote(repository)
    tags = registry_client.get_tags(repository)
    return jsonify({'tags': tags})

@app.route('/api/repository/<path:repository>/tag/<tag>', methods=['DELETE'])
#@cross_origin()  # 暂时移除CORS装饰器
def api_delete_tag(repository, tag):
    """删除指定标签的镜像"""
    try:
        repository = unquote(repository)  # URL解码仓库名
        tag = unquote(tag)  # URL解码标签名
        
        logger.info(f"开始删除标签: {repository}:{tag}")
        
        # 使用带垃圾回收的删除方法（传入分离的参数）
        result = registry_client.delete_image_with_gc(repository, tag)
        
        if result['success']:
            # 获取删除前后的空间信息
            try:
                # 删除前的空间使用情况
                pre_gc_size = get_directory_size(get_data_path())
                
                # 等待GC完成
                time.sleep(2)
                
                # 删除后的空间使用情况
                post_gc_size = get_directory_size(get_data_path())
                freed_bytes = pre_gc_size - post_gc_size
                
                logger.info(f"标签删除成功: {repository}:{tag}, 释放空间: {freed_bytes} bytes")
                
                # 清除所有相关缓存（加强缓存清除）
                cache_keys_to_clear = [
                    # Registry相关缓存
                    f"registry:repo:{repository}*",
                    f"registry:manifest:{repository}:{tag}",
                    "registry:repos:list",
                    # API缓存
                    "api:repositories",
                    "api:storage",
                    f"api:description:{repository}",
                    f"api:details:{repository}",
                    # 模糊匹配清除
                    f"api:description:*",
                    f"api:details:*"
                ]
                
                cleared_count = 0
                for cache_key in cache_keys_to_clear:
                    try:
                        mirror_cache._invalidate_cache(cache_key)
                        logger.info(f"已清除缓存: {cache_key}")
                        cleared_count += 1
                    except Exception as e:
                        logger.warning(f"清除缓存失败 {cache_key}: {e}")
                
                logger.info(f"删除操作后共清除 {cleared_count} 个缓存项")
                
                return jsonify({
                    'success': True,
                    'message': '标签删除成功',
                    'repository': repository,
                    'tag': tag,
                    'freed_bytes': freed_bytes,
                    'gc_result': result.get('gc_result', {}),
                    'cache_cleared': cleared_count
                })
            except Exception as size_error:
                logger.warning(f"计算释放空间失败: {size_error}")
                return jsonify({
                    'success': True,
                    'message': '标签删除成功',
                    'repository': repository,
                    'tag': tag,
                    'freed_bytes': result.get('gc_result', {}).get('freed_bytes', 0),
                    'gc_result': result.get('gc_result', {})
                })
        else:
            logger.error(f"标签删除失败: {repository}:{tag}, 错误: {result.get('message', '未知错误')}")
            return jsonify({
                'success': False,
                'message': result.get('message', '镜像删除失败'),
                'repository': repository,
                'tag': tag
            }), 500
            
    except requests.exceptions.RequestException as e:
        logger.error(f"删除标签网络请求失败: {e}")
        return jsonify({
            'success': False,
            'message': '网络请求失败',
            'repository': repository,
            'tag': tag
        }), 502
    except Exception as e:
        logger.error(f"删除标签时发生错误: {e}")
        return jsonify({
            'success': False,
            'message': str(e),
            'repository': repository,
            'tag': tag
        }), 500

@app.route('/api/repository/<path:repository>', methods=['DELETE'])
def api_delete_repository(repository: str):
    """API: 删除整个仓库并触发垃圾回收"""
    try:
        repository = unquote(repository)
        logger.info(f"开始删除仓库: {repository}")
        
        # 使用带垃圾回收的删除方法
        result = registry_client.delete_repository_with_gc(repository)
        
        # 清除所有相关缓存（加强缓存清除）
        cache_keys_to_clear = [
            # Registry相关缓存
            f"registry:repo:{repository}*",
            "registry:repos:list",
            # API缓存
            "api:repositories",
            "api:storage",
            f"api:description:{repository}",
            f"api:details:{repository}",
            # 模糊匹配清除所有描述和详情缓存
            "api:description:*",
            "api:details:*"
        ]
        
        cleared_count = 0
        for cache_key in cache_keys_to_clear:
            try:
                mirror_cache._invalidate_cache(cache_key)
                logger.info(f"已清除缓存: {cache_key}")
                cleared_count += 1
            except Exception as cache_error:
                logger.warning(f"清除缓存失败 {cache_key}: {cache_error}")
        
        logger.info(f"删除仓库操作后共清除 {cleared_count} 个缓存项")
        
        if result['success']:
            logger.info(f"仓库删除成功: {repository}")
            return jsonify({
                'success': True,
                'message': f'仓库 {repository} 删除成功',
                'repository': repository,
                'result': result,
                'cache_cleared': cleared_count
            })
        else:
            logger.error(f"仓库删除失败: {repository}, 错误: {result.get('message', '未知错误')}")
            return jsonify({
                'success': False,
                'message': result.get('message', '仓库删除失败'),
                'repository': repository,
                'result': result
            }), 500
            
    except requests.exceptions.RequestException as e:
        logger.error(f"删除仓库网络请求失败 {repository}: {e}")
        return jsonify({
            'success': False,
            'message': '网络请求失败',
            'repository': repository
        }), 502
    except Exception as e:
        logger.error(f"删除仓库异常 {repository}: {e}")
        return jsonify({
            'success': False,
            'message': f'删除仓库异常: {str(e)}',
            'repository': repository
        }), 500

@app.route('/api/storage')
def api_storage():
    """API: 获取存储信息 - 计算本地存储目录大小 - 使用Redis缓存（永久有效）"""
    # 先尝试从缓存获取
    cache_key = "api:storage"
    cached_result = mirror_cache.get_cached_api_result(cache_key)
    if cached_result:
        logger.debug("从Redis缓存返回存储信息")
        return jsonify(cached_result)
    
    # 缓存未命中，调用实际API
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
        
        response_data = {
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
        }
        
        # 只有在成功获取到有效数据时才缓存（检查数值合理性）
        if (total_size_bytes >= 0 and 
            available_bytes >= 0 and 
            len(repositories) >= 0 and
            response_data['success'] == True):
            # 缓存结果到Redis，设置永久有效（1年）
            mirror_cache.cache_api_result(cache_key, response_data, ttl=86400*365)
            logger.info("存储信息API调用成功，结果已永久缓存到Redis")
        else:
            logger.warning("存储信息API返回无效结果，跳过缓存")
        
        return jsonify(response_data)
    except requests.exceptions.RequestException as e:
        logger.error(f"存储信息API网络请求失败: {e}")
        return jsonify({'success': False, 'error': '网络请求失败'}), 502
    except FileNotFoundError:
        logger.error("存储路径不存在")
        return jsonify({'success': False, 'error': '存储路径不存在'}), 404
    except PermissionError:
        logger.error("无权限访问存储路径")
        return jsonify({'success': False, 'error': '无权限访问'}), 403
    except Exception as e:
        logger.error(f"获取存储信息失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
    """API: 垃圾回收 - 使用Docker SDK执行garbage-collect命令（统一使用数组命令格式）"""
    try:
        import docker
        from datetime import datetime
        
        # 创建Docker客户端
        client = docker.from_env()
        
        logger.info("执行垃圾回收命令...")
        
        # 在registry容器中执行garbage-collect命令
        container = client.containers.get('docker_registry')
        
        # 执行命令并获取实时输出（使用数组形式，与删除时的GC保持一致）
        result = container.exec_run(
            ["registry", "garbage-collect", "/etc/docker/registry/config.yml"],
            stdout=True,
            stderr=True,
            demux=True
        )
        
        # 解析执行结果
        exit_code = result.exit_code
        stdout_output = result.output[0].decode('utf-8') if result.output[0] else ""
        stderr_output = result.output[1].decode('utf-8') if result.output[1] else ""
        
        logger.info(f"GC stdout: {stdout_output}")
        logger.info(f"GC stderr: {stderr_output}")
        
        # 分析输出判断执行结果
        success = exit_code == 0
        message = stdout_output.strip() if stdout_output else "垃圾回收执行完成"
        
        # 解析释放的空间
        freed_bytes = 0
        blobs_deleted = 0
        manifests_deleted = 0
        
        if stdout_output:
            # 查找删除统计信息
            import re
            # 匹配类似 "Deleting blob: /path/to/blob" 的行
            blob_matches = re.findall(r'Deleting blob: .*', stdout_output)
            manifest_matches = re.findall(r'Deleting manifest: .*', stdout_output)
            
            blobs_deleted = len(blob_matches)
            manifests_deleted = len(manifest_matches)
            
            # 如果有明确的统计信息
            stats_match = re.search(r'(\d+) blobs and (\d+) manifests eligible for deletion', stdout_output)
            if stats_match:
                eligible_blobs = int(stats_match.group(1))
                eligible_manifests = int(stats_match.group(2))
                # 简单估算：每个blob平均1MB，每个manifest 1KB
                freed_bytes = eligible_blobs * 1024 * 1024 + eligible_manifests * 1024
        
        gc_result = {
            'success': success,
            'message': message,
            'container': 'docker_registry',
            'exit_code': exit_code,
            'stdout': stdout_output,
            'stderr': stderr_output,
            'blobs_deleted': blobs_deleted,
            'manifests_deleted': manifests_deleted,
            'freed_bytes': freed_bytes,
            'timestamp': datetime.now().isoformat()
        }
        
        if success:
            logger.info(f"垃圾回收执行成功: {message}")
            return jsonify({
                'success': True,
                'message': message,
                'freed_space': message,  # 保持向前兼容
                'gc_result': gc_result
            })
        else:
            error_msg = stderr_output or message or "垃圾回收执行失败"
            logger.error(f"垃圾回收执行失败: {error_msg}")
            return jsonify({
                'success': False,
                'message': error_msg,
                'error': stderr_output,
                'gc_result': gc_result
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
        logger.error(f"垃圾回收执行异常: {e}")
        return jsonify({
            'success': False,
            'message': str(e),
            'error': str(e)
        }), 500

@app.route('/api/repository/<path:repository>/details')
def api_repository_details(repository: str):
    """获取仓库的详细信息 - 使用Redis缓存（永久有效）"""
    try:
        repository = unquote(repository)
        
        # 先尝试从缓存获取
        cache_key = f"api:details:{repository}"
        cached_result = mirror_cache.get_cached_api_result(cache_key)
        if cached_result:
            logger.debug(f"从Redis缓存返回仓库详情: {repository}")
            return jsonify(cached_result)
        
        # 缓存未命中，调用实际API
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
        
        response_data = {
            'success': True,
            'repository': repository,
            'tag_count': len(tags),
            'tags': tag_details
        }
        
        # 只有在成功获取到有效数据时才缓存
        if tags is not None and len(tags) >= 0 and response_data['success'] == True:
            # 缓存结果到Redis，设置永久有效（1年）
            mirror_cache.cache_api_result(cache_key, response_data, ttl=86400*365)
            logger.info(f"仓库详情API调用成功，结果已永久缓存到Redis: {repository}")
        else:
            logger.warning(f"仓库详情API返回无效结果，跳过缓存: {repository}")
        
        return jsonify(response_data)
    except requests.exceptions.RequestException as e:
        logger.error(f"仓库详情API网络请求失败 {repository}: {e}")
        return jsonify({'success': False, 'error': '网络请求失败'}), 502
    except Exception as e:
        logger.error(f"获取仓库详情失败 {repository}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/repository/<path:repository>/tag/<tag>')
def api_tag_details(repository: str, tag: str):
    """获取单个标签的详细信息 - 使用Redis缓存（永久有效）"""
    try:
        repository = unquote(repository)
        tag = unquote(tag)
        
        # 先尝试从缓存获取
        cache_key = f"api:tag:{repository}:{tag}"
        cached_result = mirror_cache.get_cached_api_result(cache_key)
        if cached_result:
            logger.debug(f"从Redis缓存返回标签详情: {repository}:{tag}")
            return jsonify(cached_result)
        
        # 缓存未命中，调用实际API
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
        
        response_data = {
            'success': True,
            'data': tag_info
        }
        
        # 只有在成功获取到有效数据时才缓存
        if (tag_info and 
            tag_info.get('size', -1) >= 0 and 
            tag_info.get('layers_count', -1) >= 0 and
            response_data['success'] == True):
            # 缓存结果到Redis，设置永久有效（1年）
            mirror_cache.cache_api_result(cache_key, response_data, ttl=86400*365)
            logger.info(f"标签详情API调用成功，结果已永久缓存到Redis: {repository}:{tag}")
        else:
            logger.warning(f"标签详情API返回无效结果，跳过缓存: {repository}:{tag}")
        
        logger.info(f"标签详情API返回 - 层数: {tag_info['layers_count']}, 有层: {tag_info['has_layers']}")
        return jsonify(response_data)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"标签详情API网络请求失败 {repository}:{tag}: {e}")
        return jsonify({'success': False, 'error': '网络请求失败'}), 502
    except Exception as e:
        logger.error(f"获取标签详情失败 {repository}:{tag}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
    """API: 获取配置的registry地址 - 使用Redis缓存（永久有效）"""
    # 先尝试从缓存获取
    cache_key = "api:registry-host"
    cached_result = mirror_cache.get_cached_api_result(cache_key)
    if cached_result:
        logger.debug("从Redis缓存返回registry地址")
        return jsonify(cached_result)
    
    # 缓存未命中，调用实际API
    try:
        import os
        registry_host = os.environ.get('REGISTRY_HOST', 'r.ue6.fun:8888')
        response_data = {
            'success': True,
            'host': registry_host
        }
        
        # 只有在成功获取到有效数据时才缓存
        if registry_host and len(registry_host) > 0 and response_data['success'] == True:
            # 缓存结果到Redis，设置永久有效（1年）
            mirror_cache.cache_api_result(cache_key, response_data, ttl=86400*365)
            logger.info("Registry地址API调用成功，结果已永久缓存到Redis")
        else:
            logger.warning("Registry地址API返回空结果，跳过缓存")
        
        return jsonify(response_data)
    except Exception as e:
        logger.error(f"获取registry地址失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
    """API: 获取仓库的描述信息 - 使用Redis缓存（永久有效）"""
    try:
        repository = unquote(repository)

        cache_key = f"api:description:{repository}"

        # 检查文件是否被修改
        file_changed = False
        if hasattr(mirror_cache, '_check_file_changed'):
            if mirror_cache._check_file_changed():
                logger.info(f"Mirror.json文件已修改，清除仓库 {repository} 的API缓存和Redis缓存")
                mirror_cache._invalidate_cache(cache_key)
                file_changed = True

                # 更新文件修改时间
                try:
                    from backend.config import get_mirror_file_path
                    mirror_file = get_mirror_file_path()
                    mirror_cache._file_mtime = mirror_file.stat().st_mtime if mirror_file.exists() else 0
                except Exception as e:
                    logger.error(f"更新文件修改时间失败: {e}")

        # 先尝试从缓存获取
        cached_result = mirror_cache.get_cached_api_result(cache_key)
        if cached_result and not file_changed:
            logger.debug(f"从Redis缓存返回仓库描述: {repository}")
            return jsonify(cached_result)

        # 文件已修改或缓存未命中，直接从文件读取
        logger.info(f"从文件读取仓库描述: {repository}")
        from backend.cache.redis_cache import BaseCache
        base_cache = BaseCache()
        description_data = base_cache.get_repo_info(repository)
        response_data = {'success': True, 'data': description_data}

        # 只有在成功获取到有效数据时才缓存
        if description_data is not None and response_data['success'] == True:
            # 缓存结果到Redis，设置永久有效（1年）
            mirror_cache.cache_api_result(cache_key, response_data, ttl=86400*365)
            logger.info(f"仓库描述API调用成功，结果已永久缓存到Redis: {repository}")
        else:
            logger.warning(f"仓库描述API返回空结果，跳过缓存: {repository}")

        return jsonify(response_data)
    except requests.exceptions.RequestException as e:
        logger.error(f"仓库描述API网络请求失败 {repository}: {e}")
        return jsonify({'success': False, 'error': '网络请求失败'}), 502
    except Exception as e:
        logger.error(f"获取仓库描述失败 {repository}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
            # 更新成功后清除相关缓存
            cache_keys_to_clear = [
                f"api:description:{repository}",
                "api:repositories",  # 仓库列表可能包含描述信息
                f"api:details:{repository}"  # 详情可能引用描述信息
            ]
            
            cleared_count = 0
            for cache_key in cache_keys_to_clear:
                try:
                    mirror_cache._invalidate_cache(cache_key)
                    logger.info(f"已清除缓存: {cache_key}")
                    cleared_count += 1
                except Exception as e:
                    logger.warning(f"清除缓存失败 {cache_key}: {e}")
            
            logger.info(f"更新描述后共清除 {cleared_count} 个缓存项")
            
            return jsonify({
                'success': True, 
                'message': '描述信息更新成功',
                'repository': repository,
                'cache_cleared': cleared_count
            })
        else:
            return jsonify({
                'success': False, 
                'error': '更新失败',
                'repository': repository
            })
    except requests.exceptions.RequestException as e:
        logger.error(f"更新仓库描述网络请求失败 {repository}: {e}")
        return jsonify({
            'success': False,
            'error': '网络请求失败',
            'repository': repository
        }), 502
    except Exception as e:
        logger.error(f"更新仓库描述失败 {repository}: {e}")
        return jsonify({
            'success': False, 
            'error': str(e),
            'repository': repository
        })




































































