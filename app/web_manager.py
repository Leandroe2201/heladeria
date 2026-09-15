import socket
import sys
from pathlib import Path
from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, pyqtSignal, QTimer
from app.settings_service import get_setting


def local_ip():
    """IP LAN preferida para abrir el panel desde otro equipo de la red."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip and not ip.startswith('127.'):
                return ip
    except Exception:
        pass
    return '127.0.0.1'


def port_is_open(port):
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=0.25):
            return True
    except OSError:
        return False


class WebServerManager(QObject):
    status_changed = pyqtSignal(bool)
    output = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._read_err)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)

    def _read(self):
        self.output.emit(bytes(self.process.readAllStandardOutput()).decode(errors='ignore'))

    def _read_err(self):
        self.output.emit(bytes(self.process.readAllStandardError()).decode(errors='ignore'))

    def _finished(self, *_):
        QTimer.singleShot(150, lambda: self.status_changed.emit(self.is_running()))

    def _process_error(self, error):
        self.output.emit(f'Error al iniciar el servidor web: {error}\n')
        self.status_changed.emit(self.is_running())

    def port(self):
        try:
            return int(get_setting('web_port', '5050'))
        except Exception:
            return 5050

    def owns_process(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def is_running(self):
        # Reconoce tanto el proceso iniciado desde la app como un iniciar_web.bat externo.
        return self.owns_process() or port_is_open(self.port())

    def start(self):
        port = self.port()
        if port_is_open(port):
            self.output.emit(f'El puerto {port} ya está activo. El Panel Web parece estar levantado.\n')
            self.status_changed.emit(True)
            return True
        if self.owns_process():
            self.status_changed.emit(True)
            return True

        env = QProcessEnvironment.systemEnvironment()
        env.insert('HELADERIA_WEB_PORT', str(port))
        self.process.setProcessEnvironment(env)
        project_root = str(Path(__file__).resolve().parent.parent)
        self.process.setWorkingDirectory(project_root)
        self.output.emit(f'Iniciando Panel Web en puerto {port}...\n')
        self.process.start(sys.executable, ['-u', '-m', 'app.web_server'])
        if not self.process.waitForStarted(4000):
            self.output.emit('No se pudo iniciar el proceso web. Revisá el registro de errores.\n')
            self.status_changed.emit(False)
            return False
        # Waitress/Flask necesita unos instantes para comenzar a escuchar.
        QTimer.singleShot(900, lambda: self.status_changed.emit(self.is_running()))
        return True

    def stop(self):
        if self.owns_process():
            self.process.terminate()
            if not self.process.waitForFinished(2500):
                self.process.kill()
                self.process.waitForFinished(1000)
            self.output.emit('Panel Web detenido.\n')
        elif port_is_open(self.port()):
            self.output.emit('El Panel Web fue iniciado fuera del sistema. Cerrá la ventana de iniciar_web.bat para detenerlo.\n')
        self.status_changed.emit(self.is_running())

    def restart(self):
        if self.owns_process():
            self.stop()
        QTimer.singleShot(250, self.start)

    def url(self):
        return f'http://{local_ip()}:{self.port()}'

    def local_url(self):
        return f'http://127.0.0.1:{self.port()}'
