"""程序入口：创建应用并显示主窗口。"""

import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def main():
    # 每个桌面程序只需要一个 QApplication，负责管理窗口和用户操作。
    app = QApplication(sys.argv)
    app.setApplicationName("铁路运单草单审核助手")

    window = MainWindow()
    window.show()

    # 启动事件循环，让程序持续响应点击、输入等操作。
    return app.exec()


if __name__ == "__main__":
    # 直接运行本文件时才启动窗口；导入本文件时不会启动。
    sys.exit(main())
