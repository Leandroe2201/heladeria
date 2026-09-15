from app.modules.base import BaseDataPage
class UsuariosPage(BaseDataPage):
    def __init__(self, back_callback):
        super().__init__("👤 Usuarios y permisos","users",[("id","ID"),("name","Nombre"),("role","Rol"),("active","Activo")],back_callback,"name")
