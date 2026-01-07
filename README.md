# Docker Registry Web UI

## 📖 项目概述

Docker Registry Web UI 是一个专业的开源Docker镜像仓库管理系统，基于Python Flask框架开发，提供直观的Web界面来管理官方的Docker Registry容器。该项目旨在简化私有Docker镜像仓库的日常管理和维护工作。

### 🎯 核心价值
- **简化管理**: 无需命令行操作，图形化界面管理镜像
- **快速部署**: Docker Compose一键部署
- **轻量高效**: 后端依赖官方registry:2容器，资源占用低
- **安全保障**: 完善的操作确认和权限控制

## 🏗️ 系统架构

### 技术栈
- **后端**: Python 3.9 + Flask 2.3.3
- **前端**: 原生JavaScript + HTML5 + CSS3
- **数据库**: 文件系统存储 + JSON配置
- **容器**: Docker + Docker Compose
- **缓存**: MirrorCache内存缓存系统

### 架构图
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Web前端界面    │◄──►│   Flask后端API    │◄──►│  Registry容器    │
│  (响应式设计)   │    │  (RESTful接口)   │    │ (registry:2)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                              ▼
                      ┌─────────────────┐
                      │  文件系统存储    │
                      │ (镜像数据+配置)  │
                      └─────────────────┘
```

## 📦 功能特性

### 🗂️ 镜像管理
- **仓库浏览**: 查看所有镜像仓库和标签信息
- **镜像详情**: 显示镜像大小、架构、创建时间等详细信息
- **标签操作**: 支持单个删除镜像标签
- **智能排序**: 自动识别最新版本和常用标签

### 💾 存储管理
- **空间监控**: 实时显示存储使用情况和磁盘空间
- **垃圾回收**: 清理未引用的镜像层，释放存储空间
- **空仓库清理**: 自动识别并清理没有标签的仓库
- **存储统计**: 详细的存储使用统计报表

### 🔧 系统管理
- **健康检查**: 监控Registry服务状态
- **容器重启**: 支持Registry容器重启操作
- **配置管理**: 配置文件管理
- **日志查看**: 操作日志和错误日志记录

### 🌐 Web界面特性
- **响应式设计**: 完美适配桌面和移动设备
- **卡片布局**: 直观的镜像仓库展示
- **实时刷新**: 自动更新镜像状态
- **操作确认**: 重要操作二次确认机制

## 🎨 UI页面介绍

### 主页面 (Dashboard)
**主要组件：**
- **仪表板卡片**: 显示存储使用情况、仓库数量、健康状态统计（聚合多数据源自动生成）
- **仓库列表**: 卡片式展示所有镜像仓库，支持搜索和筛选（从Registry API实时获取）
- **快速操作**: 一键垃圾回收、健康检查、清理空仓库（调用后端管理API）

**数据来源说明**：
- **聚合数据展示**：整合Registry状态、存储信息、仓库统计等多维度数据
- **实时同步**：页面自动刷新，保持数据与Registry服务同步
- **智能筛选**：支持按仓库名、状态、标签数量等多条件筛选
- **操作便捷**：一键式操作，无需复杂配置

### 镜像仓库详情页
**页面内容：**
- **仓库信息**: 名称、描述、创建时间、分类标签（部分来自Mirror.json配置文件，需手动维护）
  - 当分类或标签为空时，相关显示区域自动隐藏
- **标签列表**: 按时间戳排序的标签展示（自动从Registry提取）
- **存储信息**: 镜像大小、架构、操作系统详情（自动从镜像manifest提取）
- **Docker命令**: 自动生成pull/push命令，支持一键复制（基于配置生成）

**数据来源说明**：
- **手动配置数据**：仓库简介、分类、描述标签等需要手动在Mirror.json中配置，计划未来接入AI自动生成
- **自动提取数据**：镜像大小、架构、操作系统、环境变量、分层信息等从镜像manifest自动解析提取

**交互功能：**
- **标签管理**: 查看标签详情、删除单个标签（支持批量选择）
- **命令生成**: 自动生成Docker pull/push命令，支持一键复制到剪贴板  
- **分层查看**: 展开查看镜像的层级结构和各层详细信息
- **刷新同步**: 手动刷新按钮确保数据实时性
- **导航操作**: 返回列表、查看详情等页面导航功能

### 标签详情页
**详细信息展示：**
- **镜像元数据**: 完整manifest信息解析（自动从Docker Registry API提取）
- **层级结构**: 镜像Layer详细信息（自动解析manifest文件层信息）
- **环境变量**: 运行时配置信息（从镜像配置文件中提取）
- **执行历史**: build历史和变更记录（从镜像元数据中获取）

**数据来源说明**：
- **自动解析数据**：所有信息均从Docker镜像的manifest和配置文件自动解析，无需手动配置
- **实时获取**：每次访问时从Registry服务实时获取最新数据
- **技术标准**：遵循Docker镜像v2 schema规范解析

### 系统管理页面
**管理功能：**
- **存储监控**: 磁盘使用率和空间预警（实时监控文件系统和Registry存储）
- **健康检查**: Registry服务状态监控（通过API端点连通性检测）
- **垃圾回收**: 一键清理存储空间（调用Registry garbage-collect命令）
- **容器管理**: Registry容器重启和状态查看（使用Docker SDK操作）


**数据来源说明**：
- **系统监控数据**：实时获取文件系统和Registry服务状态
- **Docker操作**：通过Docker SDK执行容器管理和垃圾回收
- **API检测**：通过Registry API测试服务健康状态
- **自动刷新**：所有数据显示保持实时更新



## 🚀 快速开始

### 环境要求
- Docker Engine 20.10+
- Docker Compose 1.29+
- 磁盘空间: 至少50GB可用空间
- 内存: 2GB RAM

### 一键部署
```bash
# 克隆项目
git clone https://github.com/YunJian101/Docker-Registry-Manager
cd Docker-Registry-Manager

