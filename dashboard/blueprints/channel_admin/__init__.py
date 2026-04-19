from flask import Blueprint

channel_admin_bp = Blueprint('channel_admin', __name__, template_folder='../../templates/channel_admin')

from . import routes