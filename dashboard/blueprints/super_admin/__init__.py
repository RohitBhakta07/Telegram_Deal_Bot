from flask import Blueprint

super_admin_bp = Blueprint('super_admin', __name__, template_folder='../../templates/super_admin')

from . import routes # Import routes taaki wo app se jud jayein