# 启动服务（根据您的Docker Compose版本选择对应的命令）
docker-compose up -d    # 传统版本（带连字符）
# 或
docker compose up -d    # 新版本（无连字符，需要Docker Desktop 2.4.0+）

# 查看服务状态
docker-compose ps       # 传统版本
# 或  
docker compose ps       # 新版本
```

### 访问地址
- **Web界面**: http://localhost:5001 (Web管理界面端口)
- **Registry API**: http://localhost:5000/v2/ (Registry容器API端口)
- **Docker推送/拉取端口**: 5000 (用于`docker push/pull`操作)

## 📘 使用教程

### 基本工作流程
1. **推送镜像**:
   ```bash
   docker pull nginx:latest
   docker tag nginx:latest localhost:5000/nginx:latest
   docker push localhost:5000/nginx:latest
   ```

2. **管理镜像**:
   - 访问Web界面 http://localhost:5001
   - 浏览/搜索镜像仓库
   - 查看镜像详情
   - 删除不需要的镜像标签

3. **监控存储**:
   - 定期检查存储使用情况
   - 清理未使用的镜像层

## ⚠️ 重要注意事项

1. **安全配置**:
   - 生产环境必须启用HTTPS
   - 配置适当的防火墙规则
   - 定期备份数据目录

2. **性能优化**:
   - 大型仓库建议配置Redis缓存
   - 定期运行垃圾回收

3. **网络配置**:
   - 确保Registry端口(5000)不被公开暴露
   - Web UI端口(5001)应配置访问控制

### 首次配置
1. 从Docker Hub拉取镜像，标记并推送到私有Registry:
```bash
docker pull nginx:latest
docker tag nginx:latest localhost:5000/nginx:latest
docker push localhost:5000/nginx:latest
```

2. 在Web界面中查看镜像

## 📁 项目结构

**精简核心文件 (仅包含构建必需文件):**
```
Docker-Registry-Manager/
├── registry_web.py          # 主应用程序 (3689行代码)
├── docker-compose.yml       # Docker编排配置
├── Dockerfile.webui         # Web UI容器镜像构建
├── requirements.txt         # Python依赖
└── README.md               # 项目文档
```

**自动生成的目录 (运行时创建):**
- `data/` - Registry数据存储 (由docker-compose自动创建)
- `config/` - 配置文件目录 (由docker-compose自动创建)

## 🔧 详细配置

### 环境变量配置
```yaml
# docker-compose.yml 环境变量
REGISTRY_BASE_URL: "http://registry:5000"    # Registry内部服务地址
REGISTRY_HOST: "your-registry-domain.com:5000"  # Web UI显示的Registry外部地址（仅影响显示的镜像拉取命令前缀）
PYTHONUNBUFFERED: "1"                       # Python输出缓冲
DOCKER_HOST: "unix:///var/run/docker.sock"  # Docker套接字
```

### Registry配置
```yaml
# Registry容器配置
REGISTRY_STORAGE_DELETE_ENABLED: "true"      # 启用删除功能
REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY: "/var/lib/registry"
```

## 🔌 API接口文档

### 镜像管理接口
| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/repositories` | 获取所有仓库列表 |
| GET | `/api/repository/{repo}/tags` | 获取仓库标签列表 |
| GET | `/api/repository/{repo}/details` | 获取仓库详细信息 |
| GET | `/api/repository/{repo}/tag/{tag}` | 获取标签详细信息 |
| DELETE | `/api/repository/{repo}/tag/{tag}` | 删除镜像标签 |

