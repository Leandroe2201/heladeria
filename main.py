import sys
from PyQt6.QtWidgets import QApplication, QDialog

from app.database import init_database
from app.auth import LoginDialog
from app.main_window import MainWindow


def main():
    init_database()
    app = QApplication(sys.argv)
    app.setApplicationName('Heladería - Sistema Integral')
    login = LoginDialog()
    if login.exec() != QDialog.DialogCode.Accepted or not login.user:
        return
    window = MainWindow(login.user)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
