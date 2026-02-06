#!/usr/bin/env python3
"""
Docker Registry Manager - 应用入口文件
负责启动Flask应用和服务配置
"""

from backend.api import app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)