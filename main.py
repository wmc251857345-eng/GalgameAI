"""PyInstaller 打包入口：backend 包需要相对导入，必须从包外以 main 方式启动。

用法（打包后 exe 双击）即调用 backend.app.main()。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app import main

if __name__ == "__main__":
    main()