### 系统管理接口
| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/storage` | 获取存储统计信息 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/gc` | 垃圾回收 |
| POST | `/api/clean-empty` | 清理空仓库 |
| POST | `/api/restart-registry` | 重启Registry |

### 配置管理接口
| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/repository/{repo}/description` | 获取仓库描述 |
| POST | `/api/repository/{repo}/description` | 更新仓库描述 |
| GET | `/api/mirror/cache/status` | 缓存状态查询 |
| POST | `/api/mirror/cache/clear` | 清空缓存 |

## 💡 核心功能详解

### MirrorCache缓存系统
系统使用三级优先级缓存机制，提升数据读取效率：
- **内存缓存**: 运行时数据缓存，提升响应速度
- **文件缓存**: Mirror.json持久化存储
- **缓存失效**: 文件修改时间检测机制

### 镜像发现机制
系统采用双重发现策略:
1. **文件系统扫描**: 直接读取Registry存储目录
2. **API探测**: 调用Registry V2 API获取仓库信息

## 🛠️ 运维指南

### 日常维护
```bash
# 查看服务状态
docker-compose ps       # 传统版本
# 或
docker compose ps       # 新版本

# 查看日志
docker-compose logs -f web-ui    # 传统版本
# 或
docker compose logs -f web-ui    # 新版本

docker-compose logs -f registry  # 传统版本
# 或
docker compose logs -f registry  # 新版本

