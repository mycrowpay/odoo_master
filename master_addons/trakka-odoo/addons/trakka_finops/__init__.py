from . import models

def post_init_hook(cr, registry):
    from .models.setup import ensure_finops_setup
    ensure_finops_setup(cr, registry)
