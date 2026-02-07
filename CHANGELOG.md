# 更新日志

本项目的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)，
本项目遵循 [语义化版本控制](https://semver.org/spec/v2.0.0.html)。··

## [v1.1.1] - 2026-02-08
### 新增
- GitHub Actions自动化发布流程完整实现
- 三标签Docker镜像构建策略 (具体版本/大版本/latest)
- 智能标签分类系统 (正式版本vs非正式版本)
- CHANGELOG.md更新日志管理
- 前后端分离架构重构完成

### 更改
- 优化Docker镜像构建配置，支持多架构(amd64/arm64)
- 改进README文档结构和自动化发布说明
- 完善项目目录结构和代码组织

### 修复
- 修复版本标签解析逻辑
- 优化镜像推送和Release创建流程
- 改善错误处理和日志输出

## [v1.0.1] - 2026-02-08
### 新增
- GitHub Actions自动化发布流程初步实现
- 三标签Docker镜像构建策略
- 智能标签分类系统
- CHANGELOG.md更新日志模板

### 更改
- 重构项目为前后端分离架构
- 优化Docker镜像构建配置
- 改进README文档结构

### 修复
- 修复版本标签解析逻辑
- 优化镜像推送流程

## [v1.0.0] - 2026-02-07
### 新增
- 初始版本发布
- 基础的Docker Registry管理功能
- Web UI界面
- 镜像浏览和删除功能
- 存储监控和垃圾回收

[未发布]: https://github.com/YunJian101/Docker-Registry-Manager/compare/v1.7.1...HEAD
[v1.7.1]: https://github.com/YunJian101/Docker-Registry-Manager/compare/v1.0.1...v1.7.1
[v1.0.1]: https://github.com/YunJian101/Docker-Registry-Manager/compare/v1.0.0...v1.0.1
[v1.0.0]: https://github.com/YunJian101/Docker-Registry-Manager/releases/tag/v1.0.0