# 备份数据
tar -czf registry-backup-$(date +%Y%m%d).tar.gz data/registry/
```

### 故障排查
常见问题处理:
1. **Registry连接失败**: 检查网络和防火墙设置
2. **存储空间不足**: 运行垃圾回收清理空间
3. **权限错误**: 验证Docker socket权限
4. **镜像标签上传失败**: 删除某个标签后请点击首页的重启后端按钮，重启后才可以重新上传，这仍是Registry后端缓存问题，该缓存目前只能通过重启后端刷新，非前端UI问题，所有的docker pull 和docker push操作均为后端处理，前端并不涉及

## 📝 Mirror.json 配置文件说明

`Mirror.json` 是项目核心的仓库描述配置文件，用于存储和管理所有镜像仓库的元数据信息。

**首次自动生成条件**：
1. 仓库中已有镜像存在（需先通过`docker push`推送镜像到Registry）
2. 在Web UI界面进行以下交互操作：
   - 查看镜像仓库列表（触发仓库发现API）
   - 访问标签详情页（加载仓库详情）
   - 刷新仓库数据（手动触发同步）
3. 系统检测到Mirror.json文件不存在时自动创建
4. 自动包含以下内容：
   - 已存在的所有仓库名称
   - 基础描述模板
   - 默认分类（unknown）
   - 空标签列表

**时间延迟说明**：
- **生成延迟**: 配置文件生成可能有短暂延迟
- **缓存同步**: 生成后需要缓存同步时间才能在所有页面生效
- **实时性**: 建议操作后稍等片刻查看配置生效情况

**生成流程**：
1. 系统扫描Registry存储目录发现仓库
2. 检查/app/config/Mirror.json文件是否存在
3. 如不存在，创建默认配置文件结构
4. 将发现的仓库添加到repositories数组
5. 保存文件到/app/config目录

### 配置文件结构
```json
{
    "scheme_version": "1.0",       // 配置版本号
    "description": "Docker镜像仓库描述信息",  // 全局描述
    "created_at": "2026-01-06T16:04:00Z",  // 创建时间
    "repositories": [              // 仓库列表
        {
            "name": "nginx",  // 仓库名称
            "description": "高性能HTTP和反向代理服务器",  // 仓库描述
            "category": "web-server",  // 分类标签
            "tags": ["高性能", "反向代理", "负载均衡"]  // 仓库描述标签（非镜像版本）
        },
        {
            "name": "mysql",  // 仓库名称
            "description": "流行的开源关系型数据库",  // 仓库描述
            "category": "database",  // 分类标签
            "tags": ["关系型", "事务", "ACID"]  // 仓库描述标签（非镜像版本）
        },
        {
            "name": "redis",  // 仓库名称
            "description": "高性能键值对内存数据库",  // 仓库描述
            "category": "cache",  // 分类标签
            "tags": ["内存数据库", "缓存", "NoSQL"]  // 仓库描述标签（非镜像版本）
        },
        {
            "name": "cloudnas/clouddrive2",  // 仓库名称
            "description": "这是一个Docker镜像仓库",  // 仓库描述
            "category": "unknown",  // 分类标签
            "tags": []              // 标签列表（可选）
        }
    ]
}
```

### 核心功能
- **仓库元数据存储**：保存每个仓库的描述和分类信息
- **缓存持久化**：作为内存缓存的持久化备份
- **快速检索**：支持按仓库名称快速查找描述信息
- **自动化配置**：运行UI界面触发API后自动生成默认JSON配置

### 当前配置机制
**自动生成配置**：
- 当首次访问Web UI或触发仓库发现API时，系统会自动创建包含当前仓库的Mirror.json文件
- 新推送的镜像会自动添加到配置文件中
- 提供基础的默认描述和分类信息

**手动配置建议**：
将系统自动生成的Mirror.json文件内容发给AI，让AI根据JSON文件格式和仓库名称自动生成完整的描述、分类和标签，避免人工费时费力。后期计划接入AI的API实现自动生成。


### 管理方式
1. **自动更新**：当新镜像推送时自动添加记录
2. **手动编辑**：可直接修改配置文件
3. **缓存同步**：修改后会自动同步到内存缓存

## 🔒 安全指南

### 访问控制
- 配置防火墙规则，限制访问IP
- 使用HTTPS加密传输

## 📊 监控和日志

### 关键指标监控
- 存储空间使用率
- Registry服务可用性
- API响应时间
- 镜像操作统计

## 🔄 升级和维护

### 版本升级
```bash
# 拉取最新镜像
docker-compose pull      # 传统版本
# 或
docker compose pull      # 新版本

# 重启服务
docker-compose down      # 传统版本
docker-compose up -d     # 传统版本
# 或
docker compose down      # 新版本
docker compose up -d     # 新版本
```

##  贡献指南

### 开发环境搭建
```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
python registry_web.py
```

### 提交PR流程
1. Fork项目仓库: https://github.com/YunJian101/Docker-Registry-Manager
2. 创建功能分支
3. 提交代码变更
4. 创建Pull Request到主仓库

## 📄 许可证

本项目采用GNU通用公共许可证v3.0 (GPL-3.0)，详见LICENSE文件。

## 📞 支持与反馈

### 问题报告
- GitHub Issues: https://github.com/YunJian101/Docker-Registry-Manager/issues
- 文档更新: 提交Pull Request改进文档

### 社区支持
- 项目地址: https://github.com/YunJian101/Docker-Registry-Manager

## 🔮 未来发展计划

### 核心优化方向
- [ ] **镜像完整性校验** - 加强镜像安全性验证
- [ ] **用户认证系统** - 添加用户身份验证和权限管理
- [ ] **性能优化** - 提升系统响应速度和并发处理能力
- [ ] **异常捕获** - 完善错误处理和异常监控机制
- [ ] **AI智能描述** - 引入AI自动生成仓库介绍和标签描述



## 💝 赞助作者

如果本项目对您有帮助，欢迎通过以下方式赞助：

**支付宝 / 微信**：转账时备注"随机图API赞助"

<!-- 支付方式图片 -->
<div style="display: flex; gap: 20px;">
  <img src="images/Alipay-Payment.jpg" alt="支付宝支付" width="200">
  <img src="images/WeChat-Pay.png" alt="微信支付" width="200">
</div>

---

*最后更新: 2026年1月7日*  
*文档版本: v1.